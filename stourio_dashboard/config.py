from __future__ import annotations
from pathlib import Path
import json

CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
DASHBOARD_DIR = Path.home() / ".stourio-dashboard"
CACHE_DIR = DASHBOARD_DIR / "cache"
SETTINGS_FILE = DASHBOARD_DIR / "settings.json"

# Per-million-token pricing (USD)
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {"input": 15.0, "output": 75.0, "cache_read": 1.5, "cache_creation": 18.75},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_creation": 3.75},
    "claude-haiku-4-5": {"input": 0.8, "output": 4.0, "cache_read": 0.08, "cache_creation": 1.0},
    # Legacy
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_creation": 3.75},
    "claude-opus-4-20250918": {"input": 15.0, "output": 75.0, "cache_read": 1.5, "cache_creation": 18.75},
}

DEFAULT_MODEL = "claude-sonnet-4-6"

CONTEXT_WINDOWS: dict[str, int] = {
    "claude-opus-4-6": 1000000,
    "claude-sonnet-4-6": 1000000,
    "claude-haiku-4-5": 200000,
}


def get_pricing(model: str) -> dict[str, float]:
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    for key, pricing in MODEL_PRICING.items():
        if key in model or model in key:
            return pricing
    return MODEL_PRICING[DEFAULT_MODEL]


def get_context_window(model: str) -> int:
    if model in CONTEXT_WINDOWS:
        return CONTEXT_WINDOWS[model]
    for key, window in CONTEXT_WINDOWS.items():
        if key in model or model in key:
            return window
    return 200000


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        return json.loads(SETTINGS_FILE.read_text())
    return {"subscription_tier": "api", "custom_pricing": {}}


def save_settings(settings: dict) -> None:
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2))
