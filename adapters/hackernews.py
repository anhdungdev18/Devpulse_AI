"""
Production-ish HackerNews adapter for DevPulseAI.

Features:
- Uses Algolia HackerNews API
- Retry with exponential backoff
- Async implementation + sync wrapper
- Query/category customization
- Safe JSON parsing
- Whitespace normalization
- Basic relevance filtering
- Standardized schema normalization
- trust_env=False to bypass broken local proxy settings

Public API:
- fetch_hackernews_stories(...) -> sync wrapper used by the current pipeline
- fetch_hackernews_stories_async(...) -> async implementation
"""

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("devpulse.hackernews_adapter")

HN_ALGOLIA_API_URL = "https://hn.algolia.com/api/v1/search_by_date"

DEFAULT_QUERY_TERMS = [
    "AI",
    "LLM",
    "GPT",
    "OpenAI",
    "Claude",
    "Machine Learning",
    "Deep Learning",
]

DEFAULT_TIMEOUT = 15.0
MAX_RETRIES = 3
MAX_LIMIT = 50
DEFAULT_MIN_POINTS = 5


def clean_text(text: Optional[str]) -> str:
    """Normalize whitespace."""
    if not text:
        return ""
    return " ".join(str(text).split())


def truncate_text(text: str, max_chars: int = 300) -> str:
    """Truncate long text safely."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def contains_keyword(text: str, keyword: str) -> bool:
    """Regex keyword match with word boundaries."""
    if not text or not keyword:
        return False

    pattern = rf"\b{re.escape(keyword)}\b"
    return re.search(pattern, text, re.IGNORECASE) is not None


def build_query(query_terms: Optional[List[str]] = None) -> str:
    """
    Build Algolia HN query.

    Algolia's query parser is not a strict boolean engine,
    so we keep this as a readable broad query.
    """
    selected_terms = query_terms or DEFAULT_QUERY_TERMS
    broad_terms = selected_terms[:4]
    return " OR ".join(broad_terms)


def is_relevant_story(
    hit: Dict[str, Any],
    query_terms: Optional[List[str]] = None,
) -> bool:
    """Secondary local relevance filtering."""
    selected_terms = query_terms or DEFAULT_QUERY_TERMS

    title = clean_text(hit.get("title"))
    story_text = clean_text(hit.get("story_text"))
    url = clean_text(hit.get("url"))
    searchable = f"{title} {story_text} {url}"

    keyword_variants = {
        "AI": ["AI", "artificial intelligence"],
        "LLM": ["LLM", "large language model"],
        "GPT": ["GPT", "ChatGPT"],
        "Machine Learning": ["machine learning", "ML"],
        "Deep Learning": ["deep learning"],
    }

    for term in selected_terms:
        variants = keyword_variants.get(term, [term])
        for variant in variants:
            if contains_keyword(searchable, variant):
                return True

    return False


def normalize_story(hit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize Algolia HN hit into DevPulseAI signal schema."""
    external_id = str(hit.get("objectID") or "").strip()
    if not external_id:
        return None

    hn_url = f"https://news.ycombinator.com/item?id={external_id}"

    title = clean_text(
        hit.get("title")
        or hit.get("story_title")
        or "Untitled"
    )
    story_text = clean_text(
        hit.get("story_text")
        or hit.get("comment_text")
        or ""
    )
    url = hit.get("url") or hit.get("story_url") or hn_url

    return {
        "id": external_id,
        "source": "hackernews",
        "title": title,
        "description": truncate_text(story_text, max_chars=300),
        "url": url,
        "metadata": {
            "points": hit.get("points") or 0,
            "comments": hit.get("num_comments") or 0,
            "author": hit.get("author") or "unknown",
            "created_at": hit.get("created_at"),
            "created_at_i": hit.get("created_at_i"),
            "hn_url": hn_url,
            "tags": hit.get("_tags", []),
        },
    }


async def fetch_hackernews_json(
    client: httpx.AsyncClient,
    limit: int,
    min_points: int,
    query_terms: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Fetch raw HackerNews Algolia JSON with retries."""
    safe_limit = min(max(limit, 1), MAX_LIMIT)

    params = {
        "query": build_query(query_terms),
        "tags": "story",
        "hitsPerPage": safe_limit * 3,
        "numericFilters": f"points>{min_points}",
    }

    for attempt in range(MAX_RETRIES):
        try:
            response = await client.get(
                HN_ALGOLIA_API_URL,
                params=params,
            )
            response.raise_for_status()

            data = response.json()
            logger.info(
                "Fetched HackerNews hits: %s",
                len(data.get("hits", [])),
            )
            return data
        except httpx.TimeoutException:
            logger.warning(
                "HackerNews timeout (attempt %s)",
                attempt + 1,
            )
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "HackerNews HTTP %s (attempt %s)",
                exc.response.status_code,
                attempt + 1,
            )
        except ValueError as exc:
            logger.warning("HackerNews JSON parse error: %s", exc)
            return {}
        except Exception as exc:
            logger.error("Unexpected HackerNews fetch error: %s", exc)

        if attempt < MAX_RETRIES - 1:
            sleep_time = 2 ** attempt
            logger.info("Retrying HackerNews request in %ss", sleep_time)
            await asyncio.sleep(sleep_time)

    return {}


def parse_hackernews_hits(
    data: Dict[str, Any],
    limit: int,
    query_terms: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Parse Algolia hits into normalized signal dictionaries."""
    if not data:
        return []

    safe_limit = min(max(limit, 1), MAX_LIMIT)
    unique_signals: Dict[str, Dict[str, Any]] = {}

    for hit in data.get("hits", []):
        try:
            if not hit.get("url") and not hit.get("story_text"):
                continue

            if not is_relevant_story(hit, query_terms=query_terms):
                continue

            signal = normalize_story(hit)
            if signal is None:
                continue

            unique_signals[f"{signal['source']}:{signal['id']}"] = signal
            if len(unique_signals) >= safe_limit:
                break
        except Exception as exc:
            logger.warning("HackerNews normalization error: %s", exc)

    signals = list(unique_signals.values())
    logger.info("HackerNews normalized signals: %s", len(signals))
    return signals


async def fetch_hackernews_stories_async(
    limit: int = 5,
    min_points: int = DEFAULT_MIN_POINTS,
    query_terms: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Async HackerNews fetch implementation."""
    safe_limit = min(max(limit, 1), MAX_LIMIT)

    async with httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT,
        trust_env=False,
    ) as client:
        data = await fetch_hackernews_json(
            client=client,
            limit=safe_limit,
            min_points=min_points,
            query_terms=query_terms,
        )

    return parse_hackernews_hits(
        data=data,
        limit=safe_limit,
        query_terms=query_terms,
    )


def fetch_hackernews_stories(
    limit: int = 5,
    min_points: int = DEFAULT_MIN_POINTS,
    query_terms: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Sync wrapper.

    Safe for CLI usage.
    In async environments, call fetch_hackernews_stories_async() directly.
    """
    try:
        asyncio.get_running_loop()
        raise RuntimeError(
            "fetch_hackernews_stories() cannot run inside "
            "an existing event loop. "
            "Use fetch_hackernews_stories_async() instead."
        )
    except RuntimeError as exc:
        if "no running event loop" in str(exc).lower():
            return asyncio.run(
                fetch_hackernews_stories_async(
                    limit=limit,
                    min_points=min_points,
                    query_terms=query_terms,
                )
            )
        raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    results = fetch_hackernews_stories(
        limit=3,
        min_points=5,
    )

    print("\n=== RECENT HACKERNEWS AI/ML STORIES ===\n")
    for idx, story in enumerate(results, start=1):
        print(f"{idx}. {story['title']}")
        print(f"   Points: {story['metadata']['points']}")
        print(f"   Comments: {story['metadata']['comments']}")
        print(f"   HN URL: {story['metadata']['hn_url']}")
        print(f"   URL: {story['url']}")
        print()
