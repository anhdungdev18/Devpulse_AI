"""
Production-ish HuggingFace adapter for DevPulseAI.

Features:
- Uses public HuggingFace Hub API
- Optional token authentication via HUGGINGFACE_TOKEN or HF_TOKEN
- Retry with exponential backoff
- Async implementation + sync wrapper
- Safe JSON parsing
- Model/task filtering
- Standardized schema normalization
- trust_env=False to bypass broken local proxy settings

Public API:
- fetch_huggingface_models(...) -> sync wrapper used by the current pipeline
- fetch_huggingface_models_async(...) -> async implementation
"""

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("devpulse.huggingface_adapter")

HUGGINGFACE_API_URL = "https://huggingface.co/api/models"

DEFAULT_TIMEOUT = 15.0
MAX_RETRIES = 3
MAX_LIMIT = 50

DEFAULT_TASKS = [
    "text-generation",
    "text2text-generation",
    "automatic-speech-recognition",
    "image-text-to-text",
    "sentence-similarity",
]


def clean_text(text: Optional[str]) -> str:
    """Normalize whitespace."""
    if not text:
        return ""
    return " ".join(str(text).split())


def get_headers() -> Dict[str, str]:
    """Build request headers with optional HuggingFace auth."""
    headers = {
        "User-Agent": "DevPulseAI",
    }

    token = os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers


def build_description(item: Dict[str, Any]) -> str:
    """Build a compact model description from metadata."""
    tags = item.get("tags") or []
    pipeline = item.get("pipeline_tag") or ""

    description_parts = []
    if pipeline:
        description_parts.append(f"Pipeline: {pipeline}")

    if tags:
        description_parts.append(f"Tags: {', '.join(tags[:5])}")

    description_parts.append(f"Downloads: {item.get('downloads') or 0:,}")
    description_parts.append(f"Likes: {item.get('likes') or 0:,}")
    return " | ".join(description_parts)


def is_relevant_model(
    item: Dict[str, Any],
    tasks: Optional[List[str]] = None,
) -> bool:
    """Apply local relevance filtering for AI/ML developer signals."""
    selected_tasks = tasks or DEFAULT_TASKS

    pipeline = item.get("pipeline_tag") or ""
    tags = item.get("tags") or []
    searchable = " ".join(
        [
            clean_text(pipeline),
            " ".join(clean_text(tag) for tag in tags),
            clean_text(item.get("modelId") or item.get("id")),
        ]
    ).lower()

    for task in selected_tasks:
        normalized_task = task.lower()
        if normalized_task in searchable:
            return True

    broad_keywords = [
        "llm",
        "language-model",
        "text-generation",
        "transformers",
        "chat",
        "instruct",
        "embedding",
        "reranker",
        "diffusion",
        "vision-language",
        "multimodal",
    ]
    return any(keyword in searchable for keyword in broad_keywords)


def normalize_model(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize HuggingFace model payload into DevPulseAI signal schema."""
    model_id = clean_text(
        item.get("modelId")
        or item.get("id")
        or ""
    )
    if not model_id:
        return None

    tags = item.get("tags") or []
    pipeline = item.get("pipeline_tag") or ""

    return {
        "id": model_id,
        "source": "huggingface",
        "title": f"HF Model: {model_id}",
        "description": build_description(item),
        "url": f"https://huggingface.co/{model_id}",
        "metadata": {
            "downloads": item.get("downloads") or 0,
            "likes": item.get("likes") or 0,
            "pipeline_tag": pipeline,
            "tags": tags[:10],
            "author": item.get("author") or "",
            "last_modified": item.get("lastModified"),
            "created_at": item.get("createdAt"),
            "private": item.get("private", False),
            "gated": item.get("gated", False),
        },
    }


async def fetch_huggingface_json(
    client: httpx.AsyncClient,
    limit: int,
    sort: str,
    direction: str,
    tasks: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Fetch raw HuggingFace model JSON with retries."""
    safe_limit = min(max(limit, 1), MAX_LIMIT)
    request_limit = min(safe_limit * 3, 100)

    params = {
        "sort": sort,
        "direction": direction,
        "limit": request_limit,
        "full": "true",
    }

    if tasks and len(tasks) == 1:
        params["pipeline_tag"] = tasks[0]

    for attempt in range(MAX_RETRIES):
        try:
            response = await client.get(
                HUGGINGFACE_API_URL,
                params=params,
            )
            response.raise_for_status()

            data = response.json()
            if not isinstance(data, list):
                logger.warning(
                    "Unexpected HuggingFace response shape: %s",
                    type(data),
                )
                return []

            logger.info("Fetched HuggingFace models: %s", len(data))
            return data
        except httpx.TimeoutException:
            logger.warning(
                "HuggingFace timeout (attempt %s)",
                attempt + 1,
            )
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "HuggingFace HTTP %s (attempt %s)",
                exc.response.status_code,
                attempt + 1,
            )
        except ValueError as exc:
            logger.warning("HuggingFace JSON parse error: %s", exc)
            return []
        except Exception as exc:
            logger.error("Unexpected HuggingFace fetch error: %s", exc)

        if attempt < MAX_RETRIES - 1:
            sleep_time = 2 ** attempt
            logger.info("Retrying HuggingFace request in %ss", sleep_time)
            await asyncio.sleep(sleep_time)

    return []


def parse_huggingface_models(
    data: List[Dict[str, Any]],
    limit: int,
    tasks: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Parse HuggingFace model payloads into normalized signal dictionaries."""
    safe_limit = min(max(limit, 1), MAX_LIMIT)
    unique_signals: Dict[str, Dict[str, Any]] = {}

    for item in data:
        try:
            if not is_relevant_model(item, tasks=tasks):
                continue

            signal = normalize_model(item)
            if signal is None:
                continue

            unique_signals[f"{signal['source']}:{signal['id']}"] = signal
            if len(unique_signals) >= safe_limit:
                break
        except Exception as exc:
            logger.warning("HuggingFace normalization error: %s", exc)

    signals = list(unique_signals.values())
    logger.info("HuggingFace normalized signals: %s", len(signals))
    return signals


async def fetch_huggingface_models_async(
    limit: int = 5,
    sort: str = "likes",
    direction: str = "-1",
    tasks: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Async HuggingFace fetch implementation."""
    safe_limit = min(max(limit, 1), MAX_LIMIT)
    headers = get_headers()

    async with httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT,
        headers=headers,
        trust_env=False,
    ) as client:
        data = await fetch_huggingface_json(
            client=client,
            limit=safe_limit,
            sort=sort,
            direction=direction,
            tasks=tasks,
        )

    return parse_huggingface_models(
        data=data,
        limit=safe_limit,
        tasks=tasks,
    )


def fetch_huggingface_models(
    limit: int = 5,
    sort: str = "likes",
    direction: str = "-1",
    tasks: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Sync wrapper.

    Safe for CLI usage.
    In async environments, call fetch_huggingface_models_async() directly.
    """
    try:
        asyncio.get_running_loop()
        raise RuntimeError(
            "fetch_huggingface_models() cannot run inside "
            "an existing event loop. "
            "Use fetch_huggingface_models_async() instead."
        )
    except RuntimeError as exc:
        if "no running event loop" in str(exc).lower():
            return asyncio.run(
                fetch_huggingface_models_async(
                    limit=limit,
                    sort=sort,
                    direction=direction,
                    tasks=tasks,
                )
            )
        raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    results = fetch_huggingface_models(limit=3)

    print("\n=== TRENDING HUGGINGFACE MODELS ===\n")
    for idx, model in enumerate(results, start=1):
        print(f"{idx}. {model['title']}")
        print(f"   Likes: {model['metadata']['likes']}")
        print(f"   Downloads: {model['metadata']['downloads']}")
        print(f"   Pipeline: {model['metadata']['pipeline_tag']}")
        print(f"   URL: {model['url']}")
        print()
