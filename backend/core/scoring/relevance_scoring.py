from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict


def clamp_score(value: Any) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    return max(0, min(int(round(numeric)), 100))


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None

    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def compute_popularity_score(signal: Dict[str, Any]) -> int:
    metadata = signal.get("metadata", {}) or {}
    score = 0.0

    # Popularity reflects broad ecosystem pull, so larger public metrics
    # should saturate faster than before.
    score += min(metadata.get("stars", 0) / 15, 55)
    score += min(metadata.get("downloads", 0) / 1500, 45)
    score += min(metadata.get("likes", 0) / 10, 30)
    score += min(metadata.get("watchers", 0) / 5, 15)
    score += min(metadata.get("points", 0) / 3, 12)

    return clamp_score(score)


def compute_timeliness_score(signal: Dict[str, Any]) -> int:
    metadata = signal.get("metadata", {}) or {}
    candidates = [
        metadata.get("updated_at"),
        metadata.get("created_at"),
        metadata.get("published"),
        metadata.get("updated"),
        metadata.get("last_modified"),
        metadata.get("createdAt"),
        signal.get("collected_at"),
    ]

    parsed = next((dt for dt in (_parse_datetime(value) for value in candidates) if dt is not None), None)
    if parsed is None:
        return 65

    age_days = max((datetime.now(timezone.utc) - parsed).total_seconds() / 86400, 0)
    if age_days <= 1:
        return 100
    if age_days <= 3:
        return 92
    if age_days <= 7:
        return 82
    if age_days <= 14:
        return 72
    if age_days <= 30:
        return 58
    return 48


def compute_engagement_score(signal: Dict[str, Any]) -> int:
    metadata = signal.get("metadata", {}) or {}
    score = 0.0

    # Engagement is more about active interaction than passive popularity.
    score += min(metadata.get("points", 0) / 1.2, 45)
    score += min(metadata.get("comments", 0), 25)
    score += min(metadata.get("forks", 0) / 3, 22)
    score += min(metadata.get("likes", 0) / 10, 25)
    score += min(metadata.get("downloads", 0) / 2500, 18)

    return clamp_score(score)


def combine_relevance_scores(factors: Dict[str, Any]) -> int:
    popularity = clamp_score(factors.get("popularity", 0))
    timeliness = clamp_score(factors.get("timeliness", 0))
    engagement = clamp_score(factors.get("engagement", 0))
    technical_impact = clamp_score(factors.get("technical_impact", 0))
    actionability = clamp_score(factors.get("actionability", 0))
    ecosystem_relevance = clamp_score(factors.get("ecosystem_relevance", 0))

    final_score = (
        0.20 * popularity
        + 0.15 * timeliness
        + 0.15 * engagement
        + 0.25 * technical_impact
        + 0.15 * actionability
        + 0.10 * ecosystem_relevance
    )
    return clamp_score(final_score)
