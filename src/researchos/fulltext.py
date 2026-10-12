"""Small, license-aware Europe PMC full-text retrieval for individual papers."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

import httpx


EUROPE_PMC_FULLTEXT = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
MAX_XML_BYTES = 5_000_000
MAX_PASSAGES = 28
MAX_PASSAGE_CHARS = 1100
MAX_TOTAL_CHARS = 18_000
_XLINK = "{http://www.w3.org/1999/xlink}href"


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].casefold()


def _text(element: ET.Element) -> str:
    return re.sub(r"\s+", " ", " ".join(element.itertext())).strip()


def _license(root: ET.Element) -> tuple[str, str]:
    for item in root.iter():
        if _tag(item) != "license":
            continue
        href = item.get(_XLINK) or item.get("href") or ""
        statement = _text(item)
        candidate = f"{href} {statement}".casefold()
        path_match = re.search(r"creativecommons\.org/licenses/([^/]+)", href.casefold())
        slug = path_match.group(1).replace("_", "-") if path_match else ""
        if slug in {"zero", "cc0"} or "cc0" in candidate:
            return href or statement, "CC0"
        if slug in {"by", "by-sa", "by-nc", "by-nc-sa"}:
            return href or statement, f"CC-{slug.upper()}"
        match = re.search(r"\b(cc0|cc[- ]by(?:[- ]nc)?(?:[- ]sa)?)(?:\b|/)", candidate)
        if not match or "nd" in candidate:
            return href or statement, ""
        license_id = match.group(1).replace(" ", "-")
        # Only retain text where the license permits adaptations; no derivatives
        # and unidentified/custom terms are left for the user-provided PDF path.
        if license_id in {"cc0", "cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nc-sa"}:
            return href or statement, license_id.upper()
        return href or statement, ""
    return "", ""


def parse_fulltext_xml(xml_bytes: bytes, *, max_chars: int = MAX_TOTAL_CHARS) -> dict[str, Any] | None:
    """Return bounded section/table passages only when an explicit CC license permits reuse."""
    if not xml_bytes or len(xml_bytes) > MAX_XML_BYTES:
        return None
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None
    license_statement, license_id = _license(root)
    if not license_id:
        return None

    passages: list[dict[str, str]] = []
    body = next((element for element in root.iter() if _tag(element) == "body"), None)
    if body is None:
        return None

    def visit(element: ET.Element, section_title: str = "") -> None:
        kind = _tag(element)
        current_section = section_title
        if kind == "sec":
            title = next((_text(child) for child in element if _tag(child) == "title"), "")
            if title:
                current_section = title[:120]
        if kind in {"p", "table-wrap", "fig", "list-item"}:
            text = _text(element)
            minimum_chars = 30 if kind in {"table-wrap", "fig"} else 60
            if len(text) >= minimum_chars:
                if kind == "table-wrap":
                    caption = next((_text(child) for child in element if _tag(child) == "caption"), "")
                    locator = f"Table: {caption[:150]}" if caption else "Table"
                elif kind == "fig":
                    caption = next((_text(child) for child in element if _tag(child) == "caption"), "")
                    locator = f"Figure caption: {caption[:150]}" if caption else "Figure caption"
                else:
                    locator = f"Section: {current_section}" if current_section else "Full-text passage"
                passages.append({"locator": locator, "text": text[:MAX_PASSAGE_CHARS]})
                if kind in {"table-wrap", "fig"}:
                    return
        for child in element:
            visit(child, current_section)

    visit(body)

    priority_terms = ("method", "material", "experiment", "evaluation", "result", "implementation", "data")
    def priority(item: dict[str, str]) -> tuple[int, int]:
        locator = item["locator"].casefold()
        if locator.startswith("table"):
            return (0, 0)
        if locator.startswith("figure"):
            return (1, 0)
        if any(term in locator for term in priority_terms):
            return (2, 0)
        return (3, 0)

    passages = sorted(passages, key=priority)[:MAX_PASSAGES]
    retained: list[dict[str, str]] = []
    total = 0
    for item in passages:
        remaining = max_chars - total
        if remaining <= 0:
            break
        item = {**item, "text": item["text"][:remaining]}
        retained.append(item)
        total += len(item["text"])
    if not retained:
        return None
    return {"license": license_id, "license_statement": license_statement,
            "passages": retained, "character_count": total, "tables": sum(p["locator"].startswith("Table") for p in retained),
            "figures": sum(p["locator"].startswith("Figure") for p in retained)}


async def fetch_open_access_fulltext(paper: dict[str, Any], client: httpx.AsyncClient) -> dict[str, Any] | None:
    """Fetch one Europe PMC OA record through its documented REST fullTextXML endpoint."""
    pmcid = str(paper.get("pmcid") or "").strip()
    if not pmcid or not paper.get("is_open_access"):
        return None
    url = EUROPE_PMC_FULLTEXT.format(pmcid=quote(pmcid, safe=""))
    chunks: list[bytes] = []
    size = 0
    async with client.stream("GET", url, headers={"User-Agent": "ResearchOS/0.1 (local scholarly evidence tool)"}) as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > MAX_XML_BYTES:
                return None
            chunks.append(chunk)
    result = parse_fulltext_xml(b"".join(chunks))
    if result:
        result["pmcid"] = pmcid
        result["url"] = f"https://europepmc.org/articles/{pmcid}"
    return result


def locate_fulltext_quote(paper: dict[str, Any], quote_text: str) -> str:
    folded_quote = quote_text.casefold()
    for passage in paper.get("full_text_passages", []):
        if folded_quote and folded_quote in str(passage.get("text", "")).casefold():
            return str(passage.get("locator") or "Europe PMC full text")
    return "Europe PMC full-text passage"
