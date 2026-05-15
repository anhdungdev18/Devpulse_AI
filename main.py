"""
DevPulseAI — Multi-Agent Signal Intelligence Pipeline

Demonstrates a production-style multi-agent workflow that aggregates
technical signals from multiple sources, scores them for relevance,
assesses risks, and synthesizes an actionable intelligence digest.

Architecture:
    Adapters (fetch) → SignalCollector (normalize) → RelevanceAgent (score)
    → RiskAgent (assess) → SynthesisAgent (digest)

Design Decisions:
    - Signal collection is a utility, not an agent (deterministic work).
    - Agents are used only where reasoning is required.
    - Single provider (OpenAI) by default to reduce onboarding friction.
    - Models are chosen by role: fast for classification, strong for synthesis.

Usage:
    export OPENAI_API_KEY=sk-...
    python main.py

    Without API key: agents fall back to heuristic scoring.
"""

import os
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()


def disable_broken_proxy_env() -> None:
    """Remove local proxy env vars that block outbound HTTP requests."""
    for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
        os.environ.pop(key, None)


disable_broken_proxy_env()

# Reduced default signal count for faster demo execution
DEFAULT_SIGNAL_LIMIT = 5

# Import adapters
from adapters.github import fetch_github_trending
from adapters.arxiv import fetch_arxiv_papers
from adapters.hackernews import fetch_hackernews_stories
from adapters.medium import fetch_medium_blogs
from adapters.huggingface import fetch_huggingface_models

# Import pipeline components
from agents import (
    SignalCollector,  # Utility — no LLM
    RelevanceAgent,   # Agent — gpt-4.1-mini
    RiskAgent,        # Agent — gpt-4.1-mini
    SynthesisAgent,   # Agent — gpt-4.1
)


def collect_signals(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Collect signals from all configured sources.

    This is pure data aggregation — no LLM involved.
    """
    fetch_limit = limit if limit is not None else DEFAULT_SIGNAL_LIMIT
    print(f"\n📡 [1/4] Collecting Signals (limit: {fetch_limit} per source)...")

    signals = []

    print("  → Fetching GitHub trending repos...")
    signals.extend(fetch_github_trending(limit=fetch_limit))

    print("  → Fetching ArXiv papers...")
    signals.extend(fetch_arxiv_papers(limit=min(fetch_limit, 3)))

    print("  → Fetching HackerNews stories...")
    signals.extend(fetch_hackernews_stories(limit=fetch_limit))

    print("  → Fetching Medium blogs...")
    signals.extend(fetch_medium_blogs(limit=min(fetch_limit, 3)))

    print("  → Fetching HuggingFace models...")
    signals.extend(fetch_huggingface_models(limit=fetch_limit))

    print(f"  ✓ Collected {len(signals)} raw signals")
    return signals


def run_pipeline():
    """
    Execute the full signal intelligence pipeline.

    Pipeline stages:
    1. Signal Collection — Aggregate from sources (utility, no LLM)
    2. Normalization    — Deduplicate and normalize (utility, no LLM)
    3. Relevance Score  — Rate signals 0-100 (agent, gpt-4.1-mini)
    4. Risk Assessment  — Identify risks (agent, gpt-4.1-mini)
    5. Synthesis        — Produce digest (agent, gpt-4.1)
    """
    print("=" * 60)
    print("🧠 DevPulseAI — Signal Intelligence Pipeline")
    print("=" * 60)

    # Check for API key
    if not os.environ.get("OPENAI_API_KEY"):
        print("\n⚠️  Warning: OPENAI_API_KEY not set.")
        print("   Agents will use fallback heuristics.\n")

    # Stage 1: Collect raw signals from adapters
    raw_signals = collect_signals()

    # Stage 2: Normalize and deduplicate (utility — no LLM)
    collector = SignalCollector()
    print("\n🔄 [2/4] Normalizing Signals...")
    normalized = collector.collect(raw_signals)
    print(f"  ✓ {collector.summarize_collection(normalized)}")

    # Stage 3: Score for relevance (agent — gpt-4.1-mini)
    relevance = RelevanceAgent()
    print("\n📊 [3/4] Scoring Relevance...")
    scored = relevance.score_batch(normalized)
    high_relevance = sum(
        1 for s in scored if s.get("relevance", {}).get("score", 0) >= 70
    )
    print(f"  ✓ {high_relevance}/{len(scored)} signals rated high-relevance")

    # Stage 4: Assess risks (agent — gpt-4.1-mini)
    risk = RiskAgent()
    print("\n⚠️  [4/4] Assessing Risks...")
    assessed = risk.assess_batch(scored)
    critical = sum(
        1
        for s in assessed
        if s.get("risk", {}).get("risk_level") in ["HIGH", "CRITICAL"]
    )
    print(f"  ✓ {critical}/{len(assessed)} signals with elevated risk")

    # Stage 5: Synthesize digest (agent — gpt-4.1)
    synthesis = SynthesisAgent()
    print("\n📋 Generating Intelligence Digest...")
    digest = synthesis.synthesize(assessed)

    # Output results
    print("\n" + "=" * 60)
    print("📄 INTELLIGENCE DIGEST")
    print("=" * 60)
    print(f"\n🕐 Generated: {digest['generated_at']}")
    print(f"📦 Total Signals: {digest['total_signals']}")
    print(f"\n📝 Summary: {digest['executive_summary']}")

    print("\n🎯 Top Priority Signals:")
    for i, signal in enumerate(digest.get("priority_signals", [])[:3], 1):
        score = signal.get("relevance", {}).get("score", "?")
        risk_level = signal.get("risk", {}).get("risk_level", "?")
        print(f"   {i}. [{signal['source']}] {signal['title'][:50]}...")
        print(f"      Relevance: {score} | Risk: {risk_level}")

    print("\n💡 Recommendations:")
    for rec in digest.get("recommendations", []):
        print(f"   • {rec}")

    print("\n" + "=" * 60)
    print("✅ Pipeline completed successfully!")
    print("=" * 60)

    return digest


if __name__ == "__main__":
    run_pipeline()
