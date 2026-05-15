"""
Relevance Agent — Scores signals by developer relevance (0–100).

Hybrid scoring model:
- Deterministic metrics compute popularity, timeliness, engagement
- LLM provides semantic/contextual factors only
- Final score is computed with a fixed weighted formula
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat

from scoring.relevance_scoring import (
    clamp_score,
    combine_relevance_scores,
    compute_engagement_score,
    compute_popularity_score,
    compute_timeliness_score,
)

logger = logging.getLogger("devpulse.relevance_agent")

DEFAULT_MODEL = os.environ.get("MODEL_RELEVANCE", "gpt-4.1-mini")


class RelevanceAgent:
    """Hybrid deterministic + LLM relevance scorer."""

    def __init__(self, model_id: Optional[str] = None):
        self.model_id = model_id or DEFAULT_MODEL

        self.agent = Agent(
            name="Relevance Scorer",
            model=OpenAIChat(id=self.model_id),
            role="Scores technical signals based on AI/ML developer relevance",
            instructions=[
                "You score only semantic relevance dimensions for AI/ML developers.",
                "Return only valid JSON.",
                "Do not output a final overall score.",
                "Provide technical_impact, actionability, ecosystem_relevance, and reasoning.",
                "Prefer concrete developer impact over hype.",
            ],
            markdown=False,
        )

    def score(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        deterministic_factors = {
            "popularity": compute_popularity_score(signal),
            "timeliness": compute_timeliness_score(signal),
            "engagement": compute_engagement_score(signal),
        }

        if not os.getenv("OPENAI_API_KEY"):
            semantic = self._semantic_fallback(signal, "OPENAI_API_KEY not configured")
        else:
            prompt = self._build_prompt(signal, deterministic_factors)
            try:
                response = self.agent.run(prompt, stream=False)
                content = getattr(response, "content", "")
                semantic = self._parse_response(content, signal)
            except Exception as exc:
                logger.warning("LLM relevance scoring failed: %s", exc)
                semantic = self._semantic_fallback(signal, str(exc))

        factors = {
            **deterministic_factors,
            "technical_impact": clamp_score(semantic.get("technical_impact", 0)),
            "actionability": clamp_score(semantic.get("actionability", 0)),
            "ecosystem_relevance": clamp_score(semantic.get("ecosystem_relevance", 0)),
        }

        return {
            "score": combine_relevance_scores(factors),
            "reasoning": semantic.get("reasoning", "Deterministic fallback applied."),
            "factors": factors,
        }

    def score_batch(self, signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        scored_signals: List[Dict[str, Any]] = []
        for signal in signals:
            relevance = self.score(signal)
            scored_signals.append({**signal, "relevance": relevance})
        return scored_signals

    def _build_prompt(self, signal: Dict[str, Any], deterministic_factors: Dict[str, int]) -> str:
        safe_signal = {
            "source": signal.get("source", "unknown"),
            "title": signal.get("title", "Untitled"),
            "description": signal.get("description", ""),
            "url": signal.get("url", ""),
            "metadata": signal.get("metadata", {}),
            "deterministic_factors": deterministic_factors,
        }

        return f"""
Rate the semantic relevance of this technical signal for AI/ML developers.

You are NOT responsible for the final score.
Only estimate these semantic dimensions from 0 to 100:
- technical_impact
- actionability
- ecosystem_relevance

Consider:
- practical developer impact
- implementation usefulness
- ecosystem significance
- whether a team should pay attention soon

Signal JSON:
{json.dumps(safe_signal, ensure_ascii=False, indent=2)}

Return ONLY valid JSON in this exact shape:
{{
  "technical_impact": 85,
  "actionability": 75,
  "ecosystem_relevance": 90,
  "reasoning": "This signal is highly relevant because..."
}}
""".strip()

    def _parse_response(self, content: str, signal: Dict[str, Any]) -> Dict[str, Any]:
        try:
            text = self._extract_json(content)
            parsed = json.loads(text)

            return {
                "technical_impact": clamp_score(parsed.get("technical_impact", 0)),
                "actionability": clamp_score(parsed.get("actionability", 0)),
                "ecosystem_relevance": clamp_score(parsed.get("ecosystem_relevance", 0)),
                "reasoning": str(parsed.get("reasoning", "")).strip() or "LLM provided no reasoning.",
            }
        except Exception as exc:
            logger.warning("Failed to parse relevance response: %s", exc)
            return self._semantic_fallback(signal, f"Parse error: {exc}")

    def _extract_json(self, content: str) -> str:
        text = (content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text).strip()
            text = re.sub(r"```$", "", text).strip()

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("No JSON object found in model response")
        return match.group(0)

    def _fallback_score(self, signal: Dict[str, Any], error: str) -> Dict[str, Any]:
        deterministic_factors = {
            "popularity": compute_popularity_score(signal),
            "timeliness": compute_timeliness_score(signal),
            "engagement": compute_engagement_score(signal),
        }
        semantic = self._semantic_fallback(signal, error)
        factors = {
            **deterministic_factors,
            "technical_impact": clamp_score(semantic.get("technical_impact", 0)),
            "actionability": clamp_score(semantic.get("actionability", 0)),
            "ecosystem_relevance": clamp_score(semantic.get("ecosystem_relevance", 0)),
        }
        return {
            "score": combine_relevance_scores(factors),
            "reasoning": semantic.get("reasoning", "Deterministic fallback applied."),
            "factors": factors,
        }

    def _semantic_fallback(self, signal: Dict[str, Any], error: str) -> Dict[str, Any]:
        metadata = signal.get("metadata", {}) or {}
        source = signal.get("source", "unknown")
        title = str(signal.get("title", "")).lower()
        description = str(signal.get("description", "")).lower()
        searchable = f"{title} {description}"

        technical_impact = 45
        actionability = 40
        ecosystem_relevance = 45

        high_value_keywords = {
            "llm": (10, 5, 10),
            "agent": (8, 10, 8),
            "openai": (8, 5, 10),
            "gpt": (8, 4, 10),
            "claude": (8, 4, 8),
            "transformer": (8, 3, 8),
            "inference": (10, 8, 6),
            "rag": (10, 10, 8),
            "vector": (5, 8, 5),
            "embedding": (7, 8, 7),
            "fine-tuning": (10, 8, 8),
            "benchmark": (8, 4, 7),
            "security": (8, 10, 6),
            "deprecation": (4, 10, 4),
        }
        for keyword, boosts in high_value_keywords.items():
            if keyword in searchable:
                technical_impact += boosts[0]
                actionability += boosts[1]
                ecosystem_relevance += boosts[2]

        if metadata.get("downloads", 0) >= 10000:
            ecosystem_relevance += 10
        if metadata.get("likes", 0) >= 100:
            ecosystem_relevance += 8
        if metadata.get("stars", 0) >= 1000:
            ecosystem_relevance += 10

        if source == "arxiv":
            technical_impact += 8
        elif source == "github":
            actionability += 8
        elif source == "huggingface":
            technical_impact += 6
            ecosystem_relevance += 6
        elif source == "hackernews":
            actionability += 4

        return {
            "technical_impact": clamp_score(technical_impact),
            "actionability": clamp_score(actionability),
            "ecosystem_relevance": clamp_score(ecosystem_relevance),
            "reasoning": f"Heuristic semantic scoring used because LLM failed: {error}",
        }
