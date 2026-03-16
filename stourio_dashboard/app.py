from __future__ import annotations
import asyncio
import csv
import io
import json
from pathlib import Path
from typing import Optional

from collections import defaultdict

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .scanner import SessionScanner
from .config import load_settings, save_settings, MODEL_PRICING, DASHBOARD_DIR
from .parser import parse_session_events
from .resources import get_all_resources

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
NOTES_FILE = DASHBOARD_DIR / "session_notes.json"

app = FastAPI(title="Stourio CC Dashboard", version="0.1.0")
scanner = SessionScanner()

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    html_file = TEMPLATES_DIR / "dashboard.html"
    return HTMLResponse(html_file.read_text())


@app.get("/api/sessions/export.csv")
async def export_sessions_csv(
    q: Optional[str] = Query(None),
    project: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
):
    all_sessions = scanner.scan_all()
    sessions = [s for s in all_sessions if not s.is_subagent]
    if q:
        ql = q.lower()
        sessions = [s for s in sessions if ql in s.project.lower() or ql in s.session_id.lower()]
    if project:
        sessions = [s for s in sessions if s.project == project]
    if status:
        sessions = [s for s in sessions if s.status == status]

    output = io.StringIO()
    fieldnames = [
        "session_id", "project", "branch", "model", "status",
        "started_at", "ended_at", "duration_seconds", "message_count",
        "total_tokens", "total_cost", "tool_calls", "tool_errors", "cache_hit_ratio",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for s in sessions:
        writer.writerow({
            "session_id": s.session_id,
            "project": s.project,
            "branch": s.branch,
            "model": s.model,
            "status": s.status,
            "started_at": s.started_at.isoformat() if s.started_at else "",
            "ended_at": s.ended_at.isoformat() if s.ended_at else "",
            "duration_seconds": round(s.duration_seconds, 1),
            "message_count": s.message_count,
            "total_tokens": s.tokens.total,
            "total_cost": round(s.cost.total, 6),
            "tool_calls": len(s.tool_calls),
            "tool_errors": s.tool_error_count,
            "cache_hit_ratio": s.cache_hit_ratio,
        })
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sessions.csv"},
    )


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
    all_sessions = scanner.scan_all()
    sessions = list(all_sessions)

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

    # Build subagent cost map from all sessions (one scan, no double call)
    subagent_cost_map: dict[str, float] = defaultdict(float)
    for s in all_sessions:
        if s.is_subagent and s.parent_session_id:
            subagent_cost_map[s.parent_session_id] += s.cost.total

    total = len(sessions)
    page = sessions[offset: offset + limit]

    def enrich(s):
        d = s.to_dict()
        d["subagent_cost"] = round(subagent_cost_map.get(s.session_id, 0.0), 4)
        return d

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "sessions": [enrich(s) for s in page],
    }


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    s = scanner.get_session(session_id)
    if not s:
        return {"error": "Session not found"}
    all_sessions = scanner.scan_all()
    subagent_cost = sum(
        x.cost.total for x in all_sessions
        if x.is_subagent and x.parent_session_id == session_id
    )
    d = s.to_dict()
    d["subagent_cost"] = round(subagent_cost, 4)
    return d


@app.get("/api/sessions/{session_id}/events")
async def get_session_events(session_id: str):
    s = scanner.get_session(session_id)
    if not s or not s.file_path:
        return {"error": "Session not found or file missing"}
    events = parse_session_events(s.file_path)
    return {"events": events}


@app.get("/api/sessions/{session_id}/notes")
async def get_session_notes(session_id: str):
    notes = _load_notes()
    return notes.get(session_id, {"note": "", "tags": []})


@app.post("/api/sessions/{session_id}/notes")
async def save_session_notes(session_id: str, body: dict):
    notes = _load_notes()
    notes[session_id] = body
    _save_notes(notes)
    return {"ok": True}


@app.get("/api/stats")
async def get_stats():
    return scanner.get_stats()


@app.get("/api/resources")
async def get_resources():
    return get_all_resources()


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


@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = scanner.get_stats()
            await websocket.send_json(data)
            await asyncio.sleep(5)
    except (WebSocketDisconnect, Exception):
        pass


# ── Notes helpers ─────────────────────────────────────────────────────────────

def _load_notes() -> dict:
    if NOTES_FILE.exists():
        try:
            return json.loads(NOTES_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_notes(notes: dict) -> None:
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_FILE.write_text(json.dumps(notes, indent=2))
