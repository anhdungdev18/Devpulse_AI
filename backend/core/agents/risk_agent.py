"""
Risk Agent — Assesses security risks and breaking changes.

Hybrid scoring model:
- Deterministic keyword analysis builds baseline risk factors
- LLM provides contextual risk dimensions only
- Final risk score is computed with a fixed weighted formula
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat

from ..scoring.risk_scoring import (
    clamp_score,
    combine_risk_scores,
    compute_keyword_risk_factors,
    risk_score_to_level,
)

logger = logging.getLogger("devpulse.risk_agent")

DEFAULT_MODEL = os.environ.get("MODEL_RISK", "gpt-4.1-mini")


class RiskAgent:
    """Hybrid deterministic + LLM risk assessor."""

    RISK_LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

    def __init__(self, model_id: Optional[str] = None):
        self.model_id = model_id or DEFAULT_MODEL

        self.agent = Agent(
            name="Risk Assessor",
            model=OpenAIChat(id=self.model_id),
            role="Assesses security and breaking-change risks in technical signals",
            instructions=[
                "Analyze technical signals for developer-impacting risk.",
                "Return only valid JSON.",
                "Do not output a final combined risk score.",
                "Provide severity, exploitability, developer_impact, migration_cost, confidence, concerns, and breaking_changes.",
                "Do not overstate risk when the signal is merely informational.",
            ],
            markdown=False,
        )

    def assess(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        deterministic = compute_keyword_risk_factors(signal)

        if not os.getenv("OPENAI_API_KEY"):
            contextual = self._contextual_fallback(signal, deterministic, "OPENAI_API_KEY not configured")
        else:
            prompt = self._build_prompt(signal, deterministic)
            try:
                response = self.agent.run(prompt, stream=False)
                content = getattr(response, "content", "")
                contextual = self._parse_response(content, signal, deterministic)
            except Exception as exc:
                logger.warning("LLM risk assessment failed: %s", exc)
                contextual = self._contextual_fallback(signal, deterministic, str(exc))

        factors = {
            "severity": self._blend_factor("severity", deterministic, contextual),
            "exploitability": self._blend_factor("exploitability", deterministic, contextual),
            "developer_impact": self._blend_factor("developer_impact", deterministic, contextual),
            "migration_cost": self._blend_factor("migration_cost", deterministic, contextual),
            "confidence": self._blend_factor("confidence", deterministic, contextual),
        }

        risk_score = combine_risk_scores(factors)
        concerns = contextual.get("concerns") or deterministic.get("concerns") or [
            "No specific concerns identified."
        ]
        breaking_changes = bool(
            contextual.get("breaking_changes", False) or deterministic.get("breaking_changes", False)
        )

        return {
            "risk_level": risk_score_to_level(risk_score),
            "risk_score": risk_score,
            "concerns": concerns,
            "breaking_changes": breaking_changes,
            "factors": factors,
        }

    def assess_batch(self, signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        assessed_signals: List[Dict[str, Any]] = []
        for signal in signals:
            risk = self.assess(signal)
            assessed_signals.append({**signal, "risk": risk})
        return assessed_signals

    def _build_prompt(self, signal: Dict[str, Any], deterministic: Dict[str, Any]) -> str:
        safe_signal = {
            "source": signal.get("source", "unknown"),
            "title": signal.get("title", "Untitled"),
            "description": signal.get("description", ""),
            "url": signal.get("url", ""),
            "metadata": signal.get("metadata", {}),
            "deterministic_risk_baseline": {
                key: deterministic[key]
                for key in ["severity", "exploitability", "developer_impact", "migration_cost", "confidence"]
            },
        }

        return f"""
Analyze this technical signal for AI/ML developer risk.

You are NOT responsible for the final combined risk score.
Estimate these contextual dimensions from 0 to 100:
- severity
- exploitability
- developer_impact
- migration_cost
- confidence

Also provide:
- concerns: concise list of specific issues
- breaking_changes: true or false

Signal JSON:
{json.dumps(safe_signal, ensure_ascii=False, indent=2)}

Return ONLY valid JSON in this exact shape:
{{
  "severity": 70,
  "exploitability": 40,
  "developer_impact": 90,
  "migration_cost": 80,
  "confidence": 70,
  "concerns": ["Possible breaking API migration"],
  "breaking_changes": true
}}
""".strip()

    def _parse_response(
        self,
        content: str,
        signal: Dict[str, Any],
        deterministic: Dict[str, Any],
    ) -> Dict[str, Any]:
        try:
            text = self._extract_json(content)
            parsed = json.loads(text)

            concerns_raw = parsed.get("concerns", [])
            if isinstance(concerns_raw, str):
                concerns = [concerns_raw.strip()] if concerns_raw.strip() else []
            elif isinstance(concerns_raw, list):
                concerns = [str(item).strip() for item in concerns_raw if str(item).strip()]
            else:
                concerns = []

            return {
                "severity": clamp_score(parsed.get("severity", deterministic.get("severity", 0))),
                "exploitability": clamp_score(parsed.get("exploitability", deterministic.get("exploitability", 0))),
                "developer_impact": clamp_score(parsed.get("developer_impact", deterministic.get("developer_impact", 0))),
                "migration_cost": clamp_score(parsed.get("migration_cost", deterministic.get("migration_cost", 0))),
                "confidence": clamp_score(parsed.get("confidence", deterministic.get("confidence", 0))),
                "concerns": concerns,
                "breaking_changes": bool(parsed.get("breaking_changes", False)),
            }
        except Exception as exc:
            logger.warning("Failed to parse risk response: %s", exc)
            return self._contextual_fallback(signal, deterministic, f"Parse error: {exc}")

    def _extract_json(self, content: str) -> str:
        text = (content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text).strip()
            text = re.sub(r"```$", "", text).strip()

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("No JSON object found in model response")
        return match.group(0)

    def _fallback_assessment(self, signal: Dict[str, Any], error: str) -> Dict[str, Any]:
        deterministic = compute_keyword_risk_factors(signal)
        contextual = self._contextual_fallback(signal, deterministic, error)
        factors = {
            "severity": self._blend_factor("severity", deterministic, contextual),
            "exploitability": self._blend_factor("exploitability", deterministic, contextual),
            "developer_impact": self._blend_factor("developer_impact", deterministic, contextual),
            "migration_cost": self._blend_factor("migration_cost", deterministic, contextual),
            "confidence": self._blend_factor("confidence", deterministic, contextual),
        }
        risk_score = combine_risk_scores(factors)
        return {
            "risk_level": risk_score_to_level(risk_score),
            "risk_score": risk_score,
            "concerns": contextual.get("concerns") or deterministic.get("concerns") or [
                f"Heuristic assessment used because LLM failed: {error}"
            ],
            "breaking_changes": bool(
                contextual.get("breaking_changes", False) or deterministic.get("breaking_changes", False)
            ),
            "factors": factors,
        }

    def _contextual_fallback(
        self,
        signal: Dict[str, Any],
        deterministic: Dict[str, Any],
        error: str,
    ) -> Dict[str, Any]:
        title = str(signal.get("title", "")).lower()
        description = str(signal.get("description", "")).lower()
        metadata = signal.get("metadata", {}) or {}
        searchable = f"{title} {description} {json.dumps(metadata, default=str).lower()}"

        severity = deterministic.get("severity", 10)
        exploitability = deterministic.get("exploitability", 5)
        developer_impact = deterministic.get("developer_impact", 10)
        migration_cost = deterministic.get("migration_cost", 5)
        confidence = deterministic.get("confidence", 45)

        if "license" in searchable or "gated" in searchable:
            developer_impact += 8
            confidence += 5
        if "model safety" in searchable or "alignment" in searchable:
            severity += 5
            confidence += 5
        if "dependency" in searchable or "package" in searchable:
            migration_cost += 5
        if "breaking" in searchable or "migration" in searchable:
            migration_cost += 10
            developer_impact += 8

        return {
            "severity": clamp_score(severity),
            "exploitability": clamp_score(exploitability),
            "developer_impact": clamp_score(developer_impact),
            "migration_cost": clamp_score(migration_cost),
            "confidence": clamp_score(confidence),
            "concerns": deterministic.get("concerns") or [f"Heuristic assessment used because LLM failed: {error}"],
            "breaking_changes": bool(deterministic.get("breaking_changes", False)),
        }

    def _blend_factor(self, key: str, deterministic: Dict[str, Any], contextual: Dict[str, Any]) -> int:
        deterministic_value = clamp_score(deterministic.get(key, 0))
        contextual_value = clamp_score(contextual.get(key, deterministic_value))
        return clamp_score(0.4 * deterministic_value + 0.6 * contextual_value)
