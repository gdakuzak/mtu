<p align="center">
  <img src="public/img/mtu.svg" width="200" height="200" alt="MTU logo" />
</p>

<p align="center">
  <a href="README.md">Português</a> · <strong>English</strong>
</p>

# MTU — Monitoring Token Usage

| | |
|---|---|
| **M** — Monitoring (Real-Time) | Tracks every LLM request and cost the moment it happens. |
| **T** — Token Analytics | Deep metrics on prompt, completion, and per-model usage. |
| **U** — Usage Guardrails | Set hard budgets, automatic alerts, and avoid API bill surprises. |

Tracks tokens per prompt, calculates estimated cost, and suggests optimizations. Integrates with Claude Code via MCP + automatic hook.

> [!WARNING]
> **Repository under construction.** Public release coming soon.

## Requirements

- Python 3.11+
- Docker + Docker Compose
- Claude Code CLI

---

## Quick Install

### 1. Clone and install

```bash
git clone <repo> ~/.local/share/mtu
cd ~/.local/share/mtu
uv venv && uv pip install -e .
```

### 2. Start Docker services

```bash
docker compose up -d
```

| Service | URL | Description |
|---------|-----|-------------|
| Dashboard | http://localhost:7799 | Charts, cache stats, and optimization tips |
| Prompts | http://localhost:7799/prompts | Prompt history with filters and sorting |
| SQLite UI | http://localhost:7800 | Browse/query the database directly |

### 3. Register MCP globally (all projects)

```bash
claude mcp add \
  --scope user \
  -e "PYTHONPATH=/path/to/mtu/src" \
  -- \
  mtu \
  /path/to/mtu/.venv/bin/python \
  -m mtu.server
```

Replace `/path/to/mtu` with the directory where you cloned the repo.

Verify: `claude mcp list` — should show `mtu: ✓ Connected`.

### 4. Add Stop hook (automatic per-prompt recording)

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /path/to/mtu/hooks/mtu-record-prompt.py",
            "timeout": 5,
            "async": true
          }
        ]
      }
    ]
  }
}
```

After this, **every Claude response is recorded automatically** — real tokens read from the session transcript, no extra configuration needed.

---

## Updating

### Manual

```bash
make update
```

Runs `git pull` + rebuild + redeploy. Shows previous → new version and commit list.

### Automatic (cron)

```bash
make setup-auto-update   # install cron job (checks hourly)
make remove-auto-update  # remove
```

Update interval configurable via `MTU_UPDATE_DAYS` (default: 7 days). Only rebuilds when a new version is detected upstream — no unnecessary rebuilds.

---

## What Gets Recorded

Each turn is captured from the session JSONL transcript:

| Field | Source |
| ------- | ------- |
| `input_tokens` | `message.usage.input_tokens` |
| `output_tokens` | `message.usage.output_tokens` |
| `cache_read_tokens` | `message.usage.cache_read_input_tokens` |
| `cache_creation_tokens` | `message.usage.cache_creation_input_tokens` |
| `model` | `message.model` |
| `prompt_preview` | Last user message with real text (300 chars, skips tool_results) |
| `project` | `basename(cwd)` |

---

## Web Interface

### Dashboard (`/`)

- Today's stats: tokens, cost, sessions, cache hit rate
- Tokens/cost chart by day (7/14/30 days)
- Cache stats per model (lifetime)
- Optimization suggestions
- Heaviest prompts table with truncated preview (click to open full modal)
- Project breakdown (30 days)
- Auto-sync every 30s with countdown

### Prompts (`/prompts`)

- Full history of recorded prompts
- Filters: project, model, date range
- Clickable column sorting (Date, Project, Model, Input, Output, Cache, Cost)
- "Load more" pagination (50 at a time, server-side)
- Full prompt modal on row click
- Images automatically sanitized (base64/img tags removed)

---

## Inline Alerts

When the hook detects problematic patterns, it prints to the session:

| Condition | Alert |
| ---------- | -------- |
| active tokens > 5K | `heavy prompt: NK tokens — consider /compact` |
| active tokens > 50K | `ALERT: NK tokens — critical context, use /compact urgently` |
| cache hit < 60% | `cache hit X% — context growing without reuse` |
| output > input and > 3K | `verbose response — use caveman mode` |

---

## Available MCP Tools

| Tool | Description |
| ------ | ----------- |
| `record_prompt` | Manually record token usage for a prompt |
| `get_usage_report` | N-day report with cache stats |
| `get_top_expensive_prompts` | Most expensive prompts by token count |
| `get_project_stats` | Breakdown per project |
| `analyze_optimization` | Optimization suggestions based on usage patterns |
| `sync_claude_stats` | Import history from `~/.claude/stats-cache.json` |
| `set_budget` | Set daily token limit |
| `check_token_budget` | Check current usage vs budget |

---

## Structure

```text
mtu/
├── hooks/
│   └── mtu-record-prompt.py   # Stop hook — reads transcript, POSTs to API
├── src/mtu/
│   ├── db.py                  # SQLite + pricing
│   ├── analyzer.py            # Stats, breakdown, optimization
│   ├── server.py              # MCP server (FastMCP)
│   └── web/
│       ├── app.py             # FastAPI — API + HTML routes
│       └── templates/
│           ├── dashboard.html # Main dashboard
│           └── prompts.html   # Prompt history
├── scripts/
│   ├── release.sh             # Bump version + changelog + git tag
│   └── auto-update.sh         # Update via git pull + rebuild (omz-inspired)
├── Makefile                   # Targets: release-*, update, setup-auto-update
├── docker-compose.yml
└── pyproject.toml
```
