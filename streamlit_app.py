import os
from collections import Counter
from typing import Any, Dict, List

import streamlit as st
from dotenv import load_dotenv

load_dotenv()


def disable_broken_proxy_env() -> None:
    """Remove local proxy env vars that block outbound HTTP requests."""
    for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
        os.environ.pop(key, None)


disable_broken_proxy_env()

from main import DEFAULT_SIGNAL_LIMIT
from agents import SignalCollector, RelevanceAgent, RiskAgent, SynthesisAgent

st.set_page_config(
    page_title="DevPulseAI | Bảng tin tín hiệu AI",
    page_icon="🧠",
    layout="wide",
)

st.markdown(
    """
<style>
    :root {
        --bg: #f4efe5;
        --paper: rgba(255, 252, 247, 0.92);
        --ink: #1f2937;
        --muted: #6b7280;
        --line: rgba(120, 98, 73, 0.18);
        --accent: #0f766e;
        --accent-2: #b45309;
        --danger: #b91c1c;
        --success: #166534;
        --shadow: 0 20px 50px rgba(84, 61, 42, 0.12);
    }

    .stApp {
        background:
            radial-gradient(circle at top left, rgba(15, 118, 110, 0.14), transparent 28%),
            radial-gradient(circle at top right, rgba(180, 83, 9, 0.12), transparent 24%),
            linear-gradient(180deg, #f7f3eb 0%, #efe7db 100%);
        color: var(--ink);
    }

    .block-container {
        padding-top: 2rem;
        padding-bottom: 3rem;
        max-width: 1280px;
    }

    .hero {
        background: linear-gradient(135deg, rgba(255,255,255,0.92), rgba(248,242,233,0.96));
        border: 1px solid var(--line);
        border-radius: 28px;
        padding: 28px 30px;
        box-shadow: var(--shadow);
        margin-bottom: 1rem;
    }

    .hero-title {
        font-size: 2.2rem;
        line-height: 1.1;
        font-weight: 800;
        color: #16302b;
        margin-bottom: 0.4rem;
    }

    .hero-text {
        color: var(--muted);
        font-size: 1rem;
        line-height: 1.7;
        max-width: 920px;
    }

    .panel {
        background: var(--paper);
        border: 1px solid var(--line);
        border-radius: 24px;
        padding: 20px 22px;
        box-shadow: var(--shadow);
    }

    .metric-card {
        background: linear-gradient(180deg, rgba(255,255,255,0.94), rgba(248,244,238,0.92));
        border: 1px solid var(--line);
        border-radius: 22px;
        padding: 18px 18px 14px 18px;
        box-shadow: 0 10px 30px rgba(84, 61, 42, 0.08);
    }

    .metric-label {
        color: var(--muted);
        font-size: 0.85rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }

    .metric-value {
        color: #17212b;
        font-size: 2rem;
        line-height: 1.15;
        font-weight: 800;
        margin-top: 0.35rem;
    }

    .metric-note {
        color: var(--muted);
        font-size: 0.92rem;
        margin-top: 0.4rem;
    }

    .section-title {
        font-size: 1.15rem;
        font-weight: 800;
        color: #23323a;
        margin-bottom: 0.9rem;
    }

    .summary-box {
        background: linear-gradient(135deg, rgba(15,118,110,0.08), rgba(255,255,255,0.95));
        border: 1px solid rgba(15, 118, 110, 0.18);
        border-radius: 20px;
        padding: 18px 18px;
        color: #1f2937;
        line-height: 1.75;
    }

    .rec-card {
        border-left: 4px solid var(--accent);
        background: rgba(255,255,255,0.78);
        border-radius: 14px;
        padding: 12px 14px;
        margin-bottom: 10px;
        color: #26323a;
    }

    .source-pill {
        display: inline-block;
        padding: 5px 10px;
        border-radius: 999px;
        background: rgba(15,118,110,0.1);
        color: #115e59;
        font-size: 0.8rem;
        font-weight: 700;
        margin: 4px 8px 0 0;
    }

    .signal-meta {
        color: var(--muted);
        font-size: 0.92rem;
        margin-top: 0.4rem;
    }

    .score-chip, .risk-chip {
        display: inline-block;
        padding: 6px 10px;
        border-radius: 999px;
        font-size: 0.8rem;
        font-weight: 700;
        margin-right: 8px;
        margin-bottom: 8px;
    }

    .score-chip {
        background: rgba(15,118,110,0.12);
        color: #115e59;
    }

    .risk-low { background: rgba(22, 101, 52, 0.12); color: #166534; }
    .risk-medium { background: rgba(180, 83, 9, 0.14); color: #b45309; }
    .risk-high { background: rgba(185, 28, 28, 0.12); color: #b91c1c; }
    .risk-critical { background: rgba(127, 29, 29, 0.14); color: #7f1d1d; }

    .tiny {
        color: var(--muted);
        font-size: 0.88rem;
    }

    div[data-testid="stSidebar"] {
        background: linear-gradient(180deg, rgba(250,247,241,0.98), rgba(241,233,220,0.98));
        border-right: 1px solid var(--line);
    }
</style>
""",
    unsafe_allow_html=True,
)


def render_metric(label: str, value: str, note: str) -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def risk_chip(level: str) -> str:
    normalized = (level or "LOW").lower()
    return f'<span class="risk-chip risk-{normalized}">Rủi ro: {(level or "LOW").upper()}</span>'


def score_chip(score: Any) -> str:
    return f'<span class="score-chip">Điểm liên quan: {score}</span>'


def summarize_sources(signals: List[Dict[str, Any]]) -> Dict[str, int]:
    return dict(Counter(signal.get("source", "unknown") for signal in signals))


def format_source_name(source: str) -> str:
    mapping = {
        "github": "GitHub",
        "arxiv": "ArXiv",
        "hackernews": "HackerNews",
        "medium": "Blogs / RSS",
        "huggingface": "HuggingFace",
    }
    return mapping.get(source, source.title())


def run_selected_pipeline(selected_sources: List[str], signal_count: int) -> Dict[str, Any]:
    collector = SignalCollector()
    relevance = RelevanceAgent()
    risk = RiskAgent()
    synthesis = SynthesisAgent()

    raw_signals: List[Dict[str, Any]] = []
    source_map = summarize_sources([])

    from adapters.github import fetch_github_trending
    from adapters.arxiv import fetch_arxiv_papers
    from adapters.hackernews import fetch_hackernews_stories
    from adapters.medium import fetch_medium_blogs
    from adapters.huggingface import fetch_huggingface_models

    with st.status("Đang thu thập tín hiệu từ các nguồn...", expanded=True) as status:
        if "GitHub" in selected_sources:
            st.write("Đang lấy repo nổi bật từ GitHub...")
            raw_signals.extend(fetch_github_trending(limit=signal_count))
        if "ArXiv" in selected_sources:
            st.write("Đang lấy bài nghiên cứu mới từ ArXiv...")
            raw_signals.extend(fetch_arxiv_papers(limit=min(signal_count, 3)))
        if "HackerNews" in selected_sources:
            st.write("Đang lấy bài viết từ HackerNews...")
            raw_signals.extend(fetch_hackernews_stories(limit=signal_count))
        if "Blogs / RSS" in selected_sources:
            st.write("Đang lấy bài viết từ các blog kỹ thuật...")
            raw_signals.extend(fetch_medium_blogs(limit=min(signal_count, 3)))
        if "HuggingFace" in selected_sources:
            st.write("Đang lấy model nổi bật từ HuggingFace...")
            raw_signals.extend(fetch_huggingface_models(limit=signal_count))

        normalized = collector.collect(raw_signals)
        source_map = summarize_sources(normalized)
        status.update(
            label=f"Đã chuẩn hóa {len(normalized)} tín hiệu từ {len(source_map)} nguồn",
            state="complete",
        )

    col_a, col_b = st.columns(2)
    with col_a:
        with st.status("Đang chấm mức độ liên quan...", expanded=False) as status:
            scored = relevance.score_batch(normalized)
            status.update(label="Đã chấm xong mức độ liên quan", state="complete")

    with col_b:
        with st.status("Đang đánh giá rủi ro...", expanded=False) as status:
            assessed = risk.assess_batch(scored)
            status.update(label="Đã đánh giá xong rủi ro", state="complete")

    with st.status("Đang tạo bản tổng hợp cuối...", expanded=False) as status:
        digest = synthesis.synthesize(assessed)
        status.update(label="Đã tạo xong bản tổng hợp", state="complete")

    high_relevance = sum(1 for s in assessed if s.get("relevance", {}).get("score", 0) >= 70)
    elevated_risk = sum(
        1 for s in assessed if s.get("risk", {}).get("risk_level", "LOW").upper() in ["HIGH", "CRITICAL"]
    )

    return {
        "raw_signals": raw_signals,
        "normalized": normalized,
        "assessed": assessed,
        "digest": digest,
        "high_relevance": high_relevance,
        "elevated_risk": elevated_risk,
        "source_map": source_map,
    }


st.markdown(
    """
    <div class="hero">
        <div class="hero-title">DevPulseAI</div>
        <div class="hero-text">
            Bảng tin tín hiệu AI/ML dành cho developer. Ứng dụng này tự động thu thập dữ liệu từ nhiều nguồn,
            chấm mức độ quan trọng, đánh giá rủi ro, rồi tạo ra một bản tổng hợp hành động bằng tiếng Việt dễ đọc hơn.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("## Cấu hình")
    env_api_key = os.environ.get("OPENAI_API_KEY", "")
    api_key = st.text_input(
        "OpenAI API Key",
        value=env_api_key,
        type="password",
        help="Ứng dụng sẽ tự đọc OPENAI_API_KEY từ file .env. Bạn cũng có thể ghi đè tạm thời tại đây.",
    )
    if api_key:
        os.environ["OPENAI_API_KEY"] = api_key

    sources = st.multiselect(
        "Nguồn dữ liệu",
        ["GitHub", "ArXiv", "HackerNews", "Blogs / RSS", "HuggingFace"],
        default=["GitHub", "ArXiv", "HackerNews", "Blogs / RSS", "HuggingFace"],
    )

    signal_count = st.slider(
        "Số lượng tín hiệu mỗi nguồn",
        min_value=4,
        max_value=32,
        value=DEFAULT_SIGNAL_LIMIT,
        step=4,
    )

    run_button = st.button("Chạy phân tích", use_container_width=True, type="primary")

    st.markdown("---")
    st.markdown(
        """
        <div class="tiny">
        Quy trình gồm 4 bước:
        <br>1. Thu thập tín hiệu
        <br>2. Chấm mức độ liên quan
        <br>3. Đánh giá rủi ro
        <br>4. Tổng hợp hành động
        </div>
        """,
        unsafe_allow_html=True,
    )

if run_button:
    if not sources:
        st.warning("Bạn cần chọn ít nhất một nguồn dữ liệu.")
    else:
        results = run_selected_pipeline(sources, signal_count)
        digest = results["digest"]
        assessed = results["assessed"]
        source_map = results["source_map"]

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            render_metric("Tổng tín hiệu", str(digest["total_signals"]), "Số tín hiệu đã qua chuẩn hóa")
        with c2:
            render_metric("Liên quan cao", str(results["high_relevance"]), "Các tín hiệu có điểm từ 70 trở lên")
        with c3:
            render_metric("Rủi ro cao", str(results["elevated_risk"]), "Mức HIGH hoặc CRITICAL")
        with c4:
            render_metric("Nguồn đang dùng", str(len(source_map)), "Số nguồn có dữ liệu thực tế")

        st.markdown("")
        left, right = st.columns([1.35, 1])

        with left:
            st.markdown('<div class="panel">', unsafe_allow_html=True)
            st.markdown('<div class="section-title">Tóm tắt điều hành</div>', unsafe_allow_html=True)
            st.markdown(
                f'<div class="summary-box">{digest["executive_summary"]}</div>',
                unsafe_allow_html=True,
            )
            st.markdown("</div>", unsafe_allow_html=True)

            st.markdown("")
            st.markdown('<div class="panel">', unsafe_allow_html=True)
            st.markdown('<div class="section-title">Tín hiệu ưu tiên</div>', unsafe_allow_html=True)
            for idx, signal in enumerate(digest.get("priority_signals", []), start=1):
                rel = signal.get("relevance", {})
                risk = signal.get("risk", {})
                st.markdown(
                    f"""
                    <div class="rec-card">
                        <strong>{idx}. {signal.get("title", "Untitled")}</strong><br>
                        <span class="source-pill">{format_source_name(signal.get("source", "unknown"))}</span>
                        {score_chip(rel.get("score", 0))}
                        {risk_chip(risk.get("risk_level", "LOW"))}
                        <div class="signal-meta">{signal.get("url", "")}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            st.markdown("</div>", unsafe_allow_html=True)

        with right:
            st.markdown('<div class="panel">', unsafe_allow_html=True)
            st.markdown('<div class="section-title">Khuyến nghị hành động</div>', unsafe_allow_html=True)
            for recommendation in digest.get("recommendations", []):
                st.markdown(f'<div class="rec-card">{recommendation}</div>', unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

            st.markdown("")
            st.markdown('<div class="panel">', unsafe_allow_html=True)
            st.markdown('<div class="section-title">Phân bổ theo nguồn</div>', unsafe_allow_html=True)
            for source, count in source_map.items():
                st.markdown(
                    f'<div class="rec-card"><strong>{format_source_name(source)}</strong>: {count} tín hiệu</div>',
                    unsafe_allow_html=True,
                )
            st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("")
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Chi tiết tín hiệu đã phân tích</div>', unsafe_allow_html=True)

        for signal in assessed:
            rel = signal.get("relevance", {})
            risk = signal.get("risk", {})
            concerns = risk.get("concerns", [])
            with st.expander(f"[{format_source_name(signal.get('source', 'unknown'))}] {signal.get('title', 'Untitled')}"):
                col_left, col_right = st.columns([1.6, 1])
                with col_left:
                    st.markdown(f"**Mô tả:** {signal.get('description', 'Không có mô tả')}")
                    st.markdown(f"**Liên kết:** [{signal.get('url', '')}]({signal.get('url', '')})")
                    if rel.get("reasoning"):
                        st.markdown(f"**Lý do chấm điểm:** {rel.get('reasoning')}")
                    if concerns:
                        st.markdown("**Điểm cần chú ý:**")
                        for concern in concerns:
                            st.write(f"- {concern}")
                with col_right:
                    st.markdown(
                        f"""
                        {score_chip(rel.get("score", 0))}
                        {risk_chip(risk.get("risk_level", "LOW"))}
                        """,
                        unsafe_allow_html=True,
                    )
                    metadata = signal.get("metadata", {})
                    if metadata:
                        st.markdown("**Metadata chính:**")
                        for key in list(metadata.keys())[:6]:
                            st.write(f"- `{key}`: {metadata.get(key)}")
        st.markdown("</div>", unsafe_allow_html=True)

else:
    top_left, top_right = st.columns([1.3, 1])
    with top_left:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Ứng dụng này làm gì?</div>', unsafe_allow_html=True)
        st.markdown(
            """
            DevPulseAI tự động thu thập tín hiệu kỹ thuật từ nhiều nguồn như GitHub, ArXiv, HackerNews,
            blog kỹ thuật và HuggingFace. Sau đó hệ thống:

            1. Chuẩn hóa dữ liệu về cùng một schema
            2. Dùng agent để chấm mức độ quan trọng
            3. Dùng agent để đánh giá rủi ro
            4. Dùng agent để tạo bản tổng hợp cuối cùng
            """
        )
        st.markdown("</div>", unsafe_allow_html=True)
    with top_right:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Gợi ý sử dụng</div>', unsafe_allow_html=True)
        st.markdown(
            """
            - Chọn nguồn dữ liệu ở thanh bên trái
            - Giữ `OpenAI API Key` trong file `.env` hoặc nhập trực tiếp
            - Bấm **Chạy phân tích**
            - Xem tóm tắt, tín hiệu ưu tiên và khuyến nghị hành động
            """
        )
        st.markdown("</div>", unsafe_allow_html=True)
