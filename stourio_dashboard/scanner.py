from __future__ import annotations
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import PROJECTS_DIR, CACHE_DIR
from .models import SessionSummary
from .parser import parse_session_file


class SessionScanner:
    def __init__(self, claude_projects_dir: Optional[Path] = None):
        self.projects_dir = claude_projects_dir or PROJECTS_DIR
        self._cache: dict[str, tuple[float, Optional[SessionSummary]]] = {}
        self._last_scan: float = 0.0

    def scan_all(self, force: bool = False) -> list[SessionSummary]:
        if not self.projects_dir.exists():
            return []

        sessions: list[SessionSummary] = []
        seen_files: set[str] = set()

        for jsonl_file in self.projects_dir.rglob("*.jsonl"):
            fpath = str(jsonl_file)
            seen_files.add(fpath)

            try:
                mtime = jsonl_file.stat().st_mtime
            except OSError:
                continue

            if not force and fpath in self._cache:
                cached_mtime, cached_summary = self._cache[fpath]
                if cached_mtime == mtime:
                    # Force re-parse for active sessions so parser.py can evaluate the 15-min idle timeout
                    if cached_summary and cached_summary.status == "active":
                        pass 
                    else:
                        if cached_summary:
                            sessions.append(cached_summary)
                        continue

            project_name = self._extract_project_name(jsonl_file)
            summary = parse_session_file(jsonl_file, project_name)
            
            self._cache[fpath] = (mtime, summary)
            if summary:
                sessions.append(summary)

        stale = set(self._cache.keys()) - seen_files
        for key in stale:
            del self._cache[key]

        self._last_scan = time.time()
        sessions.sort(key=lambda s: s.started_at or datetime.min, reverse=True)
        return sessions

    def _extract_project_name(self, filepath: Path) -> str:
        rel = filepath.relative_to(self.projects_dir)
        parts = rel.parts
        if len(parts) >= 2:
            raw = parts[0]
            if raw.startswith("-"):
                decoded = raw.replace("-", "/")
                segments = [s for s in decoded.split("/") if s]
                return segments[-1] if segments else raw
            return raw
        return filepath.parent.name

    def get_session(self, session_id: str) -> Optional[SessionSummary]:
        sessions = self.scan_all()
        for s in sessions:
            if s.session_id == session_id:
                return s
        return None

    def get_stats(self) -> dict:
        sessions = self.scan_all()
        if not sessions:
            return self._empty_stats()

        live_sessions = [s for s in sessions if s.status == "active"]
        
        live_tools_count = 0
        live_tools_raw = []
        live_agents_list = []
        
        ignored_tools = {"dispatch_agent", "create_agent", "TaskTool", "TeammateTool", "Agent", "intel", "ToolSearch"}
        
        for s in live_sessions:
            short_id = s.session_id[:8]
            for t in s.tool_calls:
                if t.name not in ignored_tools and not t.name.startswith("toolu_"):
                    live_tools_raw.append({
                        "name": t.name,
                        "project": s.project,
                        "session": short_id,
                        "timestamp": t.timestamp
                    })
                    live_tools_count += 1
                
            for a in s.agent_dispatches:
                live_agents_list.append({
                    "agent_id": a.agent_id,
                    "task": a.task,
                    "project": s.project,
                    "session_id": short_id,
                    "timestamp": a.timestamp
                })
        
        live_agents_list.sort(key=lambda x: x["timestamp"] or "", reverse=True)
        live_tools_raw.sort(key=lambda x: x["timestamp"] or "", reverse=True)
        live_agents_unique = len(set(a["agent_id"] for a in live_agents_list))

        total_tokens = sum(s.tokens.total for s in sessions)
        total_cost = sum(s.cost.total for s in sessions)
        total_messages = sum(s.message_count for s in sessions)
        total_tool_calls = sum(len(s.tool_calls) for s in sessions)
        total_duration = sum(s.duration_seconds for s in sessions)

        model_counts: dict[str, int] = defaultdict(int)
        for s in sessions:
            for m in s.models_used:
                model_counts[m] += 1

        daily_tokens: dict[str, int] = defaultdict(int)
        daily_sessions: dict[str, int] = defaultdict(int)
        for s in sessions:
            if s.started_at:
                day = s.started_at.strftime("%Y-%m-%d")
                daily_tokens[day] += s.tokens.total
                daily_sessions[day] += 1

        hourly: dict[int, int] = defaultdict(int)
        for s in sessions:
            if s.started_at:
                hourly[s.started_at.hour] += 1

        project_stats: dict[str, dict] = defaultdict(
            lambda: {"sessions": 0, "tokens": 0, "cost": 0.0, "messages": 0, "duration": 0.0, "tool_calls": 0}
        )
        for s in sessions:
            p = project_stats[s.project]
            p["sessions"] += 1
            p["tokens"] += s.tokens.total
            p["cost"] += s.cost.total
            p["messages"] += s.message_count
            p["duration"] += s.duration_seconds
            p["tool_calls"] += len(s.tool_calls)

        team_sessions = [s for s in sessions if s.agent_dispatches]
        agent_counts: dict[str, int] = defaultdict(int)
        for s in team_sessions:
            for a in s.agent_dispatches:
                agent_counts[a.agent_id] += 1

        return {
            "live_ops": {
                "active_sessions": len(live_sessions),
                "active_tools": live_tools_count,
                "active_tools_list": live_tools_raw,
                "active_agents_count": live_agents_unique,
                "active_agents": live_agents_list
            },
            "overview": {
                "total_sessions": len(sessions),
                "total_tokens": total_tokens,
                "total_cost": round(total_cost, 2),
                "total_messages": total_messages,
                "total_tool_calls": total_tool_calls,
                "total_duration_hours": round(total_duration / 3600, 1),
            },
            "models": {
                "counts": dict(sorted(model_counts.items(), key=lambda x: x[1], reverse=True)),
            },
            "daily": {
                "tokens": dict(sorted(daily_tokens.items())),
                "sessions": dict(sorted(daily_sessions.items())),
            },
            "hourly": {str(h): hourly.get(h, 0) for h in range(24)},
            "projects": {
                k: {**v, "cost": round(v["cost"], 4), "duration_hours": round(v["duration"] / 3600, 1)}
                for k, v in sorted(project_stats.items(), key=lambda x: x[1]["tokens"], reverse=True)
            },
            "agent_teams": {
                "total_team_sessions": len(team_sessions),
                "total_dispatches": sum(len(s.agent_dispatches) for s in team_sessions),
                "agents": dict(sorted(agent_counts.items(), key=lambda x: x[1], reverse=True)),
            },
        }

    def _empty_stats(self) -> dict:
        return {
            "live_ops": {"active_sessions": 0, "active_tools": 0, "active_tools_list": [], "active_agents_count": 0, "active_agents": []},
            "overview": {"total_sessions": 0, "total_tokens": 0, "total_cost": 0, "total_messages": 0, "total_tool_calls": 0, "total_duration_hours": 0},
            "models": {"counts": {}}, "daily": {"tokens": {}, "sessions": {}}, "hourly": {str(h): 0 for h in range(24)}, "projects": {}, "agent_teams": {"total_team_sessions": 0, "total_dispatches": 0, "agents": {}},
        }