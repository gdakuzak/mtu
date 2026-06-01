<p align="center">
  <img src="public/img/mtu.svg" width="200" height="200" alt="MTU logo" />
</p>

<p align="center">
  <strong>Português</strong> · <a href="README.en.md">English</a>
</p>

# MTU — Monitoring Token Usage

| | |
|---|---|
| **M** — Monitoring (Real-Time) | Rastreia cada requisição LLM e custo no exato momento em que acontece. |
| **T** — Token Analytics | Análise profunda de métricas de prompt, completion e por modelo. |
| **U** — Usage Guardrails | Defina orçamentos rígidos, alertas automáticos e evite surpresas na fatura da API. |

Rastreia tokens por prompt, calcula custo estimado e sugere otimizações. Integra com Claude Code via MCP + hook automático.

> [!WARNING]
> **Repositório em construção.** Release pública em breve.

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
| Dashboard | http://localhost:7799 | Gráficos, cache stats e otimizações |
| Prompts | http://localhost:7799/prompts | Histórico de prompts com filtros e ordenação |
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

## Atualização

### Manual

```bash
make update
```

Faz `git pull` + rebuild + redeploy. Mostra versão anterior → nova e lista de commits.

### Automática (cron)

```bash
make setup-auto-update   # instala cron job (verifica hourly)
make remove-auto-update  # remove
```

Intervalo de update configurável via `MTU_UPDATE_DAYS` (default: 7 dias). Só rebuilda quando detecta versão nova no upstream — sem rebuild desnecessário.

---

## O que é registrado

Cada turn captura via transcript JSONL da sessão:

| Campo | Fonte |
| ------- | ------- |
| `input_tokens` | `message.usage.input_tokens` |
| `output_tokens` | `message.usage.output_tokens` |
| `cache_read_tokens` | `message.usage.cache_read_input_tokens` |
| `cache_creation_tokens` | `message.usage.cache_creation_input_tokens` |
| `model` | `message.model` |
| `prompt_preview` | Último user message com texto real (300 chars, pula tool_results) |
| `project` | `basename(cwd)` |

---

## Interface Web

### Dashboard (`/`)

- Stats do dia: tokens, custo, sessões, cache hit rate
- Gráfico de tokens/custo por dia (7/14/30 dias)
- Cache stats por modelo (lifetime)
- Sugestões de otimização
- Tabela dos prompts mais pesados com preview truncado (clique abre modal completo)
- Breakdown por projeto (30 dias)
- Auto-sync a cada 30s com countdown

### Prompts (`/prompts`)

- Histórico completo de prompts registrados
- Filtros: projeto, modelo, intervalo de datas
- Ordenação clicável em todas as colunas (Data, Projeto, Modelo, Input, Output, Cache, Custo)
- Paginação "Carregar mais" (50 por vez, server-side)
- Modal com prompt completo ao clicar em qualquer linha
- Imagens sanitizadas automaticamente (base64/img tags removidos)

---

## Alertas inline

Quando o hook detecta padrões problemáticos, imprime na sessão:

| Condição | Alerta |
| ---------- | -------- |
| tokens ativos > 5K | `prompt pesado: NK tokens — considere /compact` |
| tokens ativos > 50K | `ALERTA: NK tokens — contexto crítico, use /compact urgente` |
| cache hit < 60% | `cache hit X% — contexto crescendo sem reuso` |
| output > input e > 3K | `resposta verbose — use caveman mode` |

---

## MCP Tools disponíveis

| Tool | Descrição |
| ------ | ----------- |
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
├── hooks/
│   └── mtu-record-prompt.py   # Hook Stop — lê transcript, POST para API
├── src/mtu/
│   ├── db.py                  # SQLite + pricing
│   ├── analyzer.py            # Stats, breakdown, otimização
│   ├── server.py              # MCP server (FastMCP)
│   └── web/
│       ├── app.py             # FastAPI — API + rotas HTML
│       └── templates/
│           ├── dashboard.html # Dashboard principal
│           └── prompts.html   # Histórico de prompts
├── scripts/
│   ├── release.sh             # Bump versão + changelog + tag git
│   └── auto-update.sh         # Update via git pull + rebuild (omz-inspired)
├── Makefile                   # Targets: release-*, update, setup-auto-update
├── docker-compose.yml
└── pyproject.toml
```
