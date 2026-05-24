import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn

from ..db import init_db, get_conn, calc_cost
from ..analyzer import (
    import_claude_stats,
    get_daily_breakdown,
    get_project_breakdown,
    get_expensive_prompts,
    get_lifetime_cache_stats,
    get_today_summary,
    generate_optimization_tips,
    check_budget,
)

DASHBOARD_HTML = Path(__file__).parent / "templates" / "dashboard.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    import_claude_stats()
    yield


app = FastAPI(title="MTU - Token Usage Monitor", lifespan=lifespan)


class RecordRequest(BaseModel):
    session_id: str
    project: str
    prompt_preview: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    model: str = "claude-sonnet-4-6"
    timestamp: str = ""


@app.get("/", response_class=FileResponse)
async def dashboard():
    return FileResponse(str(DASHBOARD_HTML), media_type="text/html",
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.post("/api/record")
async def api_record(req: RecordRequest):
    cost = calc_cost(
        req.model, req.input_tokens, req.output_tokens,
        req.cache_read_tokens, req.cache_creation_tokens,
    )
    ts = req.timestamp or datetime.now().isoformat()

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO prompt_logs
                (session_id, project, timestamp, prompt_preview,
                 input_tokens, output_tokens, cache_read_tokens,
                 cache_creation_tokens, model, cost_usd, estimated)
            VALUES (?,?,?,?,?,?,?,?,?,?,0)
            """,
            (
                req.session_id, req.project, ts, req.prompt_preview[:300],
                req.input_tokens, req.output_tokens,
                req.cache_read_tokens, req.cache_creation_tokens,
                req.model, cost,
            ),
        )

    tips = _generate_inline_tips(req)
    total = req.input_tokens + req.output_tokens + req.cache_read_tokens + req.cache_creation_tokens

    return {
        "recorded": True,
        "cost_usd": round(cost, 6),
        "total_tokens": total,
        "tips": tips,
    }


def _generate_inline_tips(req: RecordRequest) -> list[str]:
    tips = []
    active = req.input_tokens + req.output_tokens
    cache_in = req.input_tokens + req.cache_read_tokens

    hit_rate = req.cache_read_tokens / cache_in if cache_in > 0 else 1.0

    if active > 50_000:
        tips.append(f"ALERTA: {active // 1000}K tokens — contexto crítico, use /compact urgente")
    elif active > 5_000:
        tips.append(f"prompt pesado: {active // 1000}K tokens — considere /compact")

    if hit_rate < 0.6 and active > 3_000:
        tips.append(f"cache hit {hit_rate * 100:.0f}% — contexto crescendo sem reuso de cache")

    if req.output_tokens > req.input_tokens and req.output_tokens > 3_000:
        tips.append(f"resposta verbose: {req.output_tokens // 1000}K tokens output — use caveman mode")

    return tips


@app.get("/api/stats/daily")
async def api_daily(days: int = 14):
    daily = get_daily_breakdown(days)
    by_date: dict = {}
    for row in daily:
        d = row["date"]
        by_date.setdefault(d, {"date": d, "total_tokens": 0, "messages": 0, "sessions": 0, "cost": 0.0})
        by_date[d]["total_tokens"] += row["total_tokens"] or 0
        by_date[d]["messages"] += row["messages"] or 0
        by_date[d]["sessions"] += row["sessions"] or 0
        by_date[d]["cost"] += row["cost"] or 0

    # Merge com dados reais do prompt_logs (hoje)
    today = datetime.now().strftime("%Y-%m-%d")
    with get_conn() as conn:
        pl = conn.execute(
            """
            SELECT date(timestamp) as date,
                   SUM(input_tokens + output_tokens + cache_read_tokens + cache_creation_tokens) as total_tokens,
                   COUNT(*) as messages,
                   COUNT(DISTINCT session_id) as sessions,
                   SUM(cost_usd) as cost
            FROM prompt_logs
            WHERE date(timestamp) >= ?
            GROUP BY date(timestamp)
            """,
            ((datetime.now().replace(day=1).strftime("%Y-%m-%d")),),
        ).fetchall()

    for row in pl:
        d = row["date"]
        if d not in by_date:
            by_date[d] = {"date": d, "total_tokens": 0, "messages": 0, "sessions": 0, "cost": 0.0}
        by_date[d]["total_tokens"] += row["total_tokens"] or 0
        by_date[d]["messages"] += row["messages"] or 0
        by_date[d]["sessions"] += row["sessions"] or 0
        by_date[d]["cost"] += row["cost"] or 0

    return sorted(by_date.values(), key=lambda x: x["date"])


@app.get("/api/stats/today")
async def api_today():
    today = datetime.now().strftime("%Y-%m-%d")
    # Prioriza dados reais do prompt_logs
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) as messages,
                   COUNT(DISTINCT session_id) as sessions,
                   SUM(input_tokens + output_tokens + cache_read_tokens + cache_creation_tokens) as total_tokens,
                   SUM(cache_read_tokens) as cache_read,
                   SUM(input_tokens) as input_tokens,
                   SUM(cost_usd) as cost
            FROM prompt_logs WHERE date(timestamp) = ?
            """,
            (today,),
        ).fetchone()

    if row and row["total_tokens"]:
        d = dict(row)
        cache_in = (d["input_tokens"] or 0) + (d["cache_read"] or 0)
        d["cache_hit_rate"] = round((d["cache_read"] or 0) / cache_in * 100 if cache_in > 0 else 0, 1)
        return d

    return get_today_summary()


@app.get("/api/stats/cache")
async def api_cache():
    return get_lifetime_cache_stats()


@app.get("/api/stats/projects")
async def api_projects(days: int = 30):
    return get_project_breakdown(days)


@app.get("/api/prompts/expensive")
async def api_expensive(limit: int = 15, project: str | None = None):
    import re
    rows = get_expensive_prompts(limit=limit, project=project)
    for r in rows:
        if r.get("prompt_preview"):
            r["prompt_preview"] = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", r["prompt_preview"])
    return rows


SORTABLE_COLS = {
    "timestamp", "project", "model",
    "input_tokens", "output_tokens", "cache_read_tokens", "cost_usd",
}

@app.get("/api/prompts/recent")
async def api_recent(
    limit: int = 50,
    offset: int = 0,
    project: str | None = None,
    model: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort: str = "timestamp",
    dir: str = "desc",
):
    import re
    col = sort if sort in SORTABLE_COLS else "timestamp"
    order = "DESC" if dir.lower() == "desc" else "ASC"
    clauses = []
    params: list = []
    if project:
        clauses.append("project = ?")
        params.append(project)
    if model:
        clauses.append("model = ?")
        params.append(model)
    if date_from:
        clauses.append("date(timestamp) >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("date(timestamp) <= ?")
        params.append(date_to)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params += [limit, offset]
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT id, session_id, project, timestamp, prompt_preview,
                   input_tokens, output_tokens, cache_read_tokens,
                   cache_creation_tokens, model, cost_usd, estimated
            FROM prompt_logs
            {where}
            ORDER BY {col} {order}
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
        total = conn.execute(
            f"SELECT COUNT(*) FROM prompt_logs {where}",
            params[:-2],
        ).fetchone()[0]
    result = []
    ctrl = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
    for r in rows:
        d = dict(r)
        if d.get("prompt_preview"):
            d["prompt_preview"] = ctrl.sub("", d["prompt_preview"])
        result.append(d)
    return {"total": total, "offset": offset, "limit": limit, "items": result}


@app.get("/api/prompts/projects")
async def api_prompt_projects():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT project FROM prompt_logs WHERE project IS NOT NULL ORDER BY project"
        ).fetchall()
    return [r["project"] for r in rows if r["project"]]


PROMPTS_HTML = Path(__file__).parent / "templates" / "prompts.html"


@app.get("/prompts", response_class=FileResponse)
async def prompts_page():
    return FileResponse(str(PROMPTS_HTML), media_type="text/html",
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.get("/api/optimization")
async def api_optimization():
    return generate_optimization_tips()


@app.get("/api/budget")
async def api_budget(project: str | None = None):
    return check_budget(project)


@app.post("/api/sync")
async def api_sync():
    return import_claude_stats()


def main():
    port = int(os.environ.get("MTU_PORT", 7799))
    uvicorn.run("mtu.web.app:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
