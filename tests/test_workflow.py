"""Offline coverage for bounded search retention and source-quoted metrics."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from researchos import store
from researchos.agents import EXTRACT_SYSTEM, IMPACT_FEASIBILITY_SYSTEM, LEAD_SYSTEM, NOVELTY_SYSTEM, REVIEW_SYSTEM, STRATEGY_SYSTEM, SYNTH_SYSTEM
from researchos.config import settings
from researchos.workflow import research_topic_terms, run_research, topic_relevance_score


class FakeResearchProvider:
    async def complete(self, system, prompt, *, max_tokens, **kwargs):
        if system == LEAD_SYSTEM:
            return json.dumps({"branches": [{"name": "Core", "query": "test topic", "purpose": "Find relevant studies."}]})
        if system == EXTRACT_SYSTEM:
            import re
            ids = re.findall(r"^\[([0-9a-f-]{36})\]", prompt, re.MULTILINE)
            quote = "We evaluated Dice segmentation score and sensitivity."
            return json.dumps({"claims": [], "study_metrics": [
                {"paper_id": paper_id, "metric": "Dice score", "what_it_measures": "Segmentation overlap.",
                 "reported_result": "Not stated.", "evidence_quote": quote}
                for paper_id in ids
            ], "study_details": [
                {"paper_id": paper_id, "aspect": "evaluation_protocol", "evidence_quote": quote}
                for paper_id in ids
            ], "paper_appraisals": [
                {"paper_id": paper_id, "aspect": "what_studied",
                 "assessment": "The paper evaluates segmentation measures.", "evidence_quote": quote}
                for paper_id in ids
            ] + ([{"paper_id": ids[0], "aspect": "strengths", "assessment": "The paper is robust.",
                   "evidence_quote": "This quote is not present in the source."}] if ids else [])})
        if system == SYNTH_SYSTEM:
            return json.dumps({"executive_summary": "The available studies describe the topic [P1].",
                               "themes": ["The evidence focuses on the main task [P1]."],
                               "contradictions": [], "research_gaps": [], "next_steps": ["Read the closest full texts."],
                               "limitations": [], "reviewer_notes": []})
        if system == NOVELTY_SYSTEM:
            return json.dumps({"closest_related_work": [], "prior_art_risks": [], "assessment": "undetermined",
                               "basis": "The retrieved abstract is limited [P1].", "evidence_needed": []})
        if system == IMPACT_FEASIBILITY_SYSTEM:
            return json.dumps({"impact_pathways": [], "feasibility": "unclear",
                               "feasibility_rationale": "Project resources are unknown [P1].", "dependencies": [],
                               "risks": [], "unknowns": ["Dataset access is unknown."]})
        if system == STRATEGY_SYSTEM:
            return json.dumps({"recommended_direction": "Compare approaches on the target task [P1].",
                               "research_questions": [], "experimental_plan": [{"phase": "Pilot",
                               "action": "Run a reproducible baseline.", "metrics": [{"name": "Dice score",
                               "definition": "Overlap score.", "role": "primary", "status": "candidate to validate",
                               "evidence_basis": "Candidate to validate: confirm suitability with domain experts."}],
                               "data_requirements": ["A labeled dataset."], "success_criterion": "Beats baseline.",
                               "next_decision": "Proceed if stable."}], "expected_contributions": [],
                               "publication_readiness": {"assessment": "needs_evidence", "missing_evidence": [],
                                                         "selection_criteria": []}})
        if system == REVIEW_SYSTEM:
            return json.dumps({"issues": []})
        raise AssertionError(f"Unexpected model stage: {system[:50]}")

    async def close(self):
        return None


class WorkflowRetentionTests(unittest.IsolatedAsyncioTestCase):
    def test_topic_screen_rejects_clear_false_positives_and_keeps_tor_fingerprint_work(self):
        terms = research_topic_terms("website finger printing on tor browser")
        self.assertEqual(terms, {"website", "fingerprint", "tor", "browser"})
        relevant = {"title": "Website Fingerprinting Techniques Over Tor Network: A Survey", "abstract": ""}
        adjacent = {"title": "Research on Traffic Behavioral Obfuscation of Tor", "abstract": ""}
        unrelated = {"title": "Special Issue: EACR 2026 Congress: Innovative Cancer Science", "abstract": ""}
        unrelated_tor = {"title": "Investigating child sexual abuse material availability on the anonymous Tor network", "abstract": ""}
        unrelated_pdf = {"title": "paper_review_2", "evidence_text": "3D breast cancer MRI segmentation methods."}
        self.assertGreater(topic_relevance_score(relevant, terms), 0)
        self.assertGreater(topic_relevance_score(adjacent, terms), 0)
        self.assertEqual(topic_relevance_score(unrelated, terms), 0)
        self.assertEqual(topic_relevance_score(unrelated_tor, terms), 0)
        self.assertEqual(topic_relevance_score(unrelated_pdf, terms), 0)

    async def test_wide_candidate_pool_keeps_bounded_links_and_verifies_metric_quotes(self):
        with tempfile.TemporaryDirectory(prefix="researchos-workflow-test-") as temporary:
            data_dir = Path(temporary)
            with patch.object(settings, "data_dir", data_dir), \
                 patch.object(settings, "max_papers_per_run", 48), \
                 patch.object(settings, "max_analysis_papers", 12):
                store.init_db()
                project = store.project_list()[0]
                run = store.create_run(project["id"], "Compare Dice segmentation methods for this research topic", {})
                papers = [{"doi": f"10.1234/example.{index}",
                           "title": "Repeated Study" if index < 2 else f"Study {index}", "authors": [],
                           "year": 2024, "abstract": "We evaluated Dice segmentation score and sensitivity.",
                           "source": "OpenAlex", "source_id": f"W{index}", "url": f"https://doi.org/10.1234/example.{index}",
                           "open_access_url": ""} for index in range(60)]
                with patch("researchos.workflow.LocalOpenAIProvider", return_value=FakeResearchProvider()), \
                     patch("researchos.workflow.search_branch", new_callable=AsyncMock, return_value=(papers, [])):
                    await run_research(run["id"], project["id"], run["question"], [], {})

                completed = store.get_run(run["id"])
                self.assertEqual(completed["status"], "completed", completed.get("error"))
                self.assertEqual(len(completed["papers"]), 48)
                retained_abstracts = sum(bool(paper["abstract"]) for paper in completed["papers"])
                self.assertEqual(retained_abstracts, 12)
                self.assertEqual(completed["result"]["search"]["candidate_hits"], 60)
                self.assertEqual(completed["result"]["search"]["screened_out_hits"], 0)
                self.assertEqual(completed["result"]["search"]["topical_index_hits"], 60)
                self.assertEqual(completed["result"]["search"]["unique_candidates"], 60)
                self.assertEqual(completed["result"]["metrics_coverage"]["metric_count"], 12)
                self.assertTrue(all(item["evidence_quote"] == "We evaluated Dice segmentation score and sensitivity."
                                    for item in completed["result"]["study_metrics"]))
                self.assertEqual(completed["result"]["study_details_coverage"]["detail_count"], 12)
                self.assertTrue(all(item["aspect"] == "evaluation_protocol" and
                                    item["evidence_quote"] == "We evaluated Dice segmentation score and sensitivity."
                                    for item in completed["result"]["study_details"]))
                appraisal_coverage = completed["result"]["paper_appraisal_coverage"]
                self.assertEqual(appraisal_coverage["records_analyzed"], 12)
                self.assertEqual(appraisal_coverage["papers_with_assessments"], 12)
                self.assertEqual(appraisal_coverage["evidence_backed_facets"], 12)
                self.assertEqual(len(completed["result"]["paper_appraisals"]), 48)
                self.assertTrue(all(item["status"] == "evidence_found" for item in completed["result"]["paper_appraisals"]
                                    if item["aspect"] == "what_studied"))
                self.assertTrue(all(item["evidence_quote"] == "We evaluated Dice segmentation score and sensitivity."
                                    for item in completed["result"]["paper_appraisals"]
                                    if item["aspect"] == "what_studied"))
                self.assertTrue(all(item["status"] == "not_assessable" for item in completed["result"]["paper_appraisals"]
                                    if item["aspect"] in {"relevance", "strengths", "limitations"}))
                self.assertEqual(completed["result"]["citation_refs"][-1]["label"], "P12")
                saved_ids_by_doi = {paper["doi"]: paper["id"] for paper in completed["papers"]}
                references = completed["result"]["citation_refs"]
                self.assertEqual(references[0]["paper_id"], saved_ids_by_doi["10.1234/example.0"])
                self.assertEqual(references[1]["paper_id"], saved_ids_by_doi["10.1234/example.1"])
                self.assertNotEqual(references[0]["paper_id"], references[1]["paper_id"])


if __name__ == "__main__":
    unittest.main()
