import os
from collections import Counter
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from dotenv import dotenv_values, load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env", override=True)
for key, value in dotenv_values(BACKEND_ROOT / ".env").items():
    if value is not None:
        os.environ[key] = value


def disable_broken_proxy_env() -> None:
    """Remove local proxy env vars that block outbound HTTP requests."""
    for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
        os.environ.pop(key, None)


disable_broken_proxy_env()

from .agents import RelevanceAgent, RiskAgent, SignalCollector, SynthesisAgent
from .adapters.arxiv import fetch_arxiv_papers
from .adapters.github import fetch_github_trending
from .adapters.hackernews import fetch_hackernews_stories
from .adapters.huggingface import fetch_huggingface_models
from .adapters.medium import fetch_medium_blogs

DEFAULT_SIGNAL_LIMIT = 2

SOURCE_LABELS = {
    "github": "GitHub",
    "arxiv": "ArXiv",
    "hackernews": "HackerNews",
    "medium": "Blogs / RSS",
    "huggingface": "HuggingFace",
}

LABEL_TO_SOURCE = {label: source for source, label in SOURCE_LABELS.items()}


def summarize_sources(signals: List[Dict[str, Any]]) -> Dict[str, int]:
    return dict(Counter(signal.get("source", "unknown") for signal in signals))


def _parse_signal_date(signal: Dict[str, Any]) -> Optional[str]:
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
    for value in candidates:
        if not value or not isinstance(value, str):
            continue
        normalized = value.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).date().isoformat()
        except ValueError:
            continue
    return None


def _recommended_action(signal: Dict[str, Any]) -> str:
    source = signal.get("source", "unknown")
    relevance = signal.get("relevance", {}).get("score", 0)
    risk_level = (signal.get("risk", {}).get("risk_level", "LOW") or "LOW").upper()

    if risk_level in ["HIGH", "CRITICAL"]:
        return "Cần review ngay với đội kỹ thuật và kiểm tra tác động migration hoặc bảo mật."
    if source == "github":
        return "Đánh giá độ trưởng thành của repo, API surface và độ phù hợp dependency trước khi áp dụng."
    if source == "arxiv":
        return "Đọc paper để chọn kỹ thuật đáng thử nghiệm ở vòng prototype tiếp theo."
    if source == "huggingface":
        return "Benchmark model này với stack hiện tại trước khi tích hợp vào production."
    if source == "hackernews":
        return "Theo dõi thảo luận cộng đồng và xác thực xem tín hiệu này có phù hợp với roadmap hay không."
    if relevance >= 70:
        return "Ưu tiên tín hiệu này cho buổi review kỹ thuật ở chu kỳ planning kế tiếp."
    return "Tiếp tục theo dõi tín hiệu này và xem lại khi có thêm cập nhật hoặc bằng chứng mạnh hơn."


def _pipeline_steps() -> List[Dict[str, str]]:
    return [
        {"key": "collect", "label": "Thu thập", "status": "pending"},
        {"key": "relevance", "label": "Liên quan", "status": "pending"},
        {"key": "risk", "label": "Rủi ro", "status": "pending"},
        {"key": "synthesis", "label": "Tổng hợp", "status": "pending"},
        {"key": "digest", "label": "Bản tóm tắt", "status": "pending"},
    ]


def _set_step_status(steps: List[Dict[str, str]], key: str, status: str) -> None:
    for step in steps:
        if step["key"] == key:
            step["status"] = status
            return


def _emit_progress(
    progress_callback: Optional[Callable[[Dict[str, Any]], None]],
    steps: List[Dict[str, str]],
    message: str,
    percent: int,
    detail: Optional[str] = None,
) -> None:
    if progress_callback:
        progress_callback(
            {
                "steps": deepcopy(steps),
                "message": message,
                "percent": max(0, min(percent, 100)),
                "detail": detail or message,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        )


def _enrich_signal(signal: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(signal)
    enriched["display_date"] = _parse_signal_date(signal)
    enriched["recommended_action"] = _recommended_action(signal)
    return enriched


def _selected_source_keys(selected_sources: Optional[List[str]]) -> List[str]:
    if not selected_sources:
        return list(SOURCE_LABELS.keys())

    normalized: List[str] = []
    for source in selected_sources:
        if source in SOURCE_LABELS:
            normalized.append(source)
        elif source in LABEL_TO_SOURCE:
            normalized.append(LABEL_TO_SOURCE[source])
    return normalized or list(SOURCE_LABELS.keys())


def collect_selected_signals(
    selected_sources: Optional[List[str]] = None,
    signal_count: int = DEFAULT_SIGNAL_LIMIT,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    steps: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, Any]]:
    source_keys = _selected_source_keys(selected_sources)
    raw_signals: List[Dict[str, Any]] = []
    total_sources = max(len(source_keys), 1)

    def mark_source_progress(index: int, label: str) -> None:
        if steps:
            base = int((index / total_sources) * 20)
            _emit_progress(
                progress_callback,
                steps,
                f"Đang thu thập dữ liệu từ {label}.",
                percent=base,
                detail=f"Collect: {label}",
            )

    source_index = 0

    if "github" in source_keys:
        source_index += 1
        mark_source_progress(source_index, "GitHub")
        raw_signals.extend(fetch_github_trending(limit=signal_count))
    if "arxiv" in source_keys:
        source_index += 1
        mark_source_progress(source_index, "ArXiv")
        raw_signals.extend(fetch_arxiv_papers(limit=min(signal_count, 3)))
    if "hackernews" in source_keys:
        source_index += 1
        mark_source_progress(source_index, "HackerNews")
        raw_signals.extend(fetch_hackernews_stories(limit=signal_count))
    if "medium" in source_keys:
        source_index += 1
        mark_source_progress(source_index, "Blogs / RSS")
        raw_signals.extend(fetch_medium_blogs(limit=min(signal_count, 3)))
    if "huggingface" in source_keys:
        source_index += 1
        mark_source_progress(source_index, "HuggingFace")
        raw_signals.extend(fetch_huggingface_models(limit=signal_count))

    return raw_signals


def _build_stats(
    normalized: List[Dict[str, Any]],
    assessed: List[Dict[str, Any]],
    digest: Dict[str, Any],
) -> Dict[str, Any]:
    source_counts = summarize_sources(normalized)
    high_relevance = sum(1 for s in assessed if s.get("relevance", {}).get("score", 0) >= 70)
    elevated_risk = sum(
        1
        for s in assessed
        if s.get("risk", {}).get("risk_level", "LOW").upper() in ["HIGH", "CRITICAL"]
    )

    return {
        "total_signals": len(normalized),
        "high_relevance": high_relevance,
        "elevated_risks": elevated_risk,
        "trending_repositories": source_counts.get("github", 0),
        "new_research_papers": source_counts.get("arxiv", 0),
        "ai_models_tracked": source_counts.get("huggingface", 0),
        "source_counts": source_counts,
        "priority_count": len(digest.get("priority_signals", [])),
    }


def run_dashboard_pipeline(
    selected_sources: Optional[List[str]] = None,
    signal_count: int = DEFAULT_SIGNAL_LIMIT,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    collector = SignalCollector()
    relevance = RelevanceAgent()
    risk = RiskAgent()
    synthesis = SynthesisAgent()
    steps = _pipeline_steps()

    _set_step_status(steps, "collect", "running")
    _emit_progress(progress_callback, steps, "Đang thu thập tín hiệu từ các nguồn đã chọn.", percent=2)
    raw_signals = collect_selected_signals(
        selected_sources=selected_sources,
        signal_count=signal_count,
        progress_callback=progress_callback,
        steps=steps,
    )
    normalized = collector.collect(raw_signals)
    _set_step_status(steps, "collect", "done")
    _emit_progress(
        progress_callback,
        steps,
        f"Đã thu thập và chuẩn hóa {len(normalized)} tín hiệu.",
        percent=20,
        detail=f"Collect done: {len(normalized)} signals",
    )

    _set_step_status(steps, "relevance", "running")
    _emit_progress(progress_callback, steps, "Đang chấm các yếu tố liên quan.", percent=24)
    scored: List[Dict[str, Any]] = []
    total_signals = max(len(normalized), 1)
    for idx, signal in enumerate(normalized, start=1):
        result = relevance.score(signal)
        scored.append({**signal, "relevance": result})
        percent = 20 + int((idx / total_signals) * 30)
        _emit_progress(
            progress_callback,
            steps,
            f"Đã chấm liên quan {idx}/{len(normalized)} tín hiệu.",
            percent=percent,
            detail=f"Relevance: {idx}/{len(normalized)}",
        )
    _set_step_status(steps, "relevance", "done")
    _emit_progress(progress_callback, steps, "Đã hoàn tất chấm điểm liên quan.", percent=50)

    _set_step_status(steps, "risk", "running")
    _emit_progress(progress_callback, steps, "Đang đánh giá các yếu tố rủi ro.", percent=54)
    assessed: List[Dict[str, Any]] = []
    for idx, signal in enumerate(scored, start=1):
        result = risk.assess(signal)
        assessed.append({**signal, "risk": result})
        percent = 50 + int((idx / total_signals) * 30)
        _emit_progress(
            progress_callback,
            steps,
            f"Đã đánh giá rủi ro {idx}/{len(scored)} tín hiệu.",
            percent=percent,
            detail=f"Risk: {idx}/{len(scored)}",
        )
    _set_step_status(steps, "risk", "done")
    _emit_progress(progress_callback, steps, "Đã hoàn tất đánh giá rủi ro.", percent=80)

    _set_step_status(steps, "synthesis", "running")
    _emit_progress(progress_callback, steps, "Đang tạo bản tổng hợp cuối.", percent=90, detail="Synthesis running")
    digest = synthesis.synthesize(assessed)
    _set_step_status(steps, "synthesis", "done")
    _set_step_status(steps, "digest", "done")
    _emit_progress(progress_callback, steps, "Đã tạo xong bản tóm tắt tình báo.", percent=100, detail="Digest ready")

    enriched_signals = [_enrich_signal(signal) for signal in assessed]
    stats = _build_stats(normalized, assessed, digest)

    return {
        "signals": enriched_signals,
        "digest": digest,
        "stats": stats,
        "pipeline_steps": steps,
        "selected_sources": _selected_source_keys(selected_sources),
        "signal_count": signal_count,
    }
