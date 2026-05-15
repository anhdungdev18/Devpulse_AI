import os
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import dotenv_values, load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    from .core.dashboard_service import SOURCE_LABELS, run_dashboard_pipeline
except ImportError:
    from core.dashboard_service import SOURCE_LABELS, run_dashboard_pipeline

BACKEND_ROOT = Path(__file__).resolve().parent
load_dotenv(BACKEND_ROOT / ".env", override=True)
for key, value in dotenv_values(BACKEND_ROOT / ".env").items():
    if value is not None:
        os.environ[key] = value

app = FastAPI(title="DevPulseAI Backend", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

JOBS: Dict[str, Dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
SIGNAL_COUNT_OPTIONS = [1, 2, 4, 8, 12, 16, 24, 32]


class AnalyzeRequest(BaseModel):
    sources: List[str] = Field(default_factory=lambda: list(SOURCE_LABELS.keys()))
    signal_count: int = Field(default=2, ge=1, le=32)


def _default_steps() -> List[Dict[str, str]]:
    return [
        {"key": "collect", "label": "Thu thập", "status": "pending"},
        {"key": "relevance", "label": "Liên quan", "status": "pending"},
        {"key": "risk", "label": "Rủi ro", "status": "pending"},
        {"key": "synthesis", "label": "Tổng hợp", "status": "pending"},
        {"key": "digest", "label": "Bản tóm tắt", "status": "pending"},
    ]


def _update_job(job_id: str, **fields: Any) -> None:
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(fields)


def _run_job(job_id: str, sources: List[str], signal_count: int) -> None:
    def progress_callback(event: Dict[str, Any]) -> None:
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                return
            logs = job.get("progress_logs", [])
            logs.append(
                {
                    "message": event.get("message"),
                    "detail": event.get("detail"),
                    "percent": event.get("percent", 0),
                    "timestamp": event.get("timestamp"),
                }
            )
            JOBS[job_id]["progress_logs"] = logs[-40:]
            JOBS[job_id]["status"] = "running"
            JOBS[job_id]["pipeline_steps"] = event.get("steps", job.get("pipeline_steps", _default_steps()))
            JOBS[job_id]["message"] = event.get("message", job.get("message"))
            JOBS[job_id]["progress_percent"] = event.get("percent", job.get("progress_percent", 0))

    try:
        result = run_dashboard_pipeline(
            selected_sources=sources,
            signal_count=signal_count,
            progress_callback=progress_callback,
        )
        _update_job(
            job_id,
            status="done",
            pipeline_steps=result.get("pipeline_steps", _default_steps()),
            message="Pipeline đã hoàn tất thành công.",
            progress_percent=100,
            result=result,
        )
    except Exception as exc:
        with JOBS_LOCK:
            job_state = JOBS.get(job_id, {})
            failed_steps = job_state.get("pipeline_steps", _default_steps())
            current_percent = job_state.get("progress_percent", 0)
        for step in reversed(failed_steps):
            if step["status"] == "running":
                step["status"] = "failed"
                break
        _update_job(
            job_id,
            status="failed",
            pipeline_steps=failed_steps,
            message=f"Pipeline lỗi: {exc}",
            progress_percent=current_percent,
            error=str(exc),
        )


def _create_job(sources: List[str], signal_count: int) -> str:
    job_id = str(uuid.uuid4())
    with JOBS_LOCK:
        JOBS[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "message": "Tác vụ đã được đưa vào hàng đợi.",
            "pipeline_steps": _default_steps(),
            "progress_percent": 0,
            "progress_logs": [],
            "result": None,
            "error": None,
        }
    thread = threading.Thread(target=_run_job, args=(job_id, sources, signal_count), daemon=True)
    thread.start()
    return job_id


@app.get("/api/health")
def health_check() -> dict:
    return {"status": "ok", "openai_configured": bool(os.environ.get("OPENAI_API_KEY"))}


@app.get("/api/config")
def app_config() -> dict:
    return {
        "sources": [{"key": key, "label": label} for key, label in SOURCE_LABELS.items()],
        "default_signal_count": 2,
        "signal_count_options": SIGNAL_COUNT_OPTIONS,
        "openai_configured": bool(os.environ.get("OPENAI_API_KEY")),
    }


@app.get("/api/analyze")
def analyze_get(
    sources: Optional[List[str]] = Query(default=None),
    signal_count: int = Query(default=2, ge=1, le=32),
) -> dict:
    return run_dashboard_pipeline(selected_sources=sources, signal_count=signal_count)


@app.post("/api/analyze")
def analyze_post(payload: AnalyzeRequest) -> dict:
    return run_dashboard_pipeline(selected_sources=payload.sources, signal_count=payload.signal_count)


@app.post("/api/run")
def run_pipeline_job(payload: AnalyzeRequest) -> dict:
    job_id = _create_job(payload.sources, payload.signal_count)
    return {"job_id": job_id}


@app.get("/api/job/{job_id}")
def get_job(job_id: str) -> dict:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return {"job_id": job_id, "status": "missing", "message": "Không tìm thấy tác vụ."}
    return job
