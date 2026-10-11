import asyncio
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

MAX_PAGE_BYTES = 2_000_000
MAX_PAGE_TEXT = 18_000
REDIRECT_CODES = {301, 302, 303, 307, 308}
IGNORED_TAGS = {"script", "style", "noscript", "svg", "canvas", "iframe", "template"}
TRUSTED_WEB_DOMAINS = (
    "crossref.org", "europepmc.org", "openalex.org", "pubmed.ncbi.nlm.nih.gov", "pmc.ncbi.nlm.nih.gov",
    "doi.org", "arxiv.org", "biorxiv.org", "medrxiv.org", "clinicaltrials.gov", "nature.com", "science.org",
    "sciencedirect.com", "cell.com", "nejm.org", "jamanetwork.com", "bmj.com", "plos.org", "frontiersin.org",
    "academic.oup.com", "onlinelibrary.wiley.com", "journals.sagepub.com", "springer.com", "link.springer.com",
)


def is_trusted_web_url(value: str) -> bool:
    try:
        parsed = urlsplit(value.strip())
        host = (parsed.hostname or "").casefold().rstrip(".")
    except ValueError:
        return False
    return bool(parsed.scheme == "https" and not parsed.username and not parsed.password
                and any(host == domain or host.endswith("." + domain) for domain in TRUSTED_WEB_DOMAINS))


class PageTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.ignored_depth = 0
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in IGNORED_TAGS:
            self.ignored_depth += 1
        if tag == "title":
            self.in_title = True
        if tag in {"p", "br", "div", "article", "section", "li", "h1", "h2", "h3", "tr"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in IGNORED_TAGS and self.ignored_depth:
            self.ignored_depth -= 1
        if tag == "title":
            self.in_title = False
        if tag in {"p", "div", "article", "section", "li", "h1", "h2", "h3", "tr"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        if not self.ignored_depth:
            self.text_parts.append(data)

    def content(self) -> tuple[str, str]:
        title = re.sub(r"\s+", " ", " ".join(self.title_parts)).strip()
        body = re.sub(r"[\t\r ]+", " ", "".join(self.text_parts))
        body = re.sub(r"\n\s*\n+", "\n", body).strip()
        return title[:240], body[:MAX_PAGE_TEXT]


def validate_public_url(url: str) -> str:
    if len(url) > 2000:
        raise ValueError("The web address is too long.")
    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Enter a public http or https page address.")
    if parsed.username or parsed.password:
        raise ValueError("Addresses containing login credentials are not accepted.")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or "." not in host:
        raise ValueError("Only public internet hostnames are accepted.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("The page address has an invalid port.") from exc
    if port and port not in {80, 443}:
        raise ValueError("Only standard web ports 80 and 443 are accepted.")
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            addresses = {
                ipaddress.ip_address(info[4][0])
                for info in socket.getaddrinfo(host, port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
            }
        except OSError as exc:
            raise ValueError("The public host could not be resolved.") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("Private, local, and reserved network addresses are blocked.")
    display_host = f"[{host}]" if ":" in host else host
    netloc = display_host if not port else f"{display_host}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path or "/", parsed.query, ""))


async def read_public_page(url: str) -> dict[str, str]:
    current = await asyncio.to_thread(validate_public_url, url)
    if not is_trusted_web_url(current):
        raise ValueError("Only HTTPS pages from the trusted scholarly-domain list can be read.")
    async with httpx.AsyncClient(timeout=18, follow_redirects=False, headers={
        "User-Agent": "ResearchOS/0.1 (local research page reader)",
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.2",
    }) as client:
        for _ in range(5):
            current = await asyncio.to_thread(validate_public_url, current)
            async with client.stream("GET", current) as response:
                if response.status_code in REDIRECT_CODES:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("The page returned an invalid redirect.")
                    current = urljoin(current, location)
                    if not is_trusted_web_url(current):
                        raise ValueError("This trusted source redirected outside the scholarly-domain allowlist.")
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if not any(kind in content_type for kind in ("text/html", "application/xhtml+xml", "text/plain")):
                    raise ValueError("This reader accepts public HTML and text pages. For papers, use an open-access link or attach a PDF.")
                declared_size = response.headers.get("content-length")
                if declared_size and declared_size.isdigit() and int(declared_size) > MAX_PAGE_BYTES:
                    raise ValueError("The page is larger than the 2 MB reader limit.")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_PAGE_BYTES:
                        raise ValueError("The page is larger than the 2 MB reader limit.")
                    chunks.append(chunk)
                encoding = response.encoding or "utf-8"
                raw = b"".join(chunks).decode(encoding, errors="replace")
                if "text/plain" in content_type:
                    title = urlsplit(current).hostname or "Public web page"
                    text = re.sub(r"\s+", " ", raw).strip()[:MAX_PAGE_TEXT]
                else:
                    parser = PageTextParser()
                    parser.feed(raw)
                    title, text = parser.content()
                if not text:
                    raise ValueError("No readable page text was found.")
                return {"url": current, "title": title or urlsplit(current).hostname or "Public web page", "text": text}
    raise ValueError("The page redirected too many times.")
