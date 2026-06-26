import sqlite3
import os
import re
from pathlib import Path

DB_PATH = Path(os.environ.get("MTU_DB_PATH", os.path.expanduser("~/.claude/mtu.db")))
DEFAULT_MODEL = os.environ.get("MTU_DEFAULT_MODEL", "gpt-5.5")

PRICING = {
    "gpt-5.5": {
        "input": 5.0e-6, "output": 30.0e-6,
        "cache_read": 0.5e-6, "cache_creation": 5.0e-6,
    },
    "gpt-5.5-codex": {
        "input": 5.0e-6, "output": 30.0e-6,
        "cache_read": 0.5e-6, "cache_creation": 5.0e-6,
    },
    "gpt-5.4": {
        "input": 2.5e-6, "output": 15.0e-6,
        "cache_read": 0.25e-6, "cache_creation": 2.5e-6,
    },
    "gpt-5.3-codex": {
        "input": 1.75e-6, "output": 14.0e-6,
        "cache_read": 0.175e-6, "cache_creation": 1.75e-6,
    },
    "gpt-5.3-codex-spark": {
        "input": 1.75e-6, "output": 14.0e-6,
        "cache_read": 0.175e-6, "cache_creation": 1.75e-6,
    },
    "claude-sonnet-4-6": {
        "input": 3.0e-6, "output": 15.0e-6,
        "cache_read": 0.3e-6, "cache_creation": 3.75e-6,
    },
    "claude-opus-4-7": {
        "input": 15.0e-6, "output": 75.0e-6,
        "cache_read": 1.5e-6, "cache_creation": 18.75e-6,
    },
    "claude-haiku-4-5-20251001": {
        "input": 0.8e-6, "output": 4.0e-6,
        "cache_read": 0.08e-6, "cache_creation": 1.0e-6,
    },
}


MODEL_ALIASES = {
    "gpt-5.3-codex-spark": "gpt-5.3-codex",
}


def normalize_model(model: str) -> str:
    normalized_model = MODEL_ALIASES.get(model, model)
    if normalized_model in PRICING:
        return normalized_model

    lowered = (normalized_model or "").strip().lower()
    if "-codex" in lowered:
        m = re.match(r"^gpt-(\d+\.\d+)", lowered)
        if m:
            candidate = f"gpt-{m.group(1)}-codex"
            if candidate in PRICING:
                return candidate
        # fallback de segurança para qualquer variação de codex
        if "5.5" in lowered and "gpt-5.5-codex" in PRICING:
            return "gpt-5.5-codex"
        if "5.3" in lowered and "gpt-5.3-codex" in PRICING:
            return "gpt-5.3-codex"
        return "gpt-5.3-codex"

    return normalized_model


def calc_cost(model: str, input_t: int, output_t: int, cache_read: int = 0, cache_create: int = 0) -> float:
    normalized_model = normalize_model(model)
    p = PRICING.get(normalized_model, PRICING[DEFAULT_MODEL])
    return (
        input_t * p["input"]
        + output_t * p["output"]
        + cache_read * p["cache_read"]
        + cache_create * p["cache_creation"]
    )


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS prompt_logs (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id           TEXT    NOT NULL,
            project              TEXT,
            timestamp            TEXT    NOT NULL DEFAULT (datetime('now')),
            prompt_preview       TEXT,
            input_tokens         INTEGER DEFAULT 0,
            output_tokens        INTEGER DEFAULT 0,
            cache_read_tokens    INTEGER DEFAULT 0,
            cache_creation_tokens INTEGER DEFAULT 0,
            model                TEXT    DEFAULT 'gpt-5.5',
            cost_usd             REAL    DEFAULT 0,
            estimated            INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS daily_stats (
            date             TEXT NOT NULL,
            model            TEXT NOT NULL,
            total_tokens     INTEGER DEFAULT 0,
            input_tokens     INTEGER DEFAULT 0,
            output_tokens    INTEGER DEFAULT 0,
            cache_read       INTEGER DEFAULT 0,
            cache_creation   INTEGER DEFAULT 0,
            message_count    INTEGER DEFAULT 0,
            session_count    INTEGER DEFAULT 0,
            tool_call_count  INTEGER DEFAULT 0,
            cost_usd         REAL    DEFAULT 0,
            PRIMARY KEY (date, model)
        );

        CREATE TABLE IF NOT EXISTS budget_config (
            project           TEXT PRIMARY KEY,
            daily_limit_tokens INTEGER NOT NULL,
            alert_threshold   REAL    DEFAULT 0.8,
            updated_at        TEXT    DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_pl_project   ON prompt_logs(project);
        CREATE INDEX IF NOT EXISTS idx_pl_timestamp ON prompt_logs(timestamp);
        CREATE INDEX IF NOT EXISTS idx_pl_session   ON prompt_logs(session_id);
        CREATE INDEX IF NOT EXISTS idx_ds_date      ON daily_stats(date);
        """)
