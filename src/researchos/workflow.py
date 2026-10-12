import asyncio
import json
import re
import traceback
from pathlib import Path
from typing import Any

import httpx

from researchos import store
from researchos.agents import (CHECK_SYSTEM, EXTRACT_SYSTEM, IMPACT_FEASIBILITY_SYSTEM, LEAD_SYSTEM,
                               NOVELTY_SYSTEM, REVIEW_SYSTEM, STRATEGY_SYSTEM, SYNTH_SYSTEM,
                               parse_json, paper_context)
from researchos.config import settings
from researchos.fulltext import fetch_open_access_fulltext, locate_fulltext_quote
from researchos.providers.local_openai import LocalOpenAIProvider
from researchos.search import search_branch
from researchos.web_reader import read_public_page


_TOPIC_STOPWORDS = {
    "a", "about", "an", "and", "are", "as", "at", "based", "be", "by", "can", "current", "describe",
    "did", "do", "effect", "evaluate", "evaluation", "finding", "find", "for", "from", "good", "how",
    "in", "into", "is", "it", "latest", "make", "methods", "method", "new", "of", "on", "or", "paper",
    "papers", "prior", "research", "review", "reviews", "study", "studies", "the", "their", "this", "to",
    "using", "use", "what", "when", "where", "which", "with", "work", "works",
}


def _topic_tokens(value: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", value.casefold())
    tokens: set[str] = set()
    index = 0
    while index < len(words):
        word = words[index]
        if word == "finger" and index + 1 < len(words) and words[index + 1] in {"print", "printing", "prints"}:
            word = "fingerprint"
            index += 1
        else:
            word = {"web": "website", "websites": "website", "browsers": "browser",
                    "fingerprinting": "fingerprint", "fingerprinted": "fingerprint",
                    "fingerprints": "fingerprint", "onion": "tor"}.get(word, word)
            if len(word) > 5 and word.endswith("ing"):
                word = word[:-3]
            elif len(word) > 5 and word.endswith("ed"):
                word = word[:-2]
            elif len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
                word = word[:-1]
        if (len(word) > 2 or word in {"ai", "3d", "2d"}) and word not in _TOPIC_STOPWORDS:
            tokens.add(word)
        index += 1
    return tokens


def research_topic_terms(question: str, brief: dict[str, Any] | None = None) -> set[str]:
    scope = " ".join([question, *(str(value) for value in (brief or {}).values() if value)])
    return _topic_tokens(scope)


def topic_relevance_score(paper: dict[str, Any], topic_terms: set[str]) -> float:
    """Return a conservative lexical overlap score, or zero for a clear mismatch."""
    if not topic_terms:
        return 1.0
    source_text = " ".join(str(paper.get(key) or "") for key in ("title", "abstract", "evidence_text"))
    source_terms = _topic_tokens(source_text)
    matches = topic_terms.intersection(source_terms)
    # For a website/browser fingerprinting query, generic Tor and website
    # mentions are not enough: require fingerprinting content or a clearly
    # related Tor traffic-analysis/defense topic. This blocks broad Tor papers
    # that happen to mention websites, while retaining adjacent methodology.
    if "fingerprint" in topic_terms and "tor" in topic_terms:
        has_fingerprinting_context = "fingerprint" in source_terms and bool(
            source_terms.intersection({"website", "browser", "tor"})
        )
        adjacent_tor_terms = {
            "traffic", "obfuscation", "encrypted", "sidechannel", "trace", "monitoring", "classification",
        }
        has_adjacent_tor_context = (
            "tor" in source_terms and bool(source_terms.intersection(adjacent_tor_terms))
        )
        if not has_fingerprinting_context and not has_adjacent_tor_context:
            return 0.0
    minimum_matches = 1 if len(topic_terms) == 1 else 2
    if len(matches) < minimum_matches:
        # Keep a narrow set of adjacent Tor traffic-analysis/defense work: it
        # may inform a fingerprinting review even when a short title omits the
        # exact phrase "website fingerprinting".
        adjacent_tor_terms = {"traffic", "obfuscation", "encrypted", "sidechannel", "trace", "monitoring", "classification"}
        if "tor" not in topic_terms or "tor" not in source_terms or not source_terms.intersection(adjacent_tor_terms):
            return 0.0
        return max(len(matches), 1) / len(topic_terms)
    return len(matches) / len(topic_terms)


def update(run_id: str, stage: str, progress: int, message: str, agent: str = "Research Lead") -> None:
    store.update_run(run_id, status="running", stage=stage, progress=progress)
    store.add_event(run_id, agent, stage, message)


def balance_search_results(branches: list[tuple[str, list[dict[str, Any]]]],
                           topic_terms: set[str] | None = None) -> list[tuple[dict[str, Any], str, float]]:
    """Interleave provider and query-branch hits before applying the evidence cap."""
    providers = ("Crossref", "Europe PMC", "OpenAlex")
    queues = [(name, {provider: [paper for paper in papers if paper.get("source") == provider]
                      for provider in providers}) for name, papers in branches]
    max_rank = max((len(queue) for _, by_provider in queues for queue in by_provider.values()), default=0)
    balanced: list[tuple[dict[str, Any], str, float]] = []
    for rank in range(max_rank):
        for branch_name, by_provider in queues:
            for provider in providers:
                provider_queue = by_provider[provider]
                if rank < len(provider_queue):
                    paper = provider_queue[rank]
                    score = topic_relevance_score(paper, topic_terms) if topic_terms else 0.5
                    balanced.append((paper, branch_name, score))
    return balanced


def paper_identity_key(paper: dict[str, Any]) -> str:
    doi = str(paper.get("doi") or "").casefold().removeprefix("https://doi.org/")
    if doi:
        return f"doi:{doi}"
    title = " ".join(str(paper.get("title") or "").casefold().split())
    return f"title:{title}"


def merge_index_record(target: dict[str, Any], candidate: dict[str, Any], branch: str) -> None:
    source = str(candidate.get("source") or "")
    if source and source not in target.setdefault("sources", []):
        target["sources"].append(source)
    target.setdefault("search_branches", [])
    if branch not in target["search_branches"]:
        target["search_branches"].append(branch)
    for field in ("doi", "abstract", "url", "open_access_url", "pmcid", "journal", "publisher", "volume", "issue", "pages", "year"):
        value = candidate.get(field)
        existing = target.get(field)
        if value and (not existing or (field == "abstract" and len(str(value)) > len(str(existing)))):
            target[field] = value
    target["is_open_access"] = bool(target.get("is_open_access") or candidate.get("is_open_access"))
    if source == "Europe PMC" and candidate.get("pmcid") and candidate.get("is_open_access"):
        target["fulltext_source"] = "Europe PMC"
    if not target.get("authors") and candidate.get("authors"):
        target["authors"] = candidate["authors"]


def source_text(paper: dict[str, Any]) -> str:
    return str(paper.get("evidence_text") or paper.get("abstract") or "")


def source_location(paper: dict[str, Any], quote: str) -> str:
    if paper.get("source") == "User PDF":
        return store.find_passage_location(paper["id"], quote)
    if paper.get("source") == "Web page":
        return "Public web page excerpt"
    if paper.get("full_text_passages"):
        return locate_fulltext_quote(paper, quote)
    return "Abstract"


MATRIX_ASPECTS = [
    ("study_design", "Study design"), ("cohort_or_dataset", "Cohort or dataset"),
    ("sample_size", "Sample size"), ("preprocessing", "Preprocessing"),
    ("model_architecture", "Model architecture"), ("baselines", "Baselines"),
    ("data_splits", "Data splits"), ("experimental_protocol", "Experimental protocol"),
    ("metrics", "Reported metrics"), ("statistical_tests", "Uncertainty or statistical tests"),
    ("ablations", "Ablations"), ("limitations", "Stated limitations"),
    ("reproducibility", "Reproducibility details"),
]


def build_evidence_matrix(papers: list[dict[str, Any]], details: list[dict[str, Any]],
                          metrics: list[dict[str, Any]], labels: dict[str, str],
                          extraction_available: bool = True) -> list[dict[str, Any]]:
    aliases = {"dataset": "cohort_or_dataset", "sample": "sample_size", "baseline": "baselines",
               "data_split": "data_splits", "evaluation_protocol": "experimental_protocol",
               "experimental_setup": "experimental_protocol", "method": "model_architecture",
               "limitation": "limitations", "statistical_test": "statistical_tests",
               "uncertainty": "statistical_tests"}
    result = []
    for paper in papers:
        paper_id = paper["id"]
        facts: dict[str, list[dict[str, Any]]] = {}
        for item in details:
            if item.get("paper_id") != paper_id:
                continue
            aspect = aliases.get(item.get("aspect"), item.get("aspect"))
            facts.setdefault(aspect, []).append(item)
        metric_facts = [item for item in metrics if item.get("paper_id") == paper_id]
        cells = []
        for aspect, title in MATRIX_ASPECTS:
            matching = metric_facts if aspect == "metrics" else facts.get(aspect, [])
            if matching:
                evidence = [{"value": item.get("reported_result") or item.get("metric") or item.get("value") or item.get("evidence_quote") or "Reported in source",
                             "evidence_quote": item.get("evidence_quote", ""),
                             "location": item.get("location", "Exact source passage"),
                             "source_label": labels.get(paper_id, ""),
                             "reported_metric": item.get("metric", ""),
                             "reported_result": item.get("reported_result", "")}
                            for item in matching]
                status = "evidence_found"
            else:
                missing_value = "Not found in available text" if extraction_available else "Not assessed — extractor unavailable"
                evidence = [{"value": missing_value, "evidence_quote": "",
                             "location": paper.get("evidence_kind", "Available source text"),
                             "source_label": labels.get(paper_id, "")}]
                status = "not_found" if extraction_available else "not_assessed"
            cells.append({"aspect": aspect, "label": title, "status": status, "evidence": evidence})
        result.append({"paper_id": paper_id, "source_label": labels.get(paper_id, ""),
                       "title": paper.get("title", ""), "year": paper.get("year"),
                       "source": paper.get("source", ""), "evidence_kind": paper.get("evidence_kind", "Abstract"),
                       "url": paper.get("full_text_url") or paper.get("url", ""), "cells": cells})
    return result


def comparable_metric_groups(metrics: list[dict[str, Any]], matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def normalized(value: Any) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))

    context: dict[str, dict[str, str]] = {}
    for paper in matrix:
        fields = {}
        for cell in paper["cells"]:
            if cell["aspect"] not in {"cohort_or_dataset", "data_splits", "experimental_protocol"}:
                continue
            evidence = cell["evidence"]
            if evidence and evidence[0].get("evidence_quote"):
                fields[cell["aspect"]] = normalized(evidence[0].get("value") or evidence[0].get("evidence_quote"))
        context[paper["paper_id"]] = fields
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for item in metrics:
        result = str(item.get("reported_result") or "").strip()
        metric = normalized(item.get("metric"))
        if not metric or not re.search(r"\d", result):
            continue
        fields = context.get(item.get("paper_id"), {})
        dataset, split, protocol = (fields.get("cohort_or_dataset", ""), fields.get("data_splits", ""),
                                    fields.get("experimental_protocol", ""))
        if not dataset or not split or not protocol:
            continue
        grouped.setdefault((metric, dataset, split, protocol), []).append(item)
    groups = []
    for key, values in grouped.items():
        if len({item.get("paper_id") for item in values}) < 2:
            continue
        groups.append({"metric": values[0].get("metric", ""), "dataset": values[0].get("dataset") or key[1],
                       "data_split": values[0].get("data_split") or key[2],
                       "evaluation_protocol": values[0].get("evaluation_protocol") or key[3],
                       "basis": "Same normalized metric, dataset, split, and evaluation-protocol excerpts were found.",
                       "results": [{"paper_id": item.get("paper_id"), "source_label": item.get("source_label"),
                                    "title": item.get("title"), "reported_result": item.get("reported_result"),
                                    "evidence_quote": item.get("evidence_quote"), "location": item.get("location"),
                                    "url": item.get("url")} for item in values]})
    return groups


async def optional_completion(provider: LocalOpenAIProvider, system: str, prompt: str,
                              max_tokens: int = 1400) -> str | None:
    try:
        return await provider.complete(system, prompt, max_tokens=max_tokens)
    except Exception:
        return None


def enum_valid(data: dict[str, Any], key: str, allowed: set[str], fallback: str) -> bool:
    if data.get(key) not in allowed:
        data[key] = fallback
        return False
    return True


async def run_research(run_id: str, project_id: str, question: str, web_urls: list[str] | None = None,
                       brief: dict[str, Any] | None = None) -> None:
    provider = LocalOpenAIProvider(role="research")
    brief = brief or {}
    topic_terms = research_topic_terms(question, brief)
    paper_ids: list[str] = []
    try:
        update(run_id, "interview", 4, "The Research Interviewer is checking the brief for missing choices that could change the review.", "Research Interviewer")
        lead_input = json.dumps({"question": question, "brief": brief}, ensure_ascii=False)
        lead_response = await optional_completion(provider, LEAD_SYSTEM, lead_input, 700)
        lead_data = parse_json(lead_response or "") or {}
        branches = lead_data.get("branches") if isinstance(lead_data, dict) else None
        if not isinstance(branches, list) or not branches:
            branches = [
                {"name": "Core literature", "query": question, "purpose": "Find prior work on the main question."},
                {"name": "Methods and evaluation", "query": f"{question} methods evaluation", "purpose": "Identify approaches and evaluation practices."},
                {"name": "Limitations and related work", "query": f"{question} limitations related work", "purpose": "Find related work and stated limitations."},
            ]
        branches = [{"name": str(b.get("name", f"Branch {i + 1}"))[:80], "query": str(b.get("query", question))[:240],
                     "purpose": str(b.get("purpose", "Search this part of the research question."))[:300]}
                    for i, b in enumerate(branches[:3]) if isinstance(b, dict)]
        if not branches:
            branches = [{"name": "Core literature", "query": question, "purpose": "Find prior work on the main question."}]
        clarifying_questions = lead_data.get("clarifying_questions", []) if isinstance(lead_data, dict) else []
        if not isinstance(clarifying_questions, list):
            clarifying_questions = []
        clarifying_questions = [str(item).strip()[:500] for item in clarifying_questions[:5] if str(item).strip()]
        assumptions = lead_data.get("assumptions", []) if isinstance(lead_data, dict) else []
        if not isinstance(assumptions, list):
            assumptions = []
        assumptions = [str(item).strip()[:500] for item in assumptions[:8] if str(item).strip()]
        research_map = {"scope_summary": str(lead_data.get("scope_summary", ""))[:1200] if isinstance(lead_data, dict) else "",
                        "branches": branches, "clarifying_questions": clarifying_questions, "assumptions": assumptions}
        store.add_event(run_id, "Research Interviewer", "interview",
                        f"Saved {len(brief)} brief field(s); {len(clarifying_questions)} clarifying question(s) may affect scope.")
        update(run_id, "planning", 8, "The Research Lead is mapping the brief into distinct literature branches.")
        store.add_event(run_id, "Research Lead", "planning", f"Prepared {len(branches)} focused search branches from the brief.")

        project_document_total = store.project_document_count(project_id)
        project_document_candidates = store.project_documents(project_id)
        eligible_project_documents = [document for document in project_document_candidates
                                      if topic_relevance_score(document, topic_terms) > 0]
        project_documents = store.attach_project_documents_to_run(
            run_id, project_id, [document["id"] for document in eligible_project_documents])
        document_records = []
        for document in project_documents:
            document_records.append(({
                "id": document["id"], "doi": None, "title": document["title"], "authors": [], "year": None,
                "abstract": "", "evidence_text": document["evidence_text"], "source": "User PDF",
                "source_id": document["source_id"], "url": "", "open_access_url": "",
                "local_filename": document["local_filename"], "page_count": document["page_count"],
                "text_truncated": bool(document["truncated"]),
            }, "Project PDF", 1.0))
        if project_documents:
            store.add_event(run_id, "Paper Librarian", "screening",
                            f"Attached {len(project_documents)} topic-matched project PDF(s) with page-level extracted text.")
        excluded_project_documents = [document for document in project_document_candidates
                                      if document["id"] not in {item["id"] for item in project_documents}]
        if excluded_project_documents:
            store.add_event(run_id, "Paper Librarian", "screening",
                            f"Left {len(excluded_project_documents)} project PDF(s) out of this run because their title and extracted text did not match the research topic. The files remain in the project library and PDF analysis workspace.")
        if project_document_total > len(project_document_candidates):
            store.add_event(run_id, "Paper Librarian", "screening",
                            f"This run checks the {len(project_document_candidates)} most recent project PDF(s); {project_document_total - len(project_document_candidates)} older PDF(s) were not considered.")

        update(run_id, "web_reading", 12, "The Web Reader is opening the public pages you added.", "Web Reader")
        page_results = await asyncio.gather(*(read_public_page(url) for url in (web_urls or [])[:3]), return_exceptions=True)
        page_records: list[tuple[dict[str, Any], str, float]] = []
        source_errors: list[str] = []
        for url, result in zip((web_urls or [])[:3], page_results):
            if isinstance(result, Exception):
                source_errors.append(f"Web page: {type(result).__name__}: {str(result)[:140]}")
                continue
            page_records.append(({
                "doi": None,
                "title": result["title"],
                "authors": [],
                "year": None,
                "abstract": result["text"],
                "source": "Web page",
                "source_id": result["url"],
                "url": result["url"],
                "open_access_url": "",
            }, "User-selected web page", 1.0))
        if page_records:
            store.add_event(run_id, "Web Reader", "web_reading", f"Read {len(page_records)} public page(s) and saved bounded text excerpts with their URLs.")

        update(run_id, "searching", 18, "Search agents are querying Crossref, Europe PMC, and OpenAlex in parallel.", "Search Agents")
        branch_results = await asyncio.gather(*(search_branch(branch["query"]) for branch in branches), return_exceptions=True)
        aggregate: list[tuple[dict[str, Any], str, float]] = []
        aggregate.extend(document_records)
        aggregate.extend(page_records)
        searchable_branches: list[tuple[str, list[dict[str, Any]]]] = []
        for branch, result in zip(branches, branch_results):
            if isinstance(result, Exception):
                source_errors.append(f"{branch['name']}: {type(result).__name__}")
                continue
            papers, errors = result
            source_errors.extend(errors)
            searchable_branches.append((branch["name"], papers))
        search_hits_count = sum(len(papers) for _, papers in searchable_branches)
        branch_search_log = []
        unique_index: dict[str, dict[str, Any]] = {}
        for branch, result in zip(branches, branch_results):
            if isinstance(result, Exception):
                branch_search_log.append({"name": branch["name"], "query": branch["query"], "purpose": branch["purpose"],
                                          "provider_hit_counts": {"Crossref": 0, "Europe PMC": 0, "OpenAlex": 0},
                                          "errors": [type(result).__name__]})
                continue
            papers, errors = result
            counts = {provider: sum(1 for paper in papers if paper.get("source") == provider)
                      for provider in ("Crossref", "Europe PMC", "OpenAlex")}
            branch_search_log.append({"name": branch["name"], "query": branch["query"], "purpose": branch["purpose"],
                                      "provider_hit_counts": counts, "total_hits": len(papers), "errors": errors})
        for branch_name, papers in searchable_branches:
            for paper in papers:
                key = paper_identity_key(paper)
                if key not in unique_index:
                    source = str(paper.get("source") or "")
                    unique_index[key] = {**paper, "sources": [source] if source else [], "search_branches": [branch_name]}
                else:
                    merge_index_record(unique_index[key], paper, branch_name)
        screened_out_search_hits = 0
        topical_branches = [(branch["name"], []) for branch in branches]
        branch_lookup = {name: papers for name, papers in topical_branches}
        for paper in unique_index.values():
            if topic_relevance_score(paper, topic_terms) > 0:
                branch_name = next((name for name in paper.get("search_branches", []) if name in branch_lookup),
                                   branches[0]["name"])
                branch_lookup[branch_name].append(paper)
            else:
                screened_out_search_hits += 1
        ranking_method = "balanced scholarly-index order"
        if store.get_app_setting("specter2_enabled") == "true":
            from researchos.paper_ranker import dependency_status, rank_papers

            ranker_environment = dependency_status()
            candidate_map: dict[str, dict[str, Any]] = {}
            for _, papers in topical_branches:
                for paper in papers:
                    doi = str(paper.get("doi") or "").casefold().removeprefix("https://doi.org/")
                    key = f"doi:{doi}" if doi else "title:" + " ".join(str(paper.get("title") or "").casefold().split())
                    existing = candidate_map.get(key)
                    if not existing or len(str(paper.get("abstract") or "")) > len(str(existing.get("abstract") or "")):
                        candidate_map[key] = paper
            if ranker_environment["dependencies_ready"] and ranker_environment["weights_cached"] and candidate_map:
                try:
                    ranked = await rank_papers(question, list(candidate_map.values()))
                    semantic_scores = {}
                    for paper in ranked:
                        doi = str(paper.get("doi") or "").casefold().removeprefix("https://doi.org/")
                        key = f"doi:{doi}" if doi else "title:" + " ".join(str(paper.get("title") or "").casefold().split())
                        semantic_scores[key] = paper.get("semantic_score", 0.0)
                    for branch_index, (branch_name, papers) in enumerate(topical_branches):
                        for paper in papers:
                            doi = str(paper.get("doi") or "").casefold().removeprefix("https://doi.org/")
                            key = f"doi:{doi}" if doi else "title:" + " ".join(str(paper.get("title") or "").casefold().split())
                            paper["semantic_score"] = semantic_scores.get(key, 0.0)
                        papers.sort(key=lambda paper: (-float(paper.get("semantic_score") or 0),
                                                       -int(paper.get("year") or 0)))
                        topical_branches[branch_index] = (branch_name, papers)
                    ranking_method = "SPECTER2 relevance within each branch and source, then provider-balanced selection"
                    store.add_event(run_id, "Search Agents", "searching",
                                    f"SPECTER2 semantically ranked {len(candidate_map)} topic-matched scholarly records before the retained-source limit.")
                except Exception as exc:
                    source_errors.append(f"SPECTER2 ranking: {type(exc).__name__}")
            elif not ranker_environment["dependencies_ready"] or not ranker_environment["weights_cached"]:
                ranking_method = "balanced scholarly-index order (SPECTER2 setup incomplete)"
        # Interleave query branches and indexes before applying the run limit. This
        # prevents the first branch/provider from consuming the evidence set. A
        # topic screen runs first so clearly unrelated index matches never occupy
        # the retained source-link budget.
        aggregate.extend(balance_search_results(topical_branches, topic_terms))
        # Deduplicate across providers by DOI and otherwise by normalized title.
        unique: dict[str, tuple[dict[str, Any], str, float]] = {}
        for paper, branch_name, score in aggregate:
            if paper.get("source") == "User PDF":
                key = "pdf:" + paper.get("source_id", paper["title"])
            elif paper.get("source") == "Web page":
                key = "web:" + paper.get("source_id", paper["title"])
            else:
                key = ("doi:" + paper["doi"].lower()) if paper.get("doi") else "title:" + " ".join(paper["title"].lower().split())
            if key not in unique or (not unique[key][0].get("abstract") and paper.get("abstract")):
                unique[key] = (paper, branch_name, score)
        unique_candidates = list(unique.values())
        records = unique_candidates[:settings.max_papers_per_run]
        analysis_limit = max(0, min(settings.max_analysis_papers, len(records)))
        for index, (paper, branch_name, score) in enumerate(records):
            # Keep bibliographic links for the bounded report set, but retain full
            # abstracts only for records actually passed into local model analysis.
            saved_record = paper if index < analysis_limit or paper.get("source") == "User PDF" else {
                **paper, "abstract": ""}
            paper_ids.append(store.save_paper(saved_record, run_id, branch_name, score))
        store.add_event(run_id, "Paper Librarian", "screening",
                        f"Searched {search_hits_count} scholarly-index hits; screened out {screened_out_search_hits} with insufficient topic overlap; retained topic-matched project PDFs and user-selected pages, then deduplicated to {len(unique_candidates)} records. Kept {len(records)} source links and full abstracts for {analysis_limit} records reserved for local analysis. Unretained new hits were discarded after this run.")
        update(run_id, "extracting", 40, "The Evidence Extractor is finding claims supported by saved abstracts and page excerpts.", "Evidence Extractor")

        papers_for_model = []
        for index, (paper, branch_name, score) in enumerate(records[:analysis_limit]):
            item = dict(paper)
            item["id"] = paper.get("id") or paper_ids[index]
            item["evidence_kind"] = "Abstract"
            papers_for_model.append(item)
        fulltext_count = 0
        fulltext_candidates = [paper for paper in papers_for_model
                               if paper.get("fulltext_source", paper.get("source")) == "Europe PMC"
                               and paper.get("is_open_access") and paper.get("pmcid")]
        if fulltext_candidates and settings.max_open_access_fulltext_per_run > 0:
            update(run_id, "full_text", 36,
                   f"Checking Europe PMC's documented full-text API and explicit reuse license for up to {min(settings.max_open_access_fulltext_per_run, len(fulltext_candidates))} analyzed papers.",
                   "Evidence Extractor")
            try:
                async with httpx.AsyncClient(timeout=35, follow_redirects=True) as fulltext_client:
                    for paper in fulltext_candidates[:settings.max_open_access_fulltext_per_run]:
                        try:
                            fulltext = await fetch_open_access_fulltext(paper, fulltext_client)
                        except Exception as exc:
                            source_errors.append(f"Europe PMC full text ({paper.get('pmcid')}): {type(exc).__name__}")
                            continue
                        if not fulltext:
                            continue
                        paper["full_text_passages"] = fulltext["passages"]
                        paper["evidence_text"] = "\n\n".join(
                            f"[{passage['locator']}] {passage['text']}" for passage in fulltext["passages"])
                        paper["evidence_kind"] = f"Europe PMC full text · {fulltext['license']} · {len(fulltext['passages'])} passages"
                        paper["full_text_license"] = fulltext["license"]
                        paper["full_text_license_statement"] = fulltext["license_statement"]
                        paper["full_text_url"] = fulltext["url"]
                        paper["full_text_tables"] = fulltext["tables"]
                        paper["full_text_figure_captions"] = fulltext["figures"]
                        fulltext_count += 1
                if fulltext_count:
                    store.add_event(run_id, "Evidence Extractor", "full_text",
                                    f"Used bounded Europe PMC full-text passages for {fulltext_count} paper(s) with an explicit adaptation-permitting Creative Commons license. Full text was analyzed in memory; only quoted evidence and provenance are kept in the report.")
            except Exception as exc:
                source_errors.append(f"Europe PMC full text: {type(exc).__name__}")
        citation_labels_by_id = {paper["id"]: f"P{index + 1}" for index, paper in enumerate(papers_for_model)}
        extraction = await optional_completion(provider, EXTRACT_SYSTEM,
                                               paper_context(papers_for_model, analysis_limit), 8200)
        extraction_data = parse_json(extraction or "") or {}
        candidates = extraction_data.get("claims", []) if isinstance(extraction_data, dict) else []
        validated_claims = []
        for candidate in candidates[:24] if isinstance(candidates, list) else []:
            if not isinstance(candidate, dict):
                continue
            paper = next((p for p in papers_for_model if p["id"] == candidate.get("paper_id")), None)
            quote = str(candidate.get("evidence_quote", "")).strip()
            claim = str(candidate.get("claim", "")).strip()
            source_text_value = source_text(paper) if paper else ""
            if paper and claim and quote and quote.casefold() in source_text_value.casefold():
                location = source_location(paper, quote)
                validated_claims.append({"paper_id": paper["id"], "title": paper["title"], "claim": claim,
                                         "evidence_quote": quote, "limitation": str(candidate.get("limitation", "")),
                                         "source": paper.get("source", ""), "url": paper.get("url", ""),
                                         "location": location})
        rejected_extractions = max(0, len(candidates) - len(validated_claims)) if isinstance(candidates, list) else 0
        if extraction and not candidates:
            store.add_event(run_id, "Evidence Extractor", "extracting", "The local model returned no source-grounded claim candidates.")
        elif rejected_extractions:
            store.add_event(run_id, "Evidence Extractor", "extracting",
                            f"Rejected {rejected_extractions} candidate claim(s) because their source ID, exact quote, or text match failed validation.")

        # Metric entries are reported only when their quote is found verbatim in
        # the corresponding abstract, PDF excerpt, or selected page text.
        extracted_metrics = extraction_data.get("study_metrics", []) if isinstance(extraction_data, dict) else []
        study_metrics: list[dict[str, Any]] = []
        if isinstance(extracted_metrics, list):
            for candidate in extracted_metrics[:analysis_limit * 16]:
                if not isinstance(candidate, dict):
                    continue
                paper = next((p for p in papers_for_model if p["id"] == candidate.get("paper_id")), None)
                quote = str(candidate.get("evidence_quote", "")).strip()
                metric = str(candidate.get("metric", "")).strip()
                source_text_value = source_text(paper) if paper else ""
                if not paper or not metric or not quote or quote.casefold() not in source_text_value.casefold():
                    continue
                study_metrics.append({
                    "metric": metric[:180],
                    "what_it_measures": str(candidate.get("what_it_measures", "")).strip()[:500],
                    "reported_result": str(candidate.get("reported_result", "")).strip()[:500],
                    "evidence_quote": quote[:1000],
                    "source_label": citation_labels_by_id.get(paper["id"], ""),
                    "paper_id": paper["id"], "title": paper.get("title", ""),
                    "year": paper.get("year"), "source": paper.get("source", ""),
                    "location": source_location(paper, quote),
                    "evidence_kind": paper.get("evidence_kind", "Abstract"),
                    "license": paper.get("full_text_license", ""),
                    "url": paper.get("full_text_url") or paper.get("url") or (f"https://doi.org/{paper['doi']}" if paper.get("doi") else ""),
                })
        citable_study_metrics = [
            {**{key: value for key, value in item.items() if key != "paper_id"},
             "paper_id": item["source_label"]}
            for item in study_metrics if item.get("source_label")
        ]
        rejected_metrics = max(0, len(extracted_metrics) - len(study_metrics)) if isinstance(extracted_metrics, list) else 0
        store.add_event(run_id, "Evidence Extractor", "metrics",
                        f"Recorded {len(study_metrics)} explicitly named source metrics with exact matching quotes; rejected {rejected_metrics} unsupported metric entries.")

        allowed_study_aspects = {"study_design", "dataset", "sample", "preprocessing", "model_architecture",
                                 "method", "baseline", "data_split", "experimental_setup", "evaluation_protocol",
                                 "statistical_test", "uncertainty", "ablation", "limitation", "reproducibility"}
        raw_study_details = extraction_data.get("study_details", []) if isinstance(extraction_data, dict) else []
        study_details: list[dict[str, Any]] = []
        details_per_paper: dict[str, int] = {}
        seen_study_details: set[tuple[str, str, str]] = set()
        if isinstance(raw_study_details, list):
            for candidate in raw_study_details[:analysis_limit * 16]:
                if not isinstance(candidate, dict):
                    continue
                paper = next((p for p in papers_for_model if p["id"] == candidate.get("paper_id")), None)
                aspect = str(candidate.get("aspect", "")).strip().casefold()
                quote = str(candidate.get("evidence_quote", "")).strip()
                source_text_value = source_text(paper) if paper else ""
                if not paper or aspect not in allowed_study_aspects or not quote or quote.casefold() not in source_text_value.casefold():
                    continue
                dedupe_key = (paper["id"], aspect, quote.casefold())
                if dedupe_key in seen_study_details or details_per_paper.get(paper["id"], 0) >= 16:
                    continue
                seen_study_details.add(dedupe_key)
                details_per_paper[paper["id"]] = details_per_paper.get(paper["id"], 0) + 1
                location = source_location(paper, quote)
                study_details.append({
                    "aspect": aspect,
                    "value": str(candidate.get("value", "")).strip()[:500],
                    "evidence_quote": quote[:1800],
                    "source_label": citation_labels_by_id.get(paper["id"], ""),
                    "paper_id": paper["id"], "title": paper.get("title", ""),
                    "year": paper.get("year"), "source": paper.get("source", ""),
                    "evidence_kind": paper.get("evidence_kind", "Abstract"),
                    "license": paper.get("full_text_license", ""),
                    "location": location,
                    "url": paper.get("full_text_url") or paper.get("url") or (f"https://doi.org/{paper['doi']}" if paper.get("doi") else ""),
                })
        rejected_study_details = max(0, len(raw_study_details) - len(study_details)) if isinstance(raw_study_details, list) else 0
        store.add_event(run_id, "Evidence Extractor", "study_details",
                        f"Kept {len(study_details)} study-design and experiment excerpts with exact source-text matches; rejected {rejected_study_details} unsupported details.")
        evidence_matrix = build_evidence_matrix(papers_for_model, study_details, study_metrics,
                                                citation_labels_by_id, extraction_available=bool(extraction))
        metric_comparisons = comparable_metric_groups(study_metrics, evidence_matrix)
        store.add_event(run_id, "Evidence Extractor", "evidence_matrix",
                        f"Built a {len(MATRIX_ASPECTS)}-facet evidence matrix for {len(evidence_matrix)} analyzed paper(s); unsupported or absent facets are explicitly marked not found in available text.")

        # Build an annotated bibliography from appraisals whose evidence quotes
        # exactly match source text. Missing facets are explicit so an abstract
        # omission is never mistaken for a weakness in the study.
        allowed_appraisal_aspects = {"what_studied", "relevance", "strengths", "limitations"}
        raw_appraisals = extraction_data.get("paper_appraisals", []) if isinstance(extraction_data, dict) else []
        paper_appraisals: list[dict[str, Any]] = []
        seen_appraisals: set[tuple[str, str]] = set()
        if isinstance(raw_appraisals, list):
            for candidate in raw_appraisals[:analysis_limit * 4]:
                if not isinstance(candidate, dict):
                    continue
                paper = next((p for p in papers_for_model if p["id"] == candidate.get("paper_id")), None)
                aspect = str(candidate.get("aspect", "")).strip().casefold()
                assessment = str(candidate.get("assessment", "")).strip()
                quote = str(candidate.get("evidence_quote", "")).strip()
                source_text_value = source_text(paper) if paper else ""
                key = (paper["id"], aspect) if paper else ("", "")
                if (not paper or aspect not in allowed_appraisal_aspects or not assessment or not quote
                        or quote.casefold() not in source_text_value.casefold() or key in seen_appraisals):
                    continue
                seen_appraisals.add(key)
                location = source_location(paper, quote)
                paper_appraisals.append({
                    "aspect": aspect,
                    "assessment": assessment[:1000],
                    "evidence_quote": quote[:1200],
                    "status": "evidence_found",
                    "source_label": citation_labels_by_id.get(paper["id"], ""),
                    "paper_id": paper["id"], "title": paper.get("title", ""),
                    "year": paper.get("year"), "source": paper.get("source", ""),
                    "location": location,
                    "url": paper.get("full_text_url") or paper.get("url") or (f"https://doi.org/{paper['doi']}" if paper.get("doi") else ""),
                })

        default_appraisal = {
            "what_studied": "The supplied text does not contain enough detail to describe the study; inspect the full paper.",
            "relevance": "Relevance cannot be assessed from the text available to this run.",
            "strengths": "Study strengths cannot be assessed from the text available to this run.",
            "limitations": "No limitation was identified in the text available to this run. This does not mean the full paper has no limitations.",
        }
        for paper in papers_for_model:
            present = {item["aspect"] for item in paper_appraisals if item["paper_id"] == paper["id"]}
            for aspect, message in default_appraisal.items():
                if aspect in present:
                    continue
                paper_appraisals.append({
                    "aspect": aspect, "assessment": message, "evidence_quote": "",
                    "status": "not_assessable", "source_label": citation_labels_by_id.get(paper["id"], ""),
                    "paper_id": paper["id"], "title": paper.get("title", ""),
                    "year": paper.get("year"), "source": paper.get("source", ""),
                    "location": "", "url": paper.get("full_text_url") or paper.get("url") or (f"https://doi.org/{paper['doi']}" if paper.get("doi") else ""),
                })
        rejected_appraisals = max(0, len(raw_appraisals) - sum(item["status"] == "evidence_found" for item in paper_appraisals)) if isinstance(raw_appraisals, list) else 0
        store.add_event(run_id, "Paper Librarian", "appraisal",
                        f"Built {len(paper_appraisals)} annotated-bibliography facets across {len(papers_for_model)} analyzed papers; {rejected_appraisals} unsupported appraisal entries were rejected and missing facets remain marked not assessable.")

        update(run_id, "verifying", 58, "The Fact Checker is reviewing extracted claims against their exact source passages.", "Fact Checker")
        decisions: list[dict[str, Any]] = []
        if validated_claims:
            check_prompt = json.dumps({"claims": validated_claims}, ensure_ascii=False)
            checked = await optional_completion(provider, CHECK_SYSTEM, check_prompt, 1200)
            check_data = parse_json(checked or "") or {}
            raw_decisions = check_data.get("decisions", []) if isinstance(check_data, dict) else []
            if isinstance(raw_decisions, list):
                decisions = [d for d in raw_decisions if isinstance(d, dict)]
        decision_map = {str(d.get("paper_id")): d for d in decisions}
        for item in validated_claims:
            decision = decision_map.get(item["paper_id"], {})
            verdict = str(decision.get("verdict", "QUALIFY")).upper()
            if verdict not in {"SUPPORTED", "QUALIFY", "REJECT"}:
                verdict = "QUALIFY"
            store.save_claim(run_id, item["paper_id"], item["claim"], item["evidence_quote"], verdict.lower(),
                             "Fact Checker", item.get("location", ""))
            item["verdict"] = verdict
            item["checker_reason"] = decision.get("reason", "No independent model verdict was available; quote matched source abstract.")
        store.add_event(run_id, "Fact Checker", "verifying",
                        f"Saved {len(validated_claims)} claims with exact quotes from their supplied source text.")

        update(run_id, "synthesizing", 76, "The Synthesizer is comparing themes, tensions, and next steps.", "Synthesizer")
        synthesis_input = {
            "question": question,
            "brief": brief,
            "research_map": research_map,
            "papers": [{"id": f"P{i + 1}", "title": p.get("title"), "year": p.get("year"),
                        "source": p.get("source"), "doi": p.get("doi"),
                        "source_text": (p.get("evidence_text") or p.get("abstract", ""))[:1300]}
                       for i, (p, _, _) in enumerate(records[:analysis_limit])],
            "claim_reviews": [{**item, "paper_id": citation_labels_by_id.get(item["paper_id"], "unknown source")}
                              for item in validated_claims],
            "study_details": [{**item, "paper_id": item["source_label"]} for item in study_details if item.get("source_label")],
        }
        synthesis_text = await optional_completion(provider, SYNTH_SYSTEM, json.dumps(synthesis_input, ensure_ascii=False), 3200)
        synthesis = parse_json(synthesis_text or "") or {}
        model_analysis_available = isinstance(synthesis, dict) and bool(synthesis)
        if not isinstance(synthesis, dict):
            synthesis = {}

        analyst_input = json.dumps({"question": question, "brief": brief, "research_map": research_map,
                                    "papers": synthesis_input["papers"],
                                    "study_details": synthesis_input["study_details"],
                                    "verified_claims": validated_claims}, ensure_ascii=False)
        update(run_id, "novelty", 80, "The Novelty Analyst is searching the retrieved work for close prior art and unresolved overlap.", "Novelty Analyst")
        novelty_text = await optional_completion(provider, NOVELTY_SYSTEM, analyst_input, 1100)
        novelty_data = parse_json(novelty_text or "")
        novelty_available = isinstance(novelty_data, dict)
        if not novelty_available:
            novelty_data = {"closest_related_work": [], "prior_art_risks": [], "assessment": "undetermined",
                            "basis": "The local analyst did not return a structured assessment.",
                            "evidence_needed": ["Review the full texts of the closest records and expand the search map."]}
        elif not enum_valid(novelty_data, "assessment", {"substantial_overlap", "possible_distinction", "undetermined"}, "undetermined"):
            novelty_data["basis"] = "The local analyst returned an invalid assessment label, so this result is treated as undetermined. " + str(novelty_data.get("basis", ""))
            novelty_available = False
        store.add_event(run_id, "Novelty Analyst", "novelty",
                        "Compared the proposal with supplied prior work; missing matches are not treated as proof of novelty." if novelty_available
                        else "Novelty assessment is unavailable because the local model returned no structured result.")

        update(run_id, "impact_feasibility", 84, "Impact and Feasibility Analysts are separating evidence, assumptions, and project dependencies.", "Impact & Feasibility Analysts")
        impact_text = await optional_completion(provider, IMPACT_FEASIBILITY_SYSTEM, analyst_input, 1300)
        impact_data = parse_json(impact_text or "")
        impact_available = isinstance(impact_data, dict)
        if not impact_available:
            impact_data = {"impact_pathways": [], "feasibility": "unclear",
                           "feasibility_rationale": "The local analyst did not return a structured assessment.",
                           "dependencies": [], "risks": [],
                           "unknowns": ["Project data access, timeline, compute, and evaluation resources were not assessed."]}
        elif not enum_valid(impact_data, "feasibility", {"promising", "constrained", "unclear"}, "unclear"):
            impact_data["feasibility_rationale"] = "The local analyst returned an invalid feasibility label, so feasibility is treated as unclear. " + str(impact_data.get("feasibility_rationale", ""))
            impact_available = False
        store.add_event(run_id, "Impact & Feasibility Analysts", "impact_feasibility",
                        "Mapped plausible value and project dependencies; unknown resources remain explicit." if impact_available
                        else "Impact and feasibility assessment is unavailable because the local model returned no structured result.")

        update(run_id, "strategy", 88, "The Research Strategist is turning the evidence and constraints into testable next steps.", "Research Strategist")
        strategy_input = json.dumps({"question": question, "brief": brief, "research_map": research_map,
                                     "clarifying_questions": clarifying_questions, "synthesis": synthesis,
                                     "novelty_review": novelty_data, "impact_feasibility": impact_data,
                                     "papers": synthesis_input["papers"], "verified_claims": validated_claims,
                                     "study_details": synthesis_input["study_details"],
                                     "study_metrics_reported_in_sources": citable_study_metrics}, ensure_ascii=False)
        strategy_text = await optional_completion(provider, STRATEGY_SYSTEM, strategy_input, 2400)
        strategy_data = parse_json(strategy_text or "")
        strategy_available = isinstance(strategy_data, dict)
        if not strategy_available:
            strategy_data = {"recommended_direction": "Review the collected records and complete the missing project brief before committing to a research direction.",
                             "research_questions": [], "experimental_plan": [], "expected_contributions": [],
                             "publication_readiness": {"assessment": "not_assessable", "missing_evidence": ["Structured research plan was not generated."],
                                                        "selection_criteria": ["Check current venue scope, deadlines, fees, and submission rules on official pages."]}}
        else:
            readiness = strategy_data.get("publication_readiness")
            if not isinstance(readiness, dict):
                strategy_data["publication_readiness"] = {"assessment": "not_assessable", "missing_evidence": ["Publication-readiness output had an invalid structure."],
                                                           "selection_criteria": ["Check current venue scope, deadlines, fees, and submission rules on official pages."]}
                strategy_available = False
            elif not enum_valid(readiness, "assessment", {"early", "needs_evidence", "not_assessable"}, "not_assessable"):
                strategy_available = False
        store.add_event(run_id, "Research Strategist", "strategy",
                        "Drafted falsifiable questions and staged experiments from the available evidence." if strategy_available
                        else "A structured research plan is unavailable because the local model returned no result.")

        update(run_id, "reviewing", 93, "The Adversarial Reviewer is checking the synthesis and proposed plan against the collected evidence.", "Adversarial Reviewer")
        review_prompt = json.dumps({"brief": brief, "research_map": research_map,
                                    "draft": synthesis, "novelty_review": novelty_data,
                                    "impact_feasibility": impact_data, "strategy": strategy_data,
                                    "papers": synthesis_input["papers"], "claim_reviews": validated_claims,
                                    "study_details": synthesis_input["study_details"],
                                    "study_metrics_reported_in_sources": citable_study_metrics}, ensure_ascii=False)
        review_text = await optional_completion(provider, REVIEW_SYSTEM, review_prompt, 900)
        review_data = parse_json(review_text or "") or {}
        reviewer_issues = review_data.get("issues", []) if isinstance(review_data, dict) else []
        if not isinstance(reviewer_issues, list):
            reviewer_issues = []
        no_abstract = sum(1 for paper, _, _ in records if paper.get("source") not in {"Web page", "User PDF"} and not paper.get("abstract"))
        truncated_pdfs = sum(1 for paper, _, _ in records if paper.get("source") == "User PDF" and paper.get("text_truncated"))
        if not synthesis:
            synthesis = {
                "executive_summary": f"The search found {len(records)} unique records for: {question}. Abstract-level analysis was not generated because the local model was unavailable or returned invalid output.",
                "themes": [], "contradictions": [], "research_gaps": [],
                "next_steps": ["Review the paper list and attach accessible full texts.", "Start the local model server to enable structured extraction and synthesis."],
                "limitations": ["No model-generated synthesis is available for this run.", "Search results are not a complete review of the field."],
                "reviewer_notes": ["Do not treat search absence as evidence that no prior work exists."],
            }
        synthesis["novelty_analysis"] = novelty_data
        synthesis["impact_feasibility"] = impact_data
        synthesis["research_strategy"] = strategy_data
        synthesis["research_brief"] = brief
        synthesis["research_map"] = research_map
        synthesis["clarifying_questions"] = clarifying_questions
        synthesis["study_details"] = study_details
        synthesis["evidence_matrix"] = evidence_matrix
        synthesis["metric_comparisons"] = metric_comparisons
        synthesis["metric_comparison_note"] = (
            "Only records with the same metric, dataset, split, and evaluation-protocol excerpts are grouped for comparison. "
            "Reported values and units remain as each source stated them."
        )
        synthesis["full_text_coverage"] = {
            "papers_analyzed_with_full_text": fulltext_count,
            "maximum_per_run": settings.max_open_access_fulltext_per_run,
            "license_policy": "Europe PMC REST fullTextXML only; explicit CC0/CC-BY adaptation-permitting license required; bounded passages are analyzed in memory and the complete XML is not retained.",
            "figure_policy": "Figure captions may be quoted; a figure is not interpreted unless its image is passed to a vision model.",
        }
        synthesis["paper_appraisals"] = paper_appraisals
        synthesis["paper_appraisal_coverage"] = {
            "facet_count": len(paper_appraisals),
            "records_analyzed": len(papers_for_model),
            "papers_with_assessments": len({item["paper_id"] for item in paper_appraisals
                                             if item["status"] == "evidence_found"}),
            "evidence_backed_facets": sum(item["status"] == "evidence_found" for item in paper_appraisals),
            "note": "Evidence-backed appraisals quote exact text available to this run. Abstract-only sources may not expose full methods or author-stated limitations; a missing facet is marked not assessable, not as a paper weakness.",
        }
        synthesis["study_details_coverage"] = {
            "detail_count": len(study_details),
            "records_with_details": len({item["paper_id"] for item in study_details}),
            "records_with_text": sum(bool(paper.get("evidence_text") or paper.get("abstract"))
                                      for paper, _, _ in records[:analysis_limit]),
            "note": "These are exact quotes from text available to this run. Abstract-only records often omit full methods, ablations, and experiment settings.",
        }
        synthesis["analyst_availability"] = {"synthesizer": model_analysis_available,
                                               "novelty_analyst": novelty_available,
                                               "impact_feasibility": impact_available,
                                               "research_strategist": strategy_available}
        limitations = synthesis.get("limitations", [])
        if not isinstance(limitations, list):
            limitations = [str(limitations)]
        limitations += [f"The run included {len(project_documents)} user-provided PDF(s); extracted text was capped and scanned-image OCR is not available.",
                        f"The project has {project_document_total} attached PDFs; this run uses at most the 3 most recently added.",
                        f"{truncated_pdfs} attached PDF(s) reached the text extraction cap.",
                        f"{no_abstract} of {len(records)} saved records have no abstract in the returned metadata.",
                        "Supplied public web pages were read as bounded text excerpts; dynamic page content and private pages are not supported.",
                        "Search results depend on query wording, index coverage, and service availability.",
                        "Citation labels are restricted to saved records; citation-to-sentence support still needs human review."]
        synthesis["limitations"] = list(dict.fromkeys(str(item) for item in limitations))
        synthesis["model_available"] = model_analysis_available
        synthesis["citation_refs"] = [
            {"label": f"P{index + 1}", "paper_id": paper_ids[index], "title": paper.get("title"),
             "doi": paper.get("doi"), "url": paper.get("full_text_url") or paper.get("url"),
             "source": paper.get("fulltext_source") or paper.get("source"), "year": paper.get("year")}
            for index, (paper, _, _) in enumerate(records[:analysis_limit])
        ]
        # Remove references outside the bounded source set and call out the audit finding.
        valid_citations = {f"P{i + 1}" for i in range(min(len(records), analysis_limit))}
        invalid_citations: set[str] = set()
        def audit_text(value: Any) -> Any:
            if isinstance(value, str):
                def replace(match: Any) -> str:
                    label = match.group(1)
                    if label not in valid_citations:
                        invalid_citations.add(label)
                        return ""
                    return match.group(0)
                return re.sub(r"\[(P\d+)\]", replace, value)
            if isinstance(value, list):
                return [audit_text(item) for item in value]
            if isinstance(value, dict):
                return {key: audit_text(item) for key, item in value.items()}
            return value
        for field in ("executive_summary", "themes", "contradictions", "research_gaps", "next_steps", "limitations", "reviewer_notes",
                      "novelty_analysis", "impact_feasibility", "research_strategy"):
            if field in synthesis:
                synthesis[field] = audit_text(synthesis[field])
        if invalid_citations:
            notes = synthesis.get("reviewer_notes", [])
            if not isinstance(notes, list):
                notes = [str(notes)]
            notes.append("Citation audit removed references outside the saved source list: " + ", ".join(sorted(invalid_citations)))
            synthesis["reviewer_notes"] = notes
        uncited_statements: list[str] = []

        def require_citation(text: Any, location: str, *, allow_assumption: bool = False) -> Any:
            if not isinstance(text, str) or not text.strip():
                return text
            if allow_assumption and text.strip().lower().startswith(("assumption:", "candidate to validate:", "validation needed:")):
                return text
            if not re.search(r"\[(P\d+)\]", text):
                uncited_statements.append(location)
                return "UNCITED IN THIS RUN — " + text
            return text

        synthesis["executive_summary"] = require_citation(synthesis.get("executive_summary"), "executive summary")
        for field in ("themes", "contradictions", "research_gaps"):
            items = synthesis.get(field, [])
            if isinstance(items, list):
                synthesis[field] = [require_citation(item, f"{field} item {index + 1}") for index, item in enumerate(items)]
        novelty = synthesis.get("novelty_analysis", {})
        if isinstance(novelty, dict):
            novelty["basis"] = require_citation(novelty.get("basis"), "novelty assessment")
            risks = novelty.get("prior_art_risks", [])
            if isinstance(risks, list):
                novelty["prior_art_risks"] = [require_citation(item, f"prior art risk {index + 1}") for index, item in enumerate(risks)]
            related = novelty.get("closest_related_work", [])
            if isinstance(related, list):
                for index, item in enumerate(related):
                    if isinstance(item, dict):
                        item["overlap"] = require_citation(item.get("overlap"), f"closest work {index + 1} overlap")
                        item["difference_or_unknown"] = require_citation(item.get("difference_or_unknown"), f"closest work {index + 1} distinction")
        impact = synthesis.get("impact_feasibility", {})
        if isinstance(impact, dict):
            impact["feasibility_rationale"] = require_citation(impact.get("feasibility_rationale"), "feasibility rationale")
            for pathway in impact.get("impact_pathways", []) if isinstance(impact.get("impact_pathways"), list) else []:
                if isinstance(pathway, dict):
                    pathway["evidence_or_assumption"] = require_citation(pathway.get("evidence_or_assumption"), "impact pathway", allow_assumption=True)
            for risk in impact.get("risks", []) if isinstance(impact.get("risks"), list) else []:
                if isinstance(risk, dict):
                    risk["basis"] = require_citation(risk.get("basis"), "feasibility risk")
        strategy = synthesis.get("research_strategy", {})
        if isinstance(strategy, dict):
            strategy["recommended_direction"] = require_citation(strategy.get("recommended_direction"), "recommended direction")
            for index, item in enumerate(strategy.get("research_questions", []) if isinstance(strategy.get("research_questions"), list) else []):
                if isinstance(item, dict):
                    item["evidence_basis"] = require_citation(item.get("evidence_basis"), f"research question {index + 1} evidence basis")
            for phase_index, phase in enumerate(strategy.get("experimental_plan", []) if isinstance(strategy.get("experimental_plan"), list) else []):
                if isinstance(phase, dict):
                    for metric_index, metric in enumerate(phase.get("metrics", []) if isinstance(phase.get("metrics"), list) else []):
                        if isinstance(metric, dict):
                            candidate = "candidate" in str(metric.get("status", "")).casefold()
                            metric["evidence_basis"] = require_citation(
                                metric.get("evidence_basis"), f"experimental phase {phase_index + 1} metric {metric_index + 1}",
                                allow_assumption=candidate)
        if uncited_statements:
            notes = synthesis.get("reviewer_notes", [])
            if not isinstance(notes, list):
                notes = [str(notes)]
            notes.append("Citation Auditor flagged uncited statements for source review: " + "; ".join(uncited_statements[:10]))
            synthesis["reviewer_notes"] = notes
        synthesis["reviewer_issues"] = [issue for issue in reviewer_issues if isinstance(issue, dict)][:12]
        synthesis["reviewer_available"] = bool(review_text and isinstance(review_data, dict))
        synthesis["study_metrics"] = study_metrics
        synthesis["metrics_coverage"] = {
            "metric_count": len(study_metrics),
            "analysis_records": analysis_limit,
            "records_with_full_text": sum(bool(p.get("evidence_text") or p.get("abstract")) for p, _, _ in records[:analysis_limit]),
            "note": "This list includes only metrics explicitly named in the text available to this run. Abstract-only coverage can miss measures reported in full-text methods or tables.",
        }
        indexed_retained = sum(1 for paper, _, _ in records if paper.get("source") not in {"User PDF", "Web page"})
        eligible_index_records = max(0, len(unique_index) - screened_out_search_hits)
        screening_decisions = store.list_screening_decisions(run_id)
        manual_counts = {decision: sum(1 for item in screening_decisions if item.get("decision") == decision)
                         for decision in ("include", "exclude", "maybe")}
        synthesis["prisma_flow"] = {
            "identified_records": search_hits_count,
            "duplicates_removed": max(0, search_hits_count - len(unique_index)),
            "unique_records_screened": len(unique_index),
            "excluded_by_topic_screen": screened_out_search_hits,
            "eligible_after_topic_screen": eligible_index_records,
            "not_retained_by_run_cap": max(0, eligible_index_records - indexed_retained),
            "retained_for_report": indexed_retained,
            "note": "PRISMA-style operational counts for this run. Topic screening is automated and lexical; records beyond the configured retention cap are not saved. Human decisions below apply to retained records.",
            "human_decisions": manual_counts,
        }
        synthesis["search_log"] = {
            "searched_at": store.now(), "providers": ["Crossref", "Europe PMC", "OpenAlex"],
            "branches": branch_search_log, "raw_hits_across_queries": search_hits_count,
            "unique_index_records": len(unique_index), "duplicates_removed": max(0, search_hits_count - len(unique_index)),
            "topic_terms": sorted(topic_terms), "ranking_method": ranking_method,
            "retention_limit": settings.max_papers_per_run, "analysis_limit": analysis_limit,
            "model": settings.model_name or "not configured",
            "selection_policy": "Topic screen by title/abstract, then branch-balanced selection; no search-hit abstracts are saved for unselected records.",
        }
        synthesis["search"] = {"branches": branches, "unique_papers": len(records), "source_errors": source_errors,
                               "candidate_hits": search_hits_count, "unique_candidates": len(unique_candidates),
                               "screened_out_hits": screened_out_search_hits,
                               "duplicates_removed": max(0, search_hits_count - len(unique_index)),
                               "topical_index_hits": eligible_index_records,
                               "screening_method": "Local topic-token overlap against titles, abstracts, attached PDF text, and the question/brief; a narrow allowance keeps adjacent Tor traffic-analysis and defense work. Clear mismatches are excluded before source links are retained.",
                               "ranking_method": ranking_method,
                               "unique_index_candidates": len(unique_index),
                               "retained_source_links": len(records), "analysis_records": analysis_limit,
                               "fulltext_records": fulltext_count,
                               "records_not_retained_by_cap": max(0, eligible_index_records - indexed_retained),
                               "sources": ["Crossref", "Europe PMC", "OpenAlex", *( ["User-selected web pages"] if page_records else [] )],
                               "web_pages_read": len(page_records)}
        synthesis["pdfs"] = {"available_in_project": project_document_total,
                             "considered_in_run": len(project_document_candidates),
                             "included_in_run": len(project_documents),
                             "excluded_for_topic": len(excluded_project_documents),
                             "truncated_in_run": truncated_pdfs}
        synthesis["generated_at"] = store.now()
        run_status = "partial" if source_errors and not records else "completed"
        run_stage = "partial" if run_status == "partial" else "completed"
        store.update_run(run_id, status=run_status, stage=run_stage, progress=100, result=synthesis)
        if run_status == "partial":
            store.add_event(run_id, "Research Lead", "partial", "Search providers were unavailable; this run contains a partial result and should be retried.")
        store.add_event(run_id, "Citation Auditor", "completed", "Checked in-report citation labels against saved source records; source links and limitations are attached.")
    except Exception as exc:
        store.update_run(run_id, status="failed", stage="failed", error=f"{type(exc).__name__}: {exc}")
        store.add_event(run_id, "Research Lead", "failed", f"Run stopped: {type(exc).__name__}.")
        try:
            from researchos.system_care import REPAIRABLE_FILES, record_incident
            project_root = Path(__file__).resolve().parents[2]
            frames = []
            for frame in traceback.extract_tb(exc.__traceback__):
                try:
                    relative = Path(frame.filename).resolve().relative_to(project_root).as_posix()
                except ValueError:
                    continue
                if relative in REPAIRABLE_FILES:
                    frames.append(f"{relative}:{frame.lineno}:{frame.name}")
            record_incident("research workflow", type(exc).__name__,
                            f"Research run {run_id} stopped during stage failed.", detail="\n".join(frames[:8]))
        except Exception:
            pass
    finally:
        await provider.close()
