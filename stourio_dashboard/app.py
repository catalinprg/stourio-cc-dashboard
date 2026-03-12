from __future__ import annotations
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .scanner import SessionScanner
from .config import load_settings, save_settings, MODEL_PRICING
from .parser import parse_session_events

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Stourio CC Dashboard", version="0.1.0")
scanner = SessionScanner()

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    html_file = TEMPLATES_DIR / "dashboard.html"
    return HTMLResponse(html_file.read_text())


@app.get("/api/sessions")
async def get_sessions(
    q: Optional[str] = Query(None, description="Search query"),
    project: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    sort: str = Query("newest", description="newest|oldest|tokens|duration"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    sessions = scanner.scan_all()

    # Filter
    if q:
        ql = q.lower()
        sessions = [
            s for s in sessions
            if ql in s.project.lower()
            or ql in s.branch.lower()
            or ql in s.model.lower()
            or ql in s.session_id.lower()
        ]
    if project:
        sessions = [s for s in sessions if s.project == project]
    if model:
        sessions = [s for s in sessions if model in s.model]
    if status:
        sessions = [s for s in sessions if s.status == status]

    # Sort
    sort_keys = {
        "newest": lambda s: s.started_at or s.ended_at,
        "oldest": lambda s: s.started_at or s.ended_at,
        "tokens": lambda s: s.tokens.total,
        "duration": lambda s: s.duration_seconds,
    }
    key_fn = sort_keys.get(sort, sort_keys["newest"])
    reverse = sort != "oldest"
    sessions.sort(key=lambda s: key_fn(s) or 0, reverse=reverse)

    total = len(sessions)
    page = sessions[offset : offset + limit]

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "sessions": [s.to_dict() for s in page],
    }

@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    s = scanner.get_session(session_id)
    if not s:
        return {"error": "Session not found"}
    return s.to_dict()


@app.get("/api/sessions/{session_id}/events")
async def get_session_events(session_id: str):
    s = scanner.get_session(session_id)
    if not s or not s.file_path:
        return {"error": "Session not found or file missing"}
    
    events = parse_session_events(s.file_path)
    return {"events": events}


@app.get("/api/stats")
async def get_stats():
    return scanner.get_stats()


@app.get("/api/projects")
async def get_projects():
    stats = scanner.get_stats()
    return stats["projects"]


@app.get("/api/settings")
async def get_settings():
    return {**load_settings(), "available_models": list(MODEL_PRICING.keys())}


@app.post("/api/settings")
async def update_settings(settings: dict):
    save_settings(settings)
    return {"ok": True}


@app.get("/api/health")
async def health():
    return {"status": "ok", "scanner_cache_size": len(scanner._cache)}