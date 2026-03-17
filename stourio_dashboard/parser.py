from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .models import (
    AgentDispatch,
    CostEstimate,
    SessionSummary,
    TokenUsage,
    ToolCall,
)
from .config import get_pricing, get_context_window


def parse_timestamp(ts: Any) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts, tz=timezone.utc)
        except (ValueError, OSError):
            return None
    if isinstance(ts, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def extract_usage(msg: dict) -> TokenUsage:
    usage = msg.get("usage") or msg.get("message", {}).get("usage") or {}
    return TokenUsage(
        input_tokens=usage.get("input_tokens", 0) or 0,
        output_tokens=usage.get("output_tokens", 0) or 0,
        cache_read_tokens=usage.get("cache_read_input_tokens", 0) or usage.get("cache_read_tokens", 0) or 0,
        cache_creation_tokens=usage.get("cache_creation_input_tokens", 0) or usage.get("cache_creation_tokens", 0) or 0,
    )


def clean_tool_name(name: str) -> str:
    return name.replace("mcp__gemini-cli__", "").replace("mcp__", "")


def _extract_input_data(tool_name: str, inp: dict) -> Optional[str]:
    # Web
    if tool_name in ("WebSearch", "BraveSearch"):
        return inp.get("query") or inp.get("q")
    if tool_name == "WebFetch":
        return inp.get("url")
    # File ops
    if tool_name in ("Read", "Write", "Edit", "view_file", "read_file", "create_file",
                     "str_replace_based_edit_tool", "str_replace_editor"):
        return inp.get("file_path") or inp.get("path")
    # Search
    if tool_name in ("Grep", "grep"):
        pattern = inp.get("pattern") or inp.get("regex") or ""
        path = inp.get("path") or ""
        return f"{pattern}  {path}".strip() if pattern else path or None
    if tool_name in ("Glob", "glob", "file_search"):
        return inp.get("pattern") or inp.get("path")
    # Shell
    if tool_name in ("Bash", "bash", "execute_bash", "computer"):
        cmd = inp.get("command") or inp.get("cmd") or ""
        return cmd[:120] if cmd else None
    # Agents / subagents
    if tool_name in ("Agent", "dispatch_agent", "create_agent", "TaskTool", "TeammateTool"):
        return inp.get("description") or inp.get("subagent_type") or inp.get("prompt", "")[:80]
    # Tasks
    if tool_name in ("TaskCreate", "TaskUpdate", "TaskGet"):
        return inp.get("title") or inp.get("task_id")
    # MCP / other tools with a query
    query = inp.get("query") or inp.get("q")
    if query:
        return query
    # Generic: first string value that looks meaningful
    for key in ("url", "file_path", "path", "name", "id", "topic", "message", "text", "content"):
        val = inp.get(key)
        if val and isinstance(val, str):
            return val[:120]
    return None


def extract_tool_calls(msg: dict) -> tuple[list[ToolCall], dict[str, ToolCall]]:
    """Returns (tool_calls, id_map) where id_map maps tool_use_id -> ToolCall for error wiring."""
    tools: list[ToolCall] = []
    id_map: dict[str, ToolCall] = {}
    content = msg.get("content") or msg.get("message", {}).get("content") or []
    ts = msg.get("timestamp") or msg.get("created_at") or msg.get("message", {}).get("created_at")

    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                raw_name = block.get("name", "unknown")
                inp = block.get("input", {})
                tc = ToolCall(
                    name=clean_tool_name(raw_name),
                    timestamp=ts,
                    input_data=_extract_input_data(raw_name, inp),
                )
                tools.append(tc)
                if "id" in block:
                    id_map[block["id"]] = tc

    if msg.get("type") == "tool_use":
        raw_name = msg.get("name", "unknown")
        inp = msg.get("input", {})
        tc = ToolCall(
            name=clean_tool_name(raw_name),
            timestamp=ts,
            input_data=_extract_input_data(raw_name, inp),
        )
        tools.append(tc)
        if "id" in msg:
            id_map[msg["id"]] = tc

    return tools, id_map


def _extract_tool_errors(msg: dict) -> list[str]:
    """Return tool_use_ids of tool results with is_error: true."""
    error_ids = []
    # Try multiple content paths (user message, progress message)
    content = (
        msg.get("content")
        or msg.get("message", {}).get("content")
        or (msg.get("data") or {}).get("message", {}).get("message", {}).get("content")
        or []
    )
    if isinstance(content, list):
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_result"
                and block.get("is_error")
            ):
                tid = block.get("tool_use_id", "")
                if tid:
                    error_ids.append(tid)
    return error_ids


def extract_agent_info(msg: dict) -> Optional[AgentDispatch]:
    ts = msg.get("timestamp") or msg.get("created_at") or msg.get("message", {}).get("created_at")

    if msg.get("type") in ("agent_dispatch", "teammate_spawn", "team_create"):
        return AgentDispatch(
            agent_id=msg.get("agent_id") or msg.get("teammate_id") or msg.get("team_id", "unknown"),
            task=msg.get("task") or msg.get("prompt", "")[:200],
            timestamp=ts,
        )

    content = msg.get("content") or msg.get("message", {}).get("content") or []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = block.get("name", "")
                inp = block.get("input", {})

                if name in ("dispatch_agent", "create_agent", "TaskTool", "TeammateTool", "Agent"):
                    agent_name = (
                        inp.get("name")
                        or inp.get("subagent_type")
                        or inp.get("agent_id")
                        or inp.get("teammate_name")
                        or name
                    )
                    return AgentDispatch(
                        agent_id=agent_name,
                        task=inp.get("task") or inp.get("prompt") or inp.get("description", "")[:200],
                        timestamp=ts,
                    )

                standard_tools = {
                    "bash", "glob", "grep", "read_file", "view_file", "file_search",
                    "str_replace", "notebook", "WebSearch", "WebFetch", "ToolSearch",
                    "ask_gemini", "BraveSearch"
                }
                if "prompt" in inp and not name.startswith("mcp_") and name not in standard_tools:
                    return AgentDispatch(
                        agent_id=name,
                        task=inp.get("prompt", "")[:200],
                        timestamp=ts,
                    )
    return None


def compute_cost(tokens: TokenUsage, model: str) -> CostEstimate:
    pricing = get_pricing(model)
    return CostEstimate(
        input_cost=tokens.input_tokens * pricing["input"] / 1_000_000,
        output_cost=tokens.output_tokens * pricing["output"] / 1_000_000,
        cache_read_cost=tokens.cache_read_tokens * pricing["cache_read"] / 1_000_000,
        cache_creation_cost=tokens.cache_creation_tokens * pricing["cache_creation"] / 1_000_000,
    )


def parse_session_file(filepath: Path, project_name: str) -> Optional[SessionSummary]:
    try:
        lines = filepath.read_text(errors="replace").strip().split("\n")
    except (OSError, PermissionError):
        return None

    if not lines:
        return None

    session_id = filepath.stem
    tokens = TokenUsage()
    tool_calls: list[ToolCall] = []
    tool_id_map: dict[str, ToolCall] = {}
    agent_dispatches: list[AgentDispatch] = []
    models_used: set[str] = set()
    timestamps: list[datetime] = []
    turn_durations: list[float] = []
    human_count = 0
    assistant_count = 0
    total_messages = 0
    model = ""
    branch = ""
    project_path = ""
    slug = ""
    version = ""
    last_input_tokens = 0
    pending_tool_ids: set[str] = set()

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        role = msg.get("role") or msg.get("type") or msg.get("message", {}).get("role", "")
        if role != "tool_result":
            total_messages += 1

        ts = parse_timestamp(
            msg.get("timestamp")
            or msg.get("created_at")
            or msg.get("message", {}).get("created_at")
        )
        if ts:
            timestamps.append(ts)

        # Metadata available on every message
        if not slug:
            slug = msg.get("slug", "")
        if not version:
            version = msg.get("version", "")

        if role in ("human", "user"):
            human_count += 1
        elif role == "assistant":
            assistant_count += 1
            # Track last turn's full context fill (non-cached + cached input)
            usage = msg.get("usage") or msg.get("message", {}).get("usage") or {}
            inp_tok = usage.get("input_tokens", 0) or 0
            cache_tok = usage.get("cache_read_input_tokens", 0) or usage.get("cache_read_tokens", 0) or 0
            ctx_tok = inp_tok + cache_tok
            if ctx_tok:
                last_input_tokens = ctx_tok

        msg_model = msg.get("model") or msg.get("message", {}).get("model", "")
        if msg_model:
            model = msg_model
            models_used.add(msg_model)

        usage = extract_usage(msg)
        tokens.input_tokens += usage.input_tokens
        tokens.output_tokens += usage.output_tokens
        tokens.cache_read_tokens += usage.cache_read_tokens
        tokens.cache_creation_tokens += usage.cache_creation_tokens

        # Turn duration
        if msg.get("type") == "system" and msg.get("subtype") == "turn_duration":
            dur = msg.get("durationMs")
            if isinstance(dur, (int, float)) and dur > 0:
                turn_durations.append(float(dur))

        new_tools, new_id_map = extract_tool_calls(msg)
        tool_calls.extend(new_tools)
        tool_id_map.update(new_id_map)

        # Wire is_error onto the corresponding ToolCall
        for eid in _extract_tool_errors(msg):
            if eid in tool_id_map:
                tool_id_map[eid].is_error = True

        # Track active execution state via unbalanced tool IDs
        content = msg.get("content") or msg.get("message", {}).get("content") or []
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "tool_use" and "id" in block:
                        pending_tool_ids.add(block["id"])
                    elif block.get("type") == "tool_result" and "tool_use_id" in block:
                        pending_tool_ids.discard(block["tool_use_id"])

        if msg.get("type") == "tool_use" and "id" in msg:
            pending_tool_ids.add(msg["id"])

        agent = extract_agent_info(msg)
        if agent:
            agent_dispatches.append(agent)

        if msg.get("type") == "session_start" or msg.get("type") == "system":
            meta = msg.get("metadata") or msg.get("session") or {}
            branch = branch or meta.get("branch", "") or meta.get("git_branch", "")
            project_path = project_path or meta.get("project_path", "") or meta.get("cwd", "")

    # Drop pure phantom windows immediately
    if human_count == 0 and tokens.total == 0:
        return None

    started = min(timestamps) if timestamps else None
    ended = max(timestamps) if timestamps else None
    duration = (ended - started).total_seconds() if started and ended else 0.0

    now = datetime.now(tz=timezone.utc)
    time_since_last_event = (now - ended).total_seconds() if ended else 0

    # State Evaluation Heuristic
    is_active = False
    if len(pending_tool_ids) > 0:
        is_active = True
    elif time_since_last_event < 900:
        is_active = True

    # Resolve synthetic/placeholder model names to the actual model used
    real_model = model
    if not model or model.startswith("<"):
        for m in sorted(models_used):
            if not m.startswith("<"):
                real_model = m
                break
        else:
            real_model = model or "claude-sonnet-4-6"

    cost = compute_cost(tokens, real_model)

    return SessionSummary(
        session_id=session_id,
        project=project_name,
        project_path=project_path,
        branch=branch,
        model=real_model,
        slug=slug,
        version=version,
        status="active" if is_active else "completed",
        started_at=started,
        ended_at=ended,
        duration_seconds=duration,
        message_count=total_messages,
        human_messages=human_count,
        assistant_messages=assistant_count,
        tokens=tokens,
        last_input_tokens=last_input_tokens,
        cost=cost,
        tool_calls=tool_calls,
        agent_dispatches=agent_dispatches,
        context_window_max=get_context_window(real_model),
        models_used=sorted(models_used),
        turn_durations=turn_durations,
        file_path=str(filepath),
    )


def parse_session_events(file_path: str) -> list[dict]:
    path = Path(file_path)
    if not path.exists():
        return []

    events = []
    try:
        lines = path.read_text(errors="replace").strip().split("\n")
        for line in lines:
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts = msg.get("timestamp") or msg.get("created_at") or ""
            mtype = msg.get("type") or msg.get("message", {}).get("type") or msg.get("role") or ""
            content_preview = ""
            event_name = "Unknown"

            if mtype in ("human", "user"):
                event_name = "UserPrompt"
                content = msg.get("content") or msg.get("message", {}).get("content", "")
                if isinstance(content, list):
                    content_preview = " ".join([str(b.get("text", "")) for b in content if isinstance(b, dict)])
                else:
                    content_preview = str(content)
            elif mtype in ("agent_dispatch", "teammate_spawn", "team_create"):
                event_name = "SubagentStart"
                content_preview = msg.get("task") or msg.get("prompt", "")
            elif mtype == "tool_use":
                event_name = "ToolUse"
                raw_name = msg.get("name", "")
                content_preview = clean_tool_name(raw_name)
            elif mtype == "tool_result":
                event_name = "ToolResult"
                content_preview = clean_tool_name(msg.get("tool_use_id", ""))
            elif mtype == "assistant":
                event_name = "AssistantMsg"
                content = msg.get("content") or msg.get("message", {}).get("content", "")
                if isinstance(content, list):
                    content_preview = " ".join([str(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("type") == "text"])
                else:
                    content_preview = str(content)
            elif mtype == "session_start":
                event_name = "SessionStart"
            else:
                content = msg.get("content") or msg.get("message", {}).get("content") or []
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_use":
                            inp = b.get("input", {})
                            preview = clean_tool_name(b.get("name", ""))
                            input_data = _extract_input_data(b.get("name", ""), inp)
                            if input_data:
                                preview = f"{preview}: {input_data[:80]}"
                            events.append({
                                "timestamp": ts,
                                "event": "ToolUse",
                                "preview": preview,
                                "is_error": False,
                            })
                continue

            events.append({
                "timestamp": ts,
                "event": event_name,
                "preview": content_preview[:300] if content_preview else "",
            })
    except Exception:
        pass

    return events
