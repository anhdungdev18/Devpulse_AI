"""
Production-ish ArXiv adapter for DevPulseAI.

Features:
- Public ArXiv API, no authentication required
- Retry with exponential backoff
- Async implementation + sync wrapper
- Safe XML parsing
- Whitespace normalization
- Standardized schema normalization
- Authors, categories, PDF URL, published/updated metadata
- trust_env=False to bypass broken local proxy settings

Public API:
- fetch_arxiv_papers(...) -> sync wrapper used by the current pipeline
- fetch_arxiv_papers_async(...) -> async implementation
"""

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("devpulse.arxiv_adapter")

ARXIV_API_URL = "https://export.arxiv.org/api/query"

DEFAULT_CATEGORIES = [
    "cs.AI",
    "cs.LG",
    "cs.CL",
]

DEFAULT_TIMEOUT = 20.0
MAX_RETRIES = 3
MAX_LIMIT = 50
MAX_RATE_LIMIT_SLEEP = 30

ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


def clean_text(text: Optional[str]) -> str:
    """Normalize whitespace from ArXiv XML text fields."""
    if not text:
        return ""
    return " ".join(text.split())


def truncate_text(text: str, max_chars: int = 500) -> str:
    """Truncate long text safely."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def extract_arxiv_id(arxiv_url: str) -> str:
    """
    Extract clean ArXiv ID from URL.

    Example:
    http://arxiv.org/abs/2501.12345v1 -> 2501.12345v1
    """
    if not arxiv_url:
        return ""

    match = re.search(r"arxiv\.org/abs/([^?#]+)", arxiv_url)
    if match:
        return match.group(1)

    return arxiv_url.rstrip("/").split("/")[-1]


def build_search_query(categories: Optional[List[str]] = None) -> str:
    """Build ArXiv category query."""
    selected_categories = categories or DEFAULT_CATEGORIES
    category_parts = [f"cat:{category}" for category in selected_categories]
    return "(" + " OR ".join(category_parts) + ")"


def get_headers() -> Dict[str, str]:
    """Build request headers for polite ArXiv access."""
    return {
        "User-Agent": "DevPulseAI/1.0 (research aggregation demo)",
        "Accept": "application/atom+xml, application/xml;q=0.9, */*;q=0.8",
    }


def get_entry_text(
    entry: ET.Element,
    path: str,
    default: str = "",
) -> str:
    """Safely extract and clean text from an XML entry."""
    elem = entry.find(path, ATOM_NS)
    if elem is None:
        return default
    return clean_text(elem.text) or default


def get_authors(entry: ET.Element) -> List[str]:
    """Extract author names from an ArXiv entry."""
    authors: List[str] = []
    for author in entry.findall("atom:author", ATOM_NS):
        name = author.find("atom:name", ATOM_NS)
        if name is not None and name.text:
            authors.append(clean_text(name.text))
    return authors


def get_categories(entry: ET.Element) -> List[str]:
    """Extract category terms from an ArXiv entry."""
    categories: List[str] = []
    for category in entry.findall("atom:category", ATOM_NS):
        term = category.attrib.get("term")
        if term:
            categories.append(term)
    return categories


def get_primary_category(entry: ET.Element) -> Optional[str]:
    """Extract primary ArXiv category."""
    primary = entry.find("arxiv:primary_category", ATOM_NS)
    if primary is None:
        return None
    return primary.attrib.get("term")


def get_pdf_link(entry: ET.Element, fallback_url: str) -> str:
    """Extract PDF link from ArXiv entry."""
    for link in entry.findall("atom:link", ATOM_NS):
        if link.attrib.get("title") == "pdf":
            return link.attrib.get("href", fallback_url)
    return fallback_url


def normalize_entry(entry: ET.Element) -> Optional[Dict[str, Any]]:
    """Normalize ArXiv Atom entry into DevPulseAI signal schema."""
    arxiv_url = get_entry_text(entry, "atom:id")
    arxiv_id = extract_arxiv_id(arxiv_url)

    title = get_entry_text(entry, "atom:title", default="Untitled")
    summary = get_entry_text(entry, "atom:summary")
    published = get_entry_text(entry, "atom:published")
    updated = get_entry_text(entry, "atom:updated")

    if not arxiv_id or not arxiv_url:
        return None

    authors = get_authors(entry)
    categories = get_categories(entry)
    primary_category = get_primary_category(entry)
    pdf_link = get_pdf_link(entry, fallback_url=arxiv_url)

    return {
        "id": arxiv_id,
        "source": "arxiv",
        "title": title,
        "description": truncate_text(summary, max_chars=500),
        "url": arxiv_url,
        "metadata": {
            "pdf": pdf_link,
            "published": published,
            "updated": updated,
            "authors": authors,
            "categories": categories,
            "primary_category": primary_category,
        },
    }


async def fetch_arxiv_xml(
    client: httpx.AsyncClient,
    limit: int,
    categories: Optional[List[str]] = None,
) -> bytes:
    """Fetch raw ArXiv Atom XML with retries."""
    safe_limit = min(max(limit, 1), MAX_LIMIT)

    params = {
        "search_query": build_search_query(categories),
        "start": 0,
        "max_results": safe_limit,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }

    for attempt in range(MAX_RETRIES):
        try:
            response = await client.get(
                ARXIV_API_URL,
                params=params,
            )
            response.raise_for_status()

            logger.info("Fetched ArXiv XML with max_results=%s", safe_limit)
            return response.content
        except httpx.TimeoutException:
            logger.warning("ArXiv timeout (attempt %s)", attempt + 1)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                retry_after = exc.response.headers.get("Retry-After")
                try:
                    sleep_time = min(int(retry_after), MAX_RATE_LIMIT_SLEEP) if retry_after else MAX_RATE_LIMIT_SLEEP
                except ValueError:
                    sleep_time = MAX_RATE_LIMIT_SLEEP
                logger.warning(
                    "ArXiv rate limited (429) on attempt %s. Sleeping %ss",
                    attempt + 1,
                    sleep_time,
                )
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(sleep_time)
                continue
            logger.warning(
                "ArXiv HTTP %s (attempt %s)",
                exc.response.status_code,
                attempt + 1,
            )
        except Exception as exc:
            logger.error("Unexpected ArXiv fetch error: %s", exc)

        if attempt < MAX_RETRIES - 1:
            sleep_time = 3 * (attempt + 1)
            logger.info("Retrying ArXiv request in %ss", sleep_time)
            await asyncio.sleep(sleep_time)

    return b""


def parse_arxiv_entries(xml_content: bytes) -> List[Dict[str, Any]]:
    """Parse ArXiv XML into normalized signal dictionaries."""
    if not xml_content:
        return []

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as exc:
        logger.warning("ArXiv XML parse error: %s", exc)
        return []

    unique_signals: Dict[str, Dict[str, Any]] = {}
    for entry in root.findall("atom:entry", ATOM_NS):
        try:
            signal = normalize_entry(entry)
            if signal is None:
                continue

            unique_signals[f"{signal['source']}:{signal['id']}"] = signal
        except Exception as exc:
            logger.warning("ArXiv normalization error: %s", exc)

    signals = list(unique_signals.values())
    logger.info("ArXiv normalized signals: %s", len(signals))
    return signals


async def fetch_arxiv_papers_async(
    limit: int = 5,
    categories: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Async ArXiv fetch implementation."""
    safe_limit = min(max(limit, 1), MAX_LIMIT)

    async with httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT,
        headers=get_headers(),
        trust_env=False,
    ) as client:
        xml_content = await fetch_arxiv_xml(
            client=client,
            limit=safe_limit,
            categories=categories,
        )

    signals = parse_arxiv_entries(xml_content)
    return signals[:safe_limit]


def fetch_arxiv_papers(
    limit: int = 5,
    categories: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Sync wrapper.

    Safe for CLI usage.
    In async environments, call fetch_arxiv_papers_async() directly.
    """
    try:
        asyncio.get_running_loop()
        raise RuntimeError(
            "fetch_arxiv_papers() cannot run inside "
            "an existing event loop. "
            "Use fetch_arxiv_papers_async() instead."
        )
    except RuntimeError as exc:
        if "no running event loop" in str(exc).lower():
            return asyncio.run(
                fetch_arxiv_papers_async(
                    limit=limit,
                    categories=categories,
                )
            )
        raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    results = fetch_arxiv_papers(limit=3)

    print("\n=== RECENT ARXIV AI/ML PAPERS ===\n")
    for idx, paper in enumerate(results, start=1):
        print(f"{idx}. {paper['title']}")
        print(f"   ID: {paper['id']}")
        print(f"   Published: {paper['metadata']['published']}")
        print(f"   Primary category: {paper['metadata']['primary_category']}")
        print(f"   PDF: {paper['metadata']['pdf']}")
        print()
