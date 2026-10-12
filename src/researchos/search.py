import asyncio
import re
import time
from typing import Any

import httpx

from researchos.config import settings

HEADERS = {"User-Agent": "ResearchOS/0.1 (local literature research assistant)"}
_CROSSREF_LOCK = asyncio.Lock()
_crossref_next_request_at = 0.0


def _year(value: Any) -> int | None:
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return None


def _clean_abstract(value: Any) -> str:
    if isinstance(value, dict):
        words = [word for word, _ in sorted(value.items(), key=lambda pair: pair[1])]
        return " ".join(words)
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _authors(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    authors: list[str] = []
    for item in items:
        if isinstance(item, dict):
            name = item.get("name") or " ".join(filter(None, [item.get("given"), item.get("family")]))
            if name:
                authors.append(name)
    return authors


def _result_limit(limit: int | None) -> int:
    return max(1, min(int(limit or settings.max_search_results_per_source), 100))


async def search_crossref(query: str, client: httpx.AsyncClient, limit: int | None = None) -> list[dict[str, Any]]:
    global _crossref_next_request_at
    async with _CROSSREF_LOCK:
        delay = _crossref_next_request_at - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        response = await client.get(
            "https://api.crossref.org/works",
            params={"query.bibliographic": query, "rows": _result_limit(limit),
                    "select": "DOI,title,author,published,issued,abstract,URL,type,container-title,publisher,volume,issue,page"},
            headers=HEADERS,
        )
        _crossref_next_request_at = time.monotonic() + 1.1
    response.raise_for_status()
    items = response.json().get("message", {}).get("items", [])
    output = []
    for item in items:
        title = (item.get("title") or [""])[0].strip()
        if not title:
            continue
        date_parts = item.get("published", {}).get("date-parts") or item.get("issued", {}).get("date-parts") or [[]]
        output.append({
            "doi": item.get("DOI", "").lower() or None,
            "title": title,
            "authors": _authors(item.get("author")),
            "year": _year((date_parts[0] or [None])[0]),
            "abstract": _clean_abstract(item.get("abstract")),
            "source": "Crossref",
            "source_id": item.get("DOI", "") or item.get("URL", ""),
            "url": item.get("URL", ""),
            "open_access_url": "",
            "journal": (item.get("container-title") or [""])[0],
            "publisher": item.get("publisher", ""),
            "volume": item.get("volume", ""),
            "issue": item.get("issue", ""),
            "pages": item.get("page", ""),
        })
    return output


async def search_openalex(query: str, client: httpx.AsyncClient, limit: int | None = None) -> list[dict[str, Any]]:
    """Search OpenAlex's broad scholarly index using its unauthenticated free tier."""
    response = await client.get(
        "https://api.openalex.org/works",
        params={"search": query, "per-page": _result_limit(limit),
                "select": "id,doi,title,authorships,publication_year,abstract_inverted_index,primary_location,best_oa_location"},
        headers=HEADERS,
    )
    response.raise_for_status()
    output = []
    for item in response.json().get("results", []):
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        doi = str(item.get("doi") or "").removeprefix("https://doi.org/").lower() or None
        authors = [authorship.get("author", {}).get("display_name", "")
                   for authorship in item.get("authorships", [])]
        authors = [author for author in authors if author]
        primary_location = item.get("primary_location") or {}
        best_oa_location = item.get("best_oa_location") or {}
        url = (primary_location.get("landing_page_url") or (f"https://doi.org/{doi}" if doi else "")
               or item.get("id", ""))
        output.append({
            "doi": doi,
            "title": title,
            "authors": authors,
            "year": _year(item.get("publication_year")),
            "abstract": _clean_abstract(item.get("abstract_inverted_index")),
            "source": "OpenAlex",
            "source_id": item.get("id", "") or doi or title,
            "url": url,
            "open_access_url": best_oa_location.get("pdf_url") or "",
            "journal": ((primary_location.get("source") or {}).get("display_name") or ""),
            "publisher": ((primary_location.get("source") or {}).get("host_organization_name") or ""),
            "volume": "",
            "issue": "",
            "pages": "",
        })
    return output


async def search_europe_pmc(query: str, client: httpx.AsyncClient, limit: int | None = None) -> list[dict[str, Any]]:
    response = await client.get(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={"query": query, "format": "json", "resultType": "core", "pageSize": _result_limit(limit)},
        headers=HEADERS,
    )
    response.raise_for_status()
    items = response.json().get("resultList", {}).get("result", [])
    output = []
    for item in items:
        title = re.sub(r"<[^>]+>", "", item.get("title", "")).strip()
        if not title:
            continue
        doi = (item.get("doi") or "").lower() or None
        pmcid = item.get("pmcid") or ""
        source_id = item.get("id") or doi or pmcid
        authors = [author.get("fullName", "") for author in item.get("authorList", {}).get("author", []) if author.get("fullName")]
        output.append({
            "doi": doi,
            "title": title,
            "authors": authors,
            "year": _year(item.get("firstPublicationDate") or item.get("pubYear")),
            "abstract": _clean_abstract(item.get("abstractText")),
            "source": "Europe PMC",
            "source_id": str(source_id),
            "url": f"https://europepmc.org/article/MED/{item.get('id')}" if item.get("source") == "MED" else
                   (f"https://europepmc.org/article/PMC/{pmcid.removeprefix('PMC')}" if pmcid else (item.get("doi") and f"https://doi.org/{item['doi']}" or "")),
            "open_access_url": f"https://europepmc.org/articles/{pmcid}" if pmcid and item.get("isOpenAccess") == "Y" else "",
            "pmcid": pmcid or "",
            "is_open_access": item.get("isOpenAccess") == "Y",
            "journal": item.get("journalTitle", ""),
            "publisher": "",
            "volume": item.get("journalVolume", ""),
            "issue": item.get("issue", ""),
            "pages": item.get("pageInfo", ""),
        })
    return output


async def search_branch(query: str, per_source_limit: int | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
        results = await asyncio.gather(search_crossref(query, client, per_source_limit),
                                       search_europe_pmc(query, client, per_source_limit),
                                       search_openalex(query, client, per_source_limit), return_exceptions=True)
    papers: list[dict[str, Any]] = []
    names = ["Crossref", "Europe PMC", "OpenAlex"]
    for name, result in zip(names, results):
        if isinstance(result, Exception):
            if isinstance(result, httpx.HTTPStatusError):
                errors.append(f"{name}: HTTP {result.response.status_code} from {result.request.url.host}")
            elif isinstance(result, httpx.RequestError):
                errors.append(f"{name}: connection error ({type(result).__name__})")
            else:
                errors.append(f"{name}: {type(result).__name__}")
        else:
            papers.extend(result)
    return papers, errors


def merge_search_records(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge duplicate index hits while retaining which trusted indexes found them."""
    merged: dict[str, dict[str, Any]] = {}
    for paper in papers:
        doi = str(paper.get("doi") or "").casefold().removeprefix("https://doi.org/")
        title = " ".join(str(paper.get("title") or "").casefold().split())
        key = f"doi:{doi}" if doi else f"title:{title}"
        if key not in merged:
            source = paper.get("source", "")
            source_id = paper.get("source_id") or doi or title
            merged[key] = {**paper, "source_id": source_id, "sources": [source], "source_ids": {source: source_id}}
            continue
        item = merged[key]
        source = paper.get("source", "")
        if source and source not in item["sources"]:
            item["sources"].append(source)
            item["source_ids"][source] = paper.get("source_id") or doi or title
        for field in ("doi", "abstract", "url", "open_access_url", "pmcid", "journal", "publisher", "volume", "issue", "pages", "year"):
            current, candidate = item.get(field), paper.get(field)
            if candidate and (not current or (field == "abstract" and len(str(candidate)) > len(str(current)))):
                item[field] = candidate
        item["is_open_access"] = bool(item.get("is_open_access") or paper.get("is_open_access"))
        if not item.get("authors") and paper.get("authors"):
            item["authors"] = paper["authors"]
    results = list(merged.values())
    results.sort(key=lambda item: (-(int(item.get("year") or 0)), str(item.get("title") or "").casefold()))
    return results
