import json
import os
import re
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timedelta, timezone

from .db import DEFAULT_MODEL, get_conn, calc_cost, normalize_model

CLAUDE_DIR = Path(os.environ.get("MTU_CLAUDE_DIR", os.path.expanduser("~/.claude")))
STATS_CACHE = CLAUDE_DIR / "stats-cache.json"
HISTORY_JSONL = CLAUDE_DIR / "history.jsonl"
CREDENTIALS_FILE = CLAUDE_DIR / ".credentials.json"

CODEX_DIR = Path(os.environ.get("MTU_CODEX_DIR", os.path.expanduser("~/.codex")))
CODEX_SESSIONS_DIR = CODEX_DIR / "sessions"


def fetch_rate_limits() -> dict:
    """Fetch current rate limit utilization from Anthropic API using Claude Code OAuth token."""
    if not CREDENTIALS_FILE.exists():
        return {"error": "credentials not found"}

    try:
        creds = json.loads(CREDENTIALS_FILE.read_text())
        token = creds.get("claudeAiOauth", {}).get("accessToken", "")
        if not token:
            return {"error": "no access token"}
    except Exception:
        return {"error": "failed to read credentials"}

    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "x"}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            hdrs = dict(r.headers)
    except urllib.error.HTTPError as e:
        hdrs = dict(e.headers)
    except Exception as ex:
        return {"error": str(ex)}

    def ts_to_iso(ts_str: str) -> str | None:
        try:
            return datetime.fromtimestamp(int(ts_str), tz=timezone.utc).isoformat()
        except Exception:
            return None

    result = {
        "status": hdrs.get("anthropic-ratelimit-unified-status"),
        "representative_claim": hdrs.get("anthropic-ratelimit-unified-representative-claim"),
        "session_5h": {
            "utilization": float(hdrs.get("anthropic-ratelimit-unified-5h-utilization", 0)),
            "status": hdrs.get("anthropic-ratelimit-unified-5h-status"),
            "reset_ts": hdrs.get("anthropic-ratelimit-unified-5h-reset"),
            "reset_iso": ts_to_iso(hdrs.get("anthropic-ratelimit-unified-5h-reset", "")),
        },
        "week_7d": {
            "utilization": float(hdrs.get("anthropic-ratelimit-unified-7d-utilization", 0)),
            "status": hdrs.get("anthropic-ratelimit-unified-7d-status"),
            "reset_ts": hdrs.get("anthropic-ratelimit-unified-7d-reset"),
            "reset_iso": ts_to_iso(hdrs.get("anthropic-ratelimit-unified-7d-reset", "")),
        },
        "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    return result


def _read_transcripts() -> dict:
    """Read all JSONL transcripts and aggregate real usage by (date, model)."""
    projects_dir = CLAUDE_DIR / "projects"
    if not projects_dir.exists():
        return {}

    # {(date, model): {input, output, cache_read, cache_create}}
    daily: dict = {}

    for jsonl_path in projects_dir.rglob("*.jsonl"):
        try:
            with open(jsonl_path) as f:
                lines = [json.loads(l) for l in f if l.strip()]
        except Exception:
            continue

        for line in lines:
            msg = line.get("message", {})
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            usage = msg.get("usage")
            if not usage:
                continue
            model = normalize_model(msg.get("model", DEFAULT_MODEL))
            ts = line.get("timestamp", "")
            day = ts[:10] if ts else None
            if not day:
                continue

            key = (day, model)
            if key not in daily:
                daily[key] = {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}
            daily[key]["input"] += usage.get("input_tokens", 0)
            daily[key]["output"] += usage.get("output_tokens", 0)
            daily[key]["cache_read"] += usage.get("cache_read_input_tokens", 0)
            daily[key]["cache_create"] += usage.get("cache_creation_input_tokens", 0)

    return daily


def import_claude_stats() -> dict:
    """Sync real usage from transcripts + activity metadata from stats-cache.json."""
    daily_from_transcripts = _read_transcripts()

    activity_by_date: dict = {}
    if STATS_CACHE.exists():
        try:
            with open(STATS_CACHE) as f:
                data = json.load(f)
            for d in data.get("dailyActivity", []):
                activity_by_date[d["date"]] = d
        except Exception:
            pass

    if not daily_from_transcripts and not activity_by_date:
        return {"imported": 0, "error": "no transcript or stats data found"}

    imported = 0
    with get_conn() as conn:
        for (day, model), u in daily_from_transcripts.items():
            total_tokens = u["input"] + u["output"] + u["cache_read"] + u["cache_create"]
            cost = calc_cost(model, u["input"], u["output"], u["cache_read"], u["cache_create"])
            activity = activity_by_date.get(day, {})
            conn.execute(
                """
                INSERT OR REPLACE INTO daily_stats
                    (date, model, total_tokens, input_tokens, output_tokens,
                     cache_read, cache_creation, message_count, session_count,
                     tool_call_count, cost_usd)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    day, model, total_tokens,
                    u["input"], u["output"], u["cache_read"], u["cache_create"],
                    activity.get("messageCount", 0),
                    activity.get("sessionCount", 0),
                    activity.get("toolCallCount", 0),
                    cost,
                ),
            )
            imported += 1

    last = max((d for d, _ in daily_from_transcripts), default=None)
    return {"imported": imported, "last_date": last}


def _extract_codex_text(content) -> str:
    if isinstance(content, str):
        text = content.strip()
        return "" if _is_codex_injected_text(text) else _normalize_codex_user_text(text)
    if not isinstance(content, list):
        return ""

    texts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            cleaned = text.strip()
            if not _is_codex_injected_text(cleaned):
                texts.append(_normalize_codex_user_text(cleaned))

    # Codex user messages can include large injected context before the real
    # request. The last text block is usually the user's visible prompt.
    return texts[-1] if texts else ""


def _is_codex_injected_text(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith((
        "<skill>",
        "<environment_context>",
        "<permissions instructions>",
        "<collaboration_mode>",
        "<skills_instructions>",
        "<plugins_instructions>",
    ))


def _normalize_codex_user_text(text: str) -> str:
    marker = "## My request for Codex:"
    if marker in text:
        return text.split(marker, 1)[1].strip()
    return text


def _is_bad_codex_preview(text: str) -> bool:
    stripped = text.lstrip()
    return _is_codex_injected_text(stripped) or stripped.startswith("# Context from my IDE setup:")


def _sanitize_preview(text: str, limit: int = 2000) -> str:
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return cleaned[:limit]


def import_codex_stats() -> dict:
    """Import per-turn Codex token usage from ~/.codex/sessions JSONL files."""
    if not CODEX_SESSIONS_DIR.exists():
        return {"imported": 0, "skipped": 0, "error": "codex sessions dir not found"}

    imported = 0
    skipped = 0
    scanned_files = 0
    last_timestamp = None

    with get_conn() as conn:
        for jsonl_path in CODEX_SESSIONS_DIR.rglob("*.jsonl"):
            scanned_files += 1
            try:
                lines = [json.loads(l) for l in jsonl_path.read_text().splitlines() if l.strip()]
            except Exception:
                skipped += 1
                continue

            session_id = jsonl_path.stem
            cwd = ""
            model = DEFAULT_MODEL
            prompt_preview = ""

            for line in lines:
                line_type = line.get("type")
                payload = line.get("payload") if isinstance(line.get("payload"), dict) else {}

                if line_type == "session_meta":
                    session_id = payload.get("session_id") or payload.get("id") or session_id
                    cwd = payload.get("cwd") or cwd
                    if payload.get("model"):
                        model = payload["model"]
                    continue

                if line_type == "turn_context":
                    cwd = payload.get("cwd") or cwd
                    if payload.get("model"):
                        model = payload["model"]
                    continue

                if line_type == "response_item":
                    if payload.get("type") == "message" and payload.get("role") == "user":
                        preview = _extract_codex_text(payload.get("content"))
                        if preview:
                            prompt_preview = _sanitize_preview(preview)
                    if payload.get("model"):
                        model = payload["model"]
                    continue

                if line_type != "event_msg" or payload.get("type") != "token_count":
                    continue

                usage = (payload.get("info") or {}).get("last_token_usage") or {}
                if not usage:
                    continue

                timestamp = line.get("timestamp") or datetime.now().isoformat()
                selected_model = normalize_model(model or DEFAULT_MODEL)
                cache_read = int(usage.get("cached_input_tokens") or 0)
                input_total = int(usage.get("input_tokens") or 0)
                input_tokens = max(0, input_total - cache_read)
                output_tokens = int(usage.get("output_tokens") or 0)
                cache_creation = int(usage.get("cache_creation_input_tokens") or 0)
                if input_tokens + output_tokens + cache_read + cache_creation == 0:
                    skipped += 1
                    continue
                project = os.path.basename(cwd.rstrip("/")) if cwd else ""

                exists = conn.execute(
                    """
                    SELECT id, prompt_preview FROM prompt_logs
                    WHERE session_id = ? AND timestamp = ? AND model = ?
                    LIMIT 1
                    """,
                    (session_id, timestamp, selected_model),
                ).fetchone()
                if exists:
                    existing_preview = exists["prompt_preview"] or ""
                    if prompt_preview and (not existing_preview or _is_bad_codex_preview(existing_preview)):
                        conn.execute(
                            "UPDATE prompt_logs SET prompt_preview = ? WHERE id = ?",
                            (prompt_preview, exists["id"]),
                        )
                    skipped += 1
                    continue

                cost = calc_cost(
                    selected_model,
                    input_tokens,
                    output_tokens,
                    cache_read,
                    cache_creation,
                )
                conn.execute(
                    """
                    INSERT INTO prompt_logs
                        (session_id, project, timestamp, prompt_preview,
                         input_tokens, output_tokens, cache_read_tokens,
                         cache_creation_tokens, model, cost_usd, estimated)
                    VALUES (?,?,?,?,?,?,?,?,?,?,0)
                    """,
                    (
                        session_id,
                        project,
                        timestamp,
                        prompt_preview,
                        input_tokens,
                        output_tokens,
                        cache_read,
                        cache_creation,
                        selected_model,
                        cost,
                    ),
                )
                imported += 1
                last_timestamp = timestamp if last_timestamp is None else max(last_timestamp, timestamp)

    return {
        "imported": imported,
        "skipped": skipped,
        "scanned_files": scanned_files,
        "last_timestamp": last_timestamp,
    }


def import_all_stats() -> dict:
    """Sync every supported local source."""
    return {
        "claude": import_claude_stats(),
        "codex": import_codex_stats(),
    }


def get_daily_breakdown(days: int = 14) -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT date, model,
                   SUM(total_tokens) as total_tokens,
                   SUM(cache_read) as cache_read,
                   SUM(cache_creation) as cache_creation,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens,
                   SUM(message_count) as messages,
                   SUM(session_count) as sessions,
                   SUM(cost_usd) as cost
            FROM daily_stats
            WHERE date >= ?
            GROUP BY date, model
            ORDER BY date
            """,
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_project_breakdown(days: int = 30) -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT project,
                   COUNT(*) as prompt_count,
                   SUM(input_tokens + output_tokens + cache_read_tokens + cache_creation_tokens) as total_tokens,
                   SUM(cost_usd) as cost,
                   AVG(input_tokens + output_tokens) as avg_tokens_per_prompt
            FROM prompt_logs
            WHERE date(timestamp) >= ?
            GROUP BY project
            ORDER BY total_tokens DESC
            """,
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_expensive_prompts(limit: int = 10, project: str | None = None) -> list[dict]:
    with get_conn() as conn:
        query = """
            SELECT id, session_id, project, timestamp, prompt_preview,
                   input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
                   model, cost_usd, estimated
            FROM prompt_logs
            {where}
            ORDER BY (input_tokens + output_tokens) DESC
            LIMIT ?
        """
        if project:
            rows = conn.execute(
                query.format(where="WHERE project = ?"), (project, limit)
            ).fetchall()
        else:
            rows = conn.execute(query.format(where=""), (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_lifetime_cache_stats() -> dict:
    if not STATS_CACHE.exists():
        return {}
    with open(STATS_CACHE) as f:
        data = json.load(f)
    result = {}
    for model, mu in data.get("modelUsage", {}).items():
        inp = mu.get("inputTokens", 0)
        out = mu.get("outputTokens", 0)
        cache_read = mu.get("cacheReadInputTokens", 0)
        cache_create = mu.get("cacheCreationInputTokens", 0)
        total = inp + out + cache_read + cache_create
        hit_rate = cache_read / (inp + cache_read) if (inp + cache_read) > 0 else 0
        cost = calc_cost(model, inp, out, cache_read, cache_create)
        result[model] = {
            "input_tokens": inp,
            "output_tokens": out,
            "cache_read": cache_read,
            "cache_creation": cache_create,
            "total_tokens": total,
            "cache_hit_rate": round(hit_rate * 100, 1),
            "estimated_cost_usd": round(cost, 4),
        }
    return result


def get_today_summary() -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT SUM(total_tokens) as total_tokens,
                   SUM(cache_read) as cache_read,
                   SUM(input_tokens) as input_tokens,
                   SUM(message_count) as messages,
                   SUM(session_count) as sessions,
                   SUM(cost_usd) as cost
            FROM daily_stats WHERE date = ?
            """,
            (today,),
        ).fetchone()
    if row and row["total_tokens"]:
        d = dict(row)
        total_input = (d["input_tokens"] or 0) + (d["cache_read"] or 0)
        d["cache_hit_rate"] = round(
            (d["cache_read"] or 0) / total_input * 100 if total_input > 0 else 0, 1
        )
        return d
    return {"total_tokens": 0, "cache_read": 0, "messages": 0, "sessions": 0, "cost": 0, "cache_hit_rate": 0}


def generate_optimization_tips() -> list[dict]:
    tips = []
    cache = get_lifetime_cache_stats()
    for model, stats in cache.items():
        hit_rate = stats["cache_hit_rate"]
        if hit_rate < 70:
            tips.append({
                "level": "warning",
                "category": "cache",
                "title": f"Cache hit rate baixo: {hit_rate}%",
                "detail": "Adicione `cache_control: ephemeral` no CLAUDE.md ou use /compact com mais frequência.",
            })
        elif hit_rate >= 90:
            tips.append({
                "level": "success",
                "category": "cache",
                "title": f"Cache excelente: {hit_rate}% ({model})",
                "detail": "Prompts reutilizando contexto cacheado com eficiência.",
            })

    daily = get_daily_breakdown(7)
    if daily:
        tokens_by_day = {}
        for row in daily:
            tokens_by_day.setdefault(row["date"], 0)
            tokens_by_day[row["date"]] += row["total_tokens"]
        values = list(tokens_by_day.values())
        if len(values) >= 3:
            avg_early = sum(values[: len(values) // 2]) / (len(values) // 2)
            avg_late = sum(values[len(values) // 2 :]) / len(values[len(values) // 2 :])
            if avg_late > avg_early * 1.5:
                tips.append({
                    "level": "warning",
                    "category": "trend",
                    "title": "Consumo crescente nos últimos dias",
                    "detail": "Considere usar /compact no início das sessões longas para reduzir contexto acumulado.",
                })

    prompt_rows = get_expensive_prompts(limit=50)
    if prompt_rows:
        heavy = [p for p in prompt_rows if (p["input_tokens"] + p["output_tokens"]) > 5000]
        if heavy:
            tips.append({
                "level": "info",
                "category": "prompts",
                "title": f"{len(heavy)} prompts com >5k tokens encontrados",
                "detail": "Prompts pesados indicam contexto grande. Use /compact antes de tarefas novas ou divida em sessões menores.",
            })

    if not tips:
        tips.append({
            "level": "success",
            "category": "general",
            "title": "Uso de tokens parece saudável",
            "detail": "Nenhuma anomalia detectada. Continue registrando prompts com record_prompt para análise mais granular.",
        })

    return tips


def check_budget(project: str | None = None) -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    with get_conn() as conn:
        if project:
            budget_row = conn.execute(
                "SELECT * FROM budget_config WHERE project = ?", (project,)
            ).fetchone()
        else:
            budget_row = conn.execute(
                "SELECT * FROM budget_config WHERE project IS NULL OR project = ''",
            ).fetchone()

        today_tokens_row = conn.execute(
            "SELECT SUM(total_tokens) as t FROM daily_stats WHERE date = ?", (today,)
        ).fetchone()

    today_tokens = today_tokens_row["t"] or 0

    if not budget_row:
        return {"today_tokens": today_tokens, "limit": None, "warning": False, "over_budget": False}

    limit = budget_row["daily_limit_tokens"]
    threshold = budget_row["alert_threshold"]
    pct = today_tokens / limit if limit > 0 else 0

    return {
        "today_tokens": today_tokens,
        "limit": limit,
        "usage_percent": round(pct * 100, 1),
        "warning": pct >= threshold,
        "over_budget": pct >= 1.0,
        "remaining": max(0, limit - today_tokens),
    }
