from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_creation_tokens


@dataclass
class ToolCall:
    name: str
    timestamp: Optional[str] = None
    duration_ms: Optional[float] = None
    is_error: bool = False


@dataclass
class AgentDispatch:
    agent_id: str
    task: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    timestamp: Optional[str] = None


@dataclass
class CostEstimate:
    input_cost: float = 0.0
    output_cost: float = 0.0
    cache_read_cost: float = 0.0
    cache_creation_cost: float = 0.0

    @property
    def total(self) -> float:
        return self.input_cost + self.output_cost + self.cache_read_cost + self.cache_creation_cost


@dataclass
class SessionSummary:
    session_id: str
    project: str
    project_path: str = ""
    branch: str = ""
    model: str = ""
    status: str = "completed"
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: float = 0.0
    message_count: int = 0
    human_messages: int = 0
    assistant_messages: int = 0
    tokens: TokenUsage = field(default_factory=TokenUsage)
    cost: CostEstimate = field(default_factory=CostEstimate)
    tool_calls: list[ToolCall] = field(default_factory=list)
    agent_dispatches: list[AgentDispatch] = field(default_factory=list)
    context_window_max: int = 200000
    models_used: list[str] = field(default_factory=list)
    file_path: str = ""

    @property
    def duration_display(self) -> str:
        s = int(self.duration_seconds)
        if s < 60:
            return f"{s}s"
        if s < 3600:
            return f"{s // 60}m {s % 60}s"
        return f"{s // 3600}h {(s % 3600) // 60}m"

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "project": self.project,
            "project_path": self.project_path,
            "branch": self.branch,
            "model": self.model,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_seconds": self.duration_seconds,
            "duration_display": self.duration_display,
            "message_count": self.message_count,
            "human_messages": self.human_messages,
            "assistant_messages": self.assistant_messages,
            "tokens": {
                "input": self.tokens.input_tokens,
                "output": self.tokens.output_tokens,
                "cache_read": self.tokens.cache_read_tokens,
                "cache_creation": self.tokens.cache_creation_tokens,
                "total": self.tokens.total,
            },
            "cost": {
                "input": round(self.cost.input_cost, 6),
                "output": round(self.cost.output_cost, 6),
                "cache_read": round(self.cost.cache_read_cost, 6),
                "cache_creation": round(self.cost.cache_creation_cost, 6),
                "total": round(self.cost.total, 4),
            },
            "tool_calls": [
                {"name": t.name, "timestamp": t.timestamp, "duration_ms": t.duration_ms, "is_error": t.is_error}
                for t in self.tool_calls
            ],
            "tool_call_count": len(self.tool_calls),
            "agent_dispatches": [
                {
                    "agent_id": a.agent_id,
                    "task": a.task,
                    "timestamp": a.timestamp,
                    "tool_calls": [
                        {"name": t.name, "timestamp": t.timestamp, "duration_ms": t.duration_ms}
                        for t in a.tool_calls
                    ],
                }
                for a in self.agent_dispatches
            ],
            "context_window": {
                "max": self.context_window_max,
                "used": self.tokens.input_tokens + self.tokens.cache_read_tokens,
                "utilization_pct": round(
                    (self.tokens.input_tokens + self.tokens.cache_read_tokens) / self.context_window_max * 100, 1
                )
                if self.context_window_max
                else 0,
            },
            "models_used": self.models_used,
        }
