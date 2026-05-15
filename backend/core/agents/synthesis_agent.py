"""
Synthesis Agent — Produces final intelligence digest.

Combines relevance scores, risk assessments, and source metadata into
a concise, actionable intelligence digest.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat

logger = logging.getLogger("devpulse.synthesis_agent")

DEFAULT_MODEL = os.environ.get("MODEL_SYNTHESIS", "gpt-4.1")


class SynthesisAgent:
    """
    Agent that synthesizes all signal intelligence into a final digest.

    Responsibilities:
    - Combine relevance and risk assessments
    - Prioritize signals by importance
    - Generate executive summary
    - Produce actionable recommendations
    """

    def __init__(self, model_id: Optional[str] = None):
        self.model_id = model_id or DEFAULT_MODEL

        self.agent = Agent(
            name="Intelligence Synthesizer",
            model=OpenAIChat(id=self.model_id),
            role="Synthesizes technical signals into actionable intelligence digests",
            instructions=[
                "Synthesize technical signals for AI/ML developers.",
                "Prioritize high relevance and high risk signals.",
                "Identify cross-source patterns.",
                "Produce concise, actionable recommendations.",
                "Return only valid JSON.",
            ],
            markdown=False,
        )

    def synthesize(self, signals: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Synthesize signals into a final intelligence digest.

        Deterministic logic handles sorting and grouping.
        LLM handles summary and recommendations when available.
        """
        prioritized = self._prioritize_signals(signals)
        grouped = self._group_by_source(prioritized)

        if not prioritized:
            return self._empty_digest()

        if not os.getenv("OPENAI_API_KEY"):
            summary = self._fallback_summary(prioritized)
            recommendations = self._fallback_recommendations(prioritized)
        else:
            llm_digest = self._generate_llm_digest(prioritized)
            summary = llm_digest.get(
                "executive_summary",
                self._fallback_summary(prioritized),
            )
            recommendations = llm_digest.get(
                "recommendations",
                self._fallback_recommendations(prioritized),
            )

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_signals": len(signals),
            "executive_summary": summary,
            "priority_signals": prioritized[:5],
            "signals_by_source": grouped,
            "recommendations": recommendations,
        }

    def _empty_digest(self) -> Dict[str, Any]:
        """Return a stable empty digest."""
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_signals": 0,
            "executive_summary": "No signals to summarize.",
            "priority_signals": [],
            "signals_by_source": {},
            "recommendations": ["No urgent actions required."],
        }

    def _prioritize_signals(
        self,
        signals: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Sort signals by combined relevance and risk score."""

        def priority_score(signal: Dict[str, Any]) -> float:
            relevance = signal.get("relevance", {}).get("score", 50)
            risk_score = signal.get("risk", {}).get("risk_score", 0)

            try:
                relevance_score = float(relevance)
            except (TypeError, ValueError):
                relevance_score = 50.0

            try:
                risk_numeric = float(risk_score)
            except (TypeError, ValueError):
                risk_numeric = 0.0

            return 0.65 * relevance_score + 0.35 * risk_numeric

        return sorted(
            signals,
            key=priority_score,
            reverse=True,
        )

    def _group_by_source(
        self,
        signals: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Group signals by source."""
        grouped: Dict[str, List[Dict[str, Any]]] = {}

        for signal in signals:
            source = signal.get("source", "unknown")
            grouped.setdefault(source, []).append(signal)

        return grouped

    def _build_prompt(
        self,
        signals: List[Dict[str, Any]],
    ) -> str:
        """Build LLM synthesis prompt."""
        compact_signals = []

        for signal in signals[:10]:
            compact_signals.append(
                {
                    "source": signal.get("source"),
                    "title": signal.get("title"),
                    "url": signal.get("url"),
                    "relevance": signal.get("relevance"),
                    "risk": signal.get("risk"),
                    "metadata": signal.get("metadata", {}),
                }
            )

        return f"""
Create an actionable intelligence digest for AI/ML developers.

You are given prioritized technical signals from GitHub, ArXiv,
HackerNews, HuggingFace, and other sources.

Focus on:
- What matters most
- Why it matters
- Risks developers should watch
- Concrete next actions
- Cross-source patterns

Signals JSON:
{json.dumps(compact_signals, ensure_ascii=False, indent=2)}

Return ONLY valid JSON in this exact shape:
{{
  "executive_summary": "Concise 3-5 sentence summary.",
  "recommendations": [
    "Concrete action 1",
    "Concrete action 2",
    "Concrete action 3"
  ]
}}
""".strip()

    def _generate_llm_digest(
        self,
        signals: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Generate summary and recommendations with LLM."""
        prompt = self._build_prompt(signals)

        try:
            response = self.agent.run(prompt, stream=False)
            content = getattr(response, "content", "")
            return self._parse_llm_digest(content)
        except Exception as exc:
            logger.warning("LLM synthesis failed: %s", exc)
            return {
                "executive_summary": self._fallback_summary(signals),
                "recommendations": self._fallback_recommendations(signals),
            }

    def _parse_llm_digest(self, content: str) -> Dict[str, Any]:
        """Parse LLM JSON digest."""
        try:
            text = self._extract_json(content)
            parsed = json.loads(text)

            executive_summary = str(
                parsed.get("executive_summary", "")
            ).strip()

            recommendations_raw = parsed.get("recommendations", [])
            if isinstance(recommendations_raw, str):
                recommendations = [recommendations_raw]
            elif isinstance(recommendations_raw, list):
                recommendations = [
                    str(item).strip()
                    for item in recommendations_raw
                    if str(item).strip()
                ]
            else:
                recommendations = []

            return {
                "executive_summary": executive_summary,
                "recommendations": recommendations,
            }
        except Exception as exc:
            logger.warning("Failed to parse synthesis response: %s", exc)
            return {}

    def _extract_json(self, content: str) -> str:
        """Extract JSON object from raw LLM output."""
        text = (content or "").strip()

        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text).strip()
            text = re.sub(r"```$", "", text).strip()

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("No JSON object found in model response")

        return match.group(0)

    def _fallback_summary(
        self,
        signals: List[Dict[str, Any]],
    ) -> str:
        """Generate deterministic summary when LLM is unavailable."""
        high_priority = [
            s
            for s in signals
            if self._safe_relevance_score(s) >= 70
        ]

        elevated_risks = [
            s
            for s in signals
            if (
                s.get("risk", {}).get("risk_level", "LOW").upper()
                in ["HIGH", "CRITICAL"]
            )
        ]

        top_signal = signals[0].get("title", "Unknown")

        parts = [
            f"Analyzed {len(signals)} technical signals.",
            f"{len(high_priority)} high-relevance items were detected.",
        ]

        if elevated_risks:
            parts.append(
                f"{len(elevated_risks)} signals have elevated risk and may require review."
            )

        parts.append(f"Top priority signal: {top_signal}.")
        return " ".join(parts)

    def _fallback_recommendations(
        self,
        signals: List[Dict[str, Any]],
    ) -> List[str]:
        """Generate deterministic recommendations."""
        recommendations: List[str] = []

        critical = [
            s
            for s in signals
            if s.get("risk", {}).get("risk_level", "LOW").upper()
            == "CRITICAL"
        ]

        high_risk = [
            s
            for s in signals
            if s.get("risk", {}).get("risk_level", "LOW").upper()
            == "HIGH"
        ]

        high_relevance = [
            s
            for s in signals
            if self._safe_relevance_score(s) >= 80
        ]

        if critical:
            recommendations.append(
                f"Review {len(critical)} critical-risk signal(s) immediately."
            )

        if high_risk:
            recommendations.append(
                f"Investigate {len(high_risk)} high-risk signal(s) for security or migration impact."
            )

        if high_relevance:
            recommendations.append(
                f"Prioritize {len(high_relevance)} highly relevant signal(s) for engineering review."
            )

        github = [s for s in signals if s.get("source") == "github"]
        arxiv = [s for s in signals if s.get("source") == "arxiv"]
        huggingface = [s for s in signals if s.get("source") == "huggingface"]

        if github:
            recommendations.append(
                f"Evaluate {len(github)} GitHub repos for adoption potential or dependency risk."
            )

        if arxiv:
            recommendations.append(
                f"Review {len(arxiv)} ArXiv paper(s) for emerging techniques worth tracking."
            )

        if huggingface:
            recommendations.append(
                f"Inspect {len(huggingface)} HuggingFace model(s) for practical integration opportunities."
            )

        if not recommendations:
            recommendations.append("No urgent actions required.")

        return recommendations

    def _safe_relevance_score(
        self,
        signal: Dict[str, Any],
    ) -> float:
        """Safely read relevance score."""
        value = signal.get("relevance", {}).get("score", 0)

        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
