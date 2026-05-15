from __future__ import annotations

import json
from typing import Any, Dict, List


def clamp_score(value: Any) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    return max(0, min(int(round(numeric)), 100))


def detect_breaking_changes(signal: Dict[str, Any]) -> bool:
    searchable = _build_searchable(signal)
    breaking_keywords = [
        "breaking change",
        "deprecated",
        "deprecation",
        "removed",
        "migration",
        "incompatible",
        "api change",
        "end of support",
        "eol",
    ]
    return any(keyword in searchable for keyword in breaking_keywords)


def _build_searchable(signal: Dict[str, Any]) -> str:
    title = str(signal.get("title", "")).lower()
    description = str(signal.get("description", "")).lower()
    metadata = json.dumps(signal.get("metadata", {}) or {}, default=str).lower()
    return f"{title} {description} {metadata}"


def compute_keyword_risk_factors(signal: Dict[str, Any]) -> Dict[str, Any]:
    searchable = _build_searchable(signal)
    concerns: List[str] = []

    critical_keywords = [
        "active exploit",
        "remote code execution",
        "rce",
        "zero-day",
        "0-day",
        "critical vulnerability",
        "supply chain attack",
        "credential leak",
        "token leak",
        "private key leak",
    ]
    high_keywords = [
        "vulnerability",
        "exploit",
        "cve",
        "security advisory",
        "breach",
        "malware",
        "arbitrary code execution",
        "privilege escalation",
        "data leakage",
    ]
    medium_keywords = [
        "breaking change",
        "deprecated",
        "deprecation",
        "removed",
        "migration",
        "incompatible",
        "api change",
        "end of support",
        "eol",
    ]

    severity = 10
    exploitability = 5
    developer_impact = 10
    migration_cost = 5
    confidence = 45

    if any(keyword in searchable for keyword in critical_keywords):
        severity = 95
        exploitability = 90
        developer_impact = 85
        migration_cost = 60
        confidence = 85
        concerns.append("Detected critical security language.")
    elif any(keyword in searchable for keyword in high_keywords):
        severity = 75
        exploitability = 60
        developer_impact = 70
        migration_cost = 40
        confidence = 75
        concerns.append("Detected elevated security risk language.")
    elif any(keyword in searchable for keyword in medium_keywords):
        severity = 45
        exploitability = 20
        developer_impact = 70
        migration_cost = 65
        confidence = 70
        concerns.append("Detected migration or breaking-change language.")

    breaking_changes = detect_breaking_changes(signal)
    if breaking_changes:
        developer_impact = max(developer_impact, 70)
        migration_cost = max(migration_cost, 70)

    return {
        "severity": clamp_score(severity),
        "exploitability": clamp_score(exploitability),
        "developer_impact": clamp_score(developer_impact),
        "migration_cost": clamp_score(migration_cost),
        "confidence": clamp_score(confidence),
        "concerns": concerns,
        "breaking_changes": breaking_changes,
    }


def combine_risk_scores(factors: Dict[str, Any]) -> int:
    severity = clamp_score(factors.get("severity", 0))
    exploitability = clamp_score(factors.get("exploitability", 0))
    developer_impact = clamp_score(factors.get("developer_impact", 0))
    migration_cost = clamp_score(factors.get("migration_cost", 0))
    confidence = clamp_score(factors.get("confidence", 0))

    risk_score = (
        0.30 * severity
        + 0.25 * exploitability
        + 0.25 * developer_impact
        + 0.15 * migration_cost
        + 0.05 * confidence
    )
    return clamp_score(risk_score)


def risk_score_to_level(score: Any) -> str:
    value = clamp_score(score)
    if value <= 29:
        return "LOW"
    if value <= 59:
        return "MEDIUM"
    if value <= 84:
        return "HIGH"
    return "CRITICAL"
