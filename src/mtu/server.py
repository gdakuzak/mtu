import os
from datetime import datetime
from mcp.server.fastmcp import FastMCP

from .db import init_db, get_conn, calc_cost
from .analyzer import (
    import_claude_stats,
    get_daily_breakdown,
    get_project_breakdown,
    get_expensive_prompts,
    get_lifetime_cache_stats,
    get_today_summary,
    generate_optimization_tips,
    check_budget,
)

mcp = FastMCP("MTU - Token Usage Monitor")


@mcp.tool()
def record_prompt(
    session_id: str,
    project: str,
    prompt_preview: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
    model: str = "claude-sonnet-4-6",
    estimated: bool = False,
) -> dict:
    """
    Registra o uso de tokens de um prompt/resposta.

    Chame esta ferramenta após cada resposta para rastrear:
    - input_tokens: tokens da mensagem do usuário + contexto
    - output_tokens: tokens gerados na resposta
    - cache_read_tokens: tokens lidos do cache
    - cache_creation_tokens: tokens gravados no cache
    - estimated: True se os valores são estimados (não exatos)
    """
    cost = calc_cost(model, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO prompt_logs
                (session_id, project, prompt_preview, input_tokens, output_tokens,
                 cache_read_tokens, cache_creation_tokens, model, cost_usd, estimated)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                session_id, project, prompt_preview[:300],
                input_tokens, output_tokens,
                cache_read_tokens, cache_creation_tokens,
                model, cost, int(estimated),
            ),
        )
    total = input_tokens + output_tokens + cache_read_tokens + cache_creation_tokens
    return {
        "recorded": True,
        "total_tokens": total,
        "cost_usd": round(cost, 6),
        "budget": check_budget(project),
    }


@mcp.tool()
def get_usage_report(days: int = 7) -> dict:
    """
    Relatório de uso de tokens dos últimos N dias.
    Inclui breakdown por modelo e dia, com cache stats.
    """
    daily = get_daily_breakdown(days)
    today = get_today_summary()
    cache = get_lifetime_cache_stats()

    by_date: dict = {}
    for row in daily:
        d = row["date"]
        by_date.setdefault(d, {"date": d, "total_tokens": 0, "messages": 0, "sessions": 0, "cost": 0, "models": {}})
        by_date[d]["total_tokens"] += row["total_tokens"] or 0
        by_date[d]["messages"] += row["messages"] or 0
        by_date[d]["sessions"] += row["sessions"] or 0
        by_date[d]["cost"] += row["cost"] or 0
        by_date[d]["models"][row["model"]] = row["total_tokens"] or 0

    return {
        "days": days,
        "today": today,
        "daily": sorted(by_date.values(), key=lambda x: x["date"]),
        "lifetime_cache_stats": cache,
        "generated_at": datetime.now().isoformat(),
    }


@mcp.tool()
def get_top_expensive_prompts(limit: int = 10, project: str | None = None) -> list:
    """
    Lista os N prompts mais caros em tokens.
    Opcional: filtrar por projeto.
    """
    return get_expensive_prompts(limit=limit, project=project)


@mcp.tool()
def get_project_stats(days: int = 30) -> list:
    """
    Breakdown de uso por projeto nos últimos N dias.
    Só disponível para prompts registrados via record_prompt.
    """
    return get_project_breakdown(days=days)


@mcp.tool()
def analyze_optimization() -> dict:
    """
    Analisa padrões de uso e gera sugestões de otimização.
    Verifica: cache hit rate, tendências de crescimento, prompts pesados.
    """
    tips = generate_optimization_tips()
    cache = get_lifetime_cache_stats()
    summary = get_today_summary()

    return {
        "tips": tips,
        "cache_stats": cache,
        "today": summary,
        "generated_at": datetime.now().isoformat(),
    }


@mcp.tool()
def sync_claude_stats() -> dict:
    """
    Importa/sincroniza dados de ~/.claude/stats-cache.json.
    Execute isso para atualizar o histórico com dados recentes do Claude Code.
    """
    return import_claude_stats()


@mcp.tool()
def set_budget(daily_limit_tokens: int, project: str = "", alert_threshold: float = 0.8) -> dict:
    """
    Define limite diário de tokens.
    - daily_limit_tokens: limite em tokens por dia
    - project: nome do projeto (vazio = global)
    - alert_threshold: fração para alerta (0.8 = 80%)
    """
    proj = project or ""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO budget_config (project, daily_limit_tokens, alert_threshold, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            """,
            (proj, daily_limit_tokens, alert_threshold),
        )
    return {
        "set": True,
        "project": proj or "global",
        "daily_limit_tokens": daily_limit_tokens,
        "alert_at": f"{int(alert_threshold * 100)}%",
    }


@mcp.tool()
def check_token_budget(project: str = "") -> dict:
    """
    Verifica uso atual vs orçamento configurado.
    Retorna: tokens hoje, limite, % usado, se está em alerta.
    """
    return check_budget(project or None)


def main():
    init_db()
    import_claude_stats()
    mcp.run()


if __name__ == "__main__":
    main()
