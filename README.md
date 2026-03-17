# Stourio CC Dashboard

Local observability dashboard for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) sessions. Reads `~/.claude/projects/` session logs, parses them into structured data, and serves a real-time dashboard — **fully offline, never sends data anywhere**.

---

## Features

Navigation is a **left sidebar** with four sections: Live Ops, Session History, Stats, Resources. Dark mode UI throughout.

### 🟢 Live Ops (default view)
Real-time view of what Claude Code is doing right now. Updates via **WebSocket** (falls back to 30s polling, shown as `⬤ live` / `⬤ poll` indicator in the sidebar).

**KPI bar** — Active Sessions, Live Agents, Live Tools, Live Cost (API estimate), Avg Turn Duration

**Live Sessions table** — all currently active sessions, subagent sessions filtered out. Columns:
- Session slug (human-readable name) + expandable detail row
- Project, model, duration, tokens
- Cost (API estimate), tool error count, context window %, last turn duration

Click any row to expand and see the last 30 tool calls with inputs, error flags, cache hit ratio, and branch.

**Context alert** — orange banner appears when any session reaches ≥80% context window utilization.

**Active agents grid** — agent name (subagent type), task description, session slug, last turn duration. Agent badges use **orange** color (#f97316).

**Live tools table** — every tool invocation as it happens, with the actual input (file path, bash command, search query, URL) shown inline. Error calls highlighted in red.

### 📋 Session History
Full paginated session list with server-side filtering and sorting.

- **Filter bar** — search by slug/project/ID, filter by project, filter by status (all/active/completed), sort (newest/oldest/tokens/duration)
- **Load More** pagination (100 sessions per page)
- **CSV Export** — downloads filtered session list as `sessions.csv`
- **Session detail drawer** — 3 tabs:
  - **Tool Calls** — last 30 tool calls with inline input data and error flags
  - **Timeline** — parsed event stream (UserPrompt, AssistantMsg, ToolUse, ToolResult, SubagentStart)
  - **Notes** — freetext notes and tags, persisted to `~/.stourio-dashboard/session_notes.json`
- **Session comparison** — select up to 2 sessions via checkboxes, click Compare to view side-by-side metrics in a modal

### 📊 Stats
- **Overview cards** — Total Sessions (+ subagent count), Total Cost (API est.), Tool Calls + error count, Agents deployed + dispatches, Cache Hit Ratio
- **Token efficiency KPIs** — Tokens/Message, Cost/Tool Call, Avg Turn Duration, Hours Coded
- **Model distribution** — doughnut chart across all sessions including subagents (Opus, Sonnet, Haiku)
- **Daily Cost chart** — 30-day line chart of estimated API spend
- **Tool Usage Frequency** — bar chart of most-used tools across all sessions
- **Tool Error Rates** — bar chart of per-tool error counts
- **Activity heatmap** — GitHub-style 365-day heatmap of session activity, Monday-first, ISO week alignment
- Project names are clickable throughout — click any project name to jump to Session History pre-filtered by that project

### 🛠️ Resources
A dynamically updated library of all your installed Claude Code capabilities:
- **Agents** — specialized workflow agents
- **Skills** — custom user commands and installed plugin tools
- **MCP Servers** — Model Context Protocol active servers

---

## What Gets Parsed

Every `.jsonl` session file in `~/.claude/projects/` is parsed for:

| Field | Notes |
|---|---|
| Token usage | Input, output, cache read, cache creation — per turn and cumulative |
| Cost estimate | Calculated against Anthropic API pricing per model |
| Tool calls | Name + input data (file path, command, query, URL, etc.) |
| Tool errors | `is_error: true` results wired back to the originating call |
| Agent dispatches | Subagent type/name extracted from `Agent` tool input |
| Turn durations | From `system/turn_duration` events — avg and last |
| Session slug | Human-readable session name (e.g. `noble-honking-boole`) |
| Claude version | Version of Claude Code that ran the session |
| Cache hit ratio | `cache_read / (cache_read + input)` per session |
| Context window % | Based on last turn's input tokens, not cumulative |
| Subagent detection | Files under `subagents/` linked to parent session |
| Session notes | Freetext notes/tags, stored separately from session data |

> **Cost note:** Figures are API billing estimates. If you're on Claude Pro/Max, you are not charged per token — costs are shown for reference if you ever move to API billing.

---

## Install

```bash
pip3 install .
```

## Run

```bash
# CLI command (opens browser automatically)
stourio-dashboard -o

# Or as a Python module
python -m stourio_dashboard
```

## CLI Options

```
-p, --port PORT    Port to listen on (default: 3000)
--host HOST        Host to bind to (default: 127.0.0.1)
-o, --open         Open browser on start
--version          Show version
```

---

## Keyboard Shortcuts

| Key | Action |
|---|---|
| `1` | Live Ops |
| `2` | Session History |
| `3` | Stats |
| `4` | Resources |
| `r` | Refresh current tab |
| `Esc` | Close open modals |

---

## Run as Always-On Service (macOS)

Create a LaunchAgent to keep the dashboard running in the background. Verify the binary path first with `which stourio-dashboard` and update the plist accordingly.

```bash
cat << 'EOF' > ~/Library/LaunchAgents/com.stourio.dashboard.plist
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.stourio.dashboard</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/stourio-dashboard</string>
        <string>-p</string>
        <string>3000</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardErrorPath</key>
    <string>/tmp/stourio-dashboard.err</string>
    <key>StandardOutPath</key>
    <string>/tmp/stourio-dashboard.out</string>
</dict>
</plist>
EOF

launchctl load ~/Library/LaunchAgents/com.stourio.dashboard.plist
launchctl start com.stourio.dashboard
```

### Manage the Service

```bash
# Stop the service
launchctl stop com.stourio.dashboard

# Unload (disable) the service
launchctl unload ~/Library/LaunchAgents/com.stourio.dashboard.plist

# Kill any orphaned processes
pkill -9 -f stourio_dashboard

# Reload after code changes
pip install .
launchctl unload ~/Library/LaunchAgents/com.stourio.dashboard.plist
launchctl load ~/Library/LaunchAgents/com.stourio.dashboard.plist
```

---

## Data

| Item | Path |
|---|---|
| Session logs (read-only) | `~/.claude/projects/**/*.jsonl` |
| Dashboard settings | `~/.stourio-dashboard/settings.json` |
| Session notes | `~/.stourio-dashboard/session_notes.json` |
| File cache | `~/.stourio-dashboard/cache/` |

The scanner uses **mtime-based cache invalidation** — unchanged files are never re-parsed. Active sessions are always re-evaluated to detect the 15-minute idle timeout. Subagent JSONL files (under `subagents/`) are detected and linked to their parent session, preventing inflation of session counts and totals.

### Delete All Session Data

```bash
find ~/.claude/projects -type f -name "*.jsonl" -delete
```

---

## API

| Endpoint | Method | Description |
|---|---|---|
| `/api/sessions` | `GET` | List sessions — supports `q`, `project`, `model`, `status`, `sort`, `limit`, `offset` |
| `/api/sessions/export.csv` | `GET` | Download filtered sessions as CSV — same filters as `/api/sessions` |
| `/api/sessions/:id` | `GET` | Single session detail with full tool call list, cost breakdown, turn durations |
| `/api/sessions/:id/events` | `GET` | Raw parsed event timeline for a session |
| `/api/sessions/:id/notes` | `GET` | Retrieve session notes and tags |
| `/api/sessions/:id/notes` | `POST` | Save session notes and tags |
| `/api/resources` | `GET` | Installed Claude Code MCPs, Agents, and Skills |
| `/api/stats` | `GET` | Aggregate stats: live ops, overview, daily cost/tokens/sessions, tool frequency, tool errors, model distribution, projects, agent teams |
| `/api/projects` | `GET` | Per-project metrics |
| `/api/settings` | `GET` | Dashboard settings + available models |
| `/api/settings` | `POST` | Update settings |
| `/api/health` | `GET` | Health check |
| `/ws/live` | `WebSocket` | Push stats every 5s |

---

## Stack

- **Python 3.10+**
- **FastAPI** + **Uvicorn** — async HTTP server with WebSocket support
- **Jinja2** — template rendering
- **orjson** — fast JSON parsing for `.jsonl` session files
- **Click** — CLI interface
- **httpx** — HTTP client
- **Tailwind CSS** (CDN) + **Chart.js** — frontend
- **Zero external database** — filesystem only

---

## Project Structure

```
stourio_dashboard/
├── app.py          # FastAPI routes and application setup
├── cli.py          # Click CLI entry point
├── config.py       # Paths, model pricing, context windows, settings
├── models.py       # Dataclasses (SessionSummary, TokenUsage, ToolCall, etc.)
├── parser.py       # JSONL session file parser
├── scanner.py      # File discovery, caching, stats aggregation
├── templates/
│   └── dashboard.html   # Single-page dashboard UI
└── static/
    ├── favicon.svg
    └── logo.png
```

---

## License

MIT
