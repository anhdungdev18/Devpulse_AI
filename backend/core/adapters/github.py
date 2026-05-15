"""
Production-ish GitHub adapter for DevPulseAI.

Improvements:
- Safer normalization
- Broad query + local topic filtering for better recall
- Regex keyword matching
- Capped rate-limit sleeping
- Async-safe sync wrapper
- GitHub API version headers
"""

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("devpulse.github_adapter")

GITHUB_API_URL = "https://api.github.com/search/repositories"

DEFAULT_TOPICS = [
    "llm",
    "ai",
    "machine-learning",
    "artificial-intelligence",
    "deep-learning",
]

DEFAULT_TIMEOUT = 20.0
MAX_RETRIES = 3
MAX_RATE_LIMIT_SLEEP = 60


def build_query(
    days_back: int = 7,
    topics: Optional[List[str]] = None,
    min_stars: int = 10,
) -> str:
    """
    Build a broad GitHub repository search query.

    Topic filtering stays local because GitHub search topic constraints are
    inconsistent and can collapse recall to zero on recent repositories.
    """
    date_query = (
        datetime.now(timezone.utc) - timedelta(days=days_back)
    ).strftime("%Y-%m-%d")

    query_parts = [
        f"created:>{date_query}",
        f"stars:>{min_stars}",
    ]
    return " ".join(query_parts)


def get_headers() -> Dict[str, str]:
    """Build request headers with optional auth."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "DevPulseAI",
    }

    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers


def normalize_repository(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize GitHub repository payload into app schema safely."""
    repo_id = item.get("id")
    full_name = item.get("full_name")
    html_url = item.get("html_url")

    if not repo_id or not full_name or not html_url:
        return None

    return {
        "id": str(repo_id),
        "source": "github",
        "title": full_name,
        "description": item.get("description") or "No description",
        "url": html_url,
        "metadata": {
            "stars": item.get("stargazers_count", 0),
            "forks": item.get("forks_count", 0),
            "language": item.get("language"),
            "topics": item.get("topics", []),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
            "watchers": item.get("watchers_count", 0),
            "open_issues": item.get("open_issues_count", 0),
            "owner": (item.get("owner") or {}).get("login"),
            "license": ((item.get("license") or {}).get("name")),
        },
    }


def contains_keyword(text: str, keyword: str) -> bool:
    """Regex-based keyword matching with word boundaries."""
    pattern = rf"\b{re.escape(keyword)}\b"
    return re.search(pattern, text, re.IGNORECASE) is not None


def is_relevant_repository(
    item: Dict[str, Any],
    topics: Optional[List[str]] = None,
) -> bool:
    """Apply secondary filtering locally."""
    selected_topics = [t.lower() for t in (topics or DEFAULT_TOPICS)]
    repo_topics = [topic.lower() for topic in item.get("topics", [])]
    description = (item.get("description") or "").lower()
    name = item.get("full_name", "").lower()
    searchable = f"{name} {description}"

    if any(topic in repo_topics for topic in selected_topics):
        return True

    keyword_variants = {
        "llm": ["llm", "large language model"],
        "ai": ["ai", "artificial intelligence"],
        "machine-learning": ["machine learning", "machine-learning", "ml"],
        "artificial-intelligence": ["artificial intelligence"],
        "deep-learning": ["deep learning", "deep-learning"],
    }

    for topic in selected_topics:
        variants = keyword_variants.get(topic, [topic.replace("-", " "), topic])
        for variant in variants:
            if contains_keyword(searchable, variant):
                return True

    return False


async def handle_rate_limit(response: httpx.Response) -> None:
    """Handle GitHub rate limiting safely."""
    if response.status_code != 403:
        return

    remaining = response.headers.get("X-RateLimit-Remaining")
    reset_time = response.headers.get("X-RateLimit-Reset")

    if remaining == "0" and reset_time:
        try:
            reset_timestamp = int(reset_time)
            current_timestamp = int(datetime.now(timezone.utc).timestamp())
            sleep_seconds = max(reset_timestamp - current_timestamp, 1)
            capped_sleep = min(sleep_seconds, MAX_RATE_LIMIT_SLEEP)

            logger.warning(
                "GitHub rate limit reached. Sleeping %ss (capped from %ss)",
                capped_sleep,
                sleep_seconds,
            )
            await asyncio.sleep(capped_sleep)
        except Exception as exc:
            logger.warning("Failed handling GitHub rate limit: %s", exc)


async def fetch_page(
    client: httpx.AsyncClient,
    query: str,
    per_page: int,
    page: int,
) -> List[Dict[str, Any]]:
    """Fetch a single page with retries."""
    params = {
        "q": query,
        "sort": "stars",
        "order": "desc",
        "per_page": per_page,
        "page": page,
    }

    for attempt in range(MAX_RETRIES):
        try:
            response = await client.get(GITHUB_API_URL, params=params)
            await handle_rate_limit(response)
            response.raise_for_status()

            data = response.json()
            items = data.get("items", [])
            logger.info(
                "GitHub page %s fetched %s repositories",
                page,
                len(items),
            )
            return items
        except httpx.TimeoutException:
            logger.warning(
                "GitHub timeout on page %s (attempt %s)",
                page,
                attempt + 1,
            )
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "GitHub HTTP %s on page %s (attempt %s)",
                exc.response.status_code,
                page,
                attempt + 1,
            )
        except Exception as exc:
            logger.error(
                "GitHub unexpected error on page %s: %s",
                page,
                exc,
            )

        if attempt < MAX_RETRIES - 1:
            sleep_time = 2 ** attempt
            logger.info("Retrying GitHub page %s in %ss", page, sleep_time)
            await asyncio.sleep(sleep_time)

    return []


async def fetch_github_trending_async(
    limit: int = 10,
    days_back: int = 7,
    min_stars: int = 10,
    topics: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Async GitHub fetch implementation."""
    query = build_query(
        days_back=days_back,
        topics=topics,
        min_stars=min_stars,
    )
    headers = get_headers()
    logger.info("GitHub query: %s", query)

    per_page = min(max(limit * 10, 50), 100)
    total_pages = min(5, max(1, (limit * 5 + per_page - 1) // per_page))
    raw_items: List[Dict[str, Any]] = []

    async with httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT,
        headers=headers,
        trust_env=False,
    ) as client:
        for page in range(1, total_pages + 1):
            items = await fetch_page(
                client=client,
                query=query,
                per_page=per_page,
                page=page,
            )

            filtered_items = [
                item
                for item in items
                if is_relevant_repository(item, topics)
            ]
            raw_items.extend(filtered_items)

            if len(raw_items) >= limit or not items:
                break

    unique_signals: Dict[str, Dict[str, Any]] = {}
    for item in raw_items:
        try:
            signal = normalize_repository(item)
            if signal is None:
                continue

            unique_signals[f"{signal['source']}:{signal['id']}"] = signal
        except Exception as exc:
            logger.warning("GitHub normalization error: %s", exc)

    final_signals = list(unique_signals.values())[:limit]
    logger.info("GitHub final normalized signals: %s", len(final_signals))
    return final_signals


def fetch_github_trending(
    limit: int = 10,
    days_back: int = 7,
    min_stars: int = 10,
    topics: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Sync wrapper.

    Safe for CLI usage.
    In async environments, call fetch_github_trending_async() directly.
    """
    try:
        asyncio.get_running_loop()
        raise RuntimeError(
            "fetch_github_trending() cannot run inside an existing event loop. "
            "Use fetch_github_trending_async() instead."
        )
    except RuntimeError as exc:
        if "no running event loop" in str(exc).lower():
            return asyncio.run(
                fetch_github_trending_async(
                    limit=limit,
                    days_back=days_back,
                    min_stars=min_stars,
                    topics=topics,
                )
            )
        raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    results = fetch_github_trending(
        limit=5,
        days_back=7,
        min_stars=100,
    )

    print("\n=== TRENDING AI REPOSITORIES ===\n")
    for idx, repo in enumerate(results, start=1):
        print(f"{idx}. {repo['title']}")
        print(f"   Stars: {repo['metadata']['stars']}")
        print(f"   Language: {repo['metadata']['language']}")
        print(f"   URL: {repo['url']}")
        print()
