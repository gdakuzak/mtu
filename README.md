<p align="center">
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="80" height="80" fill="none">
    <defs>
      <linearGradient id="mtu-grad" x1="0%" y1="100%" x2="100%" y2="0%">
        <stop offset="0%" stop-color="#0A2540" />
        <stop offset="50%" stop-color="#00D4B2" />
        <stop offset="100%" stop-color="#0099FF" />
      </linearGradient>
    </defs>
    <path d="M 25 75 A 38 38 0 1 1 85 40" stroke="url(#mtu-grad)" stroke-width="6" stroke-linecap="round"/>
    <path d="M 22 45 A 28 28 0 0 1 45 22" stroke="#00D4B2" stroke-width="2" stroke-dasharray="4 4" opacity="0.6" stroke-linecap="round"/>
    <circle cx="35" cy="25" r="2.5" fill="#0099FF" />
    <rect x="36" y="52" width="6" height="22" rx="3" fill="#334155" />
    <rect x="47" y="42" width="6" height="32" rx="3" fill="#00D4B2" />
    <rect x="58" y="32" width="6" height="42" rx="3" fill="#0099FF" />
    <path d="M 20 65 L 38 48 L 52 60 L 82 24" stroke="url(#mtu-grad)" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
    <polygon points="82,24 68,23 80,37" fill="#0099FF" />
  </svg>
</p>

# MTU — Monitor de Uso de Tokens

Rastreia tokens por prompt, calcula custo estimado e sugere otimizações. Integra com Claude Code via MCP + hook automático.

## Requisitos

- Python 3.11+
- Docker + Docker Compose
- Claude Code CLI

---

## Instalação rápida

### 1. Clonar e instalar

```bash
git clone <repo> ~/.local/share/mtu
cd ~/.local/share/mtu
uv venv && uv pip install -e .
```

### 2. Subir serviços Docker

```bash
docker compose up -d
```

| Serviço | URL | Descrição |
|---------|-----|-----------|
| Dashboard | http://localhost:7799 | Gráficos e análises |
| SQLite UI | http://localhost:7800 | Browse/query direto no banco |

### 3. Registrar MCP globalmente (todos os projetos)

```bash
claude mcp add \
  --scope user \
  -e "PYTHONPATH=/caminho/para/mtu/src" \
  -- \
  mtu \
  /caminho/para/mtu/.venv/bin/python \
  -m mtu.server
```

Substituir `/caminho/para/mtu` pelo diretório onde clonou.

Verificar: `claude mcp list` — deve mostrar `mtu: ✓ Connected`.

### 4. Adicionar hook Stop (registro automático por prompt)

Adicionar em `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /caminho/para/mtu/hooks/mtu-record-prompt.py",
            "timeout": 5,
            "async": true
          }
        ]
      }
    ]
  }
}
```

Após isso, **cada resposta do Claude é registrada automaticamente** — tokens reais lidos do transcript da sessão, sem configuração adicional.

---

## O que é registrado

Cada turn captura via transcript JSONL da sessão:

| Campo | Fonte |
|-------|-------|
| `input_tokens` | `message.usage.input_tokens` |
| `output_tokens` | `message.usage.output_tokens` |
| `cache_read_tokens` | `message.usage.cache_read_input_tokens` |
| `cache_creation_tokens` | `message.usage.cache_creation_input_tokens` |
| `model` | `message.model` |
| `prompt_preview` | Último user message (300 chars) |
| `project` | `basename(cwd)` |

---

## Alertas inline

Quando o hook detecta padrões problemáticos, imprime na sessão:

| Condição | Alerta |
|----------|--------|
| tokens ativos > 5K | `prompt pesado: NK tokens — considere /compact` |
| tokens ativos > 50K | `ALERTA: NK tokens — contexto crítico, use /compact urgente` |
| cache hit < 60% | `cache hit X% — contexto crescendo sem reuso` |
| output > input e > 3K | `resposta verbose — use caveman mode` |

---

## MCP Tools disponíveis

| Tool | Descrição |
|------|-----------|
| `record_prompt` | Registra manualmente uso de tokens de um prompt |
| `get_usage_report` | Relatório N dias com cache stats |
| `get_top_expensive_prompts` | Prompts mais caros em tokens |
| `get_project_stats` | Breakdown por projeto |
| `analyze_optimization` | Sugestões de otimização baseadas em padrões |
| `sync_claude_stats` | Importa histórico de `~/.claude/stats-cache.json` |
| `set_budget` | Define limite diário de tokens |
| `check_token_budget` | Verifica uso atual vs orçamento |

---

## Estrutura

```text
mtu/
├── docker-compose.yml          # mtu (dashboard) + mtu-db (datasette)
├── Dockerfile
├── hooks/
│   └── mtu-record-prompt.py   # Stop hook — stdlib only, sem dependências
└── src/mtu/
    ├── db.py                   # SQLite (~/.claude/mtu.db)
    ├── analyzer.py             # Métricas + otimização
    ├── server.py               # MCP server (FastMCP)
    └── web/
        ├── app.py              # FastAPI + /api/record
        └── templates/
            └── dashboard.html  # Tailwind dark + Chart.js
```
