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

Rastreia tokens por prompt, calcula custo estimado e sugere otimizações. Integra com Claude Code e Codex via MCP; no Claude Code também há hook automático para captura exata por resposta.

> [!WARNING]
> **Repositório em construção.** Release pública em breve.

## Requisitos

- Python 3.11+
- Docker + Docker Compose
- Claude Code CLI e/ou Codex CLI

---

## Clientes suportados

| Cliente | MCP | Registro automático | Observação |
|---------|-----|---------------------|------------|
| Claude Code | Sim | Sim, via hook `Stop` | Captura tokens reais do transcript JSONL. |
| Codex | Sim | Sim, via sync de `~/.codex/sessions` | Captura tokens reais dos transcripts JSONL do Codex por workspace. O hook `Stop` continua opcional/experimental. |

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

Modelo padrão configurado no Docker: `MTU_DEFAULT_MODEL=gpt-5.5`. Altere essa variável no `docker-compose.yml` se quiser usar outro modelo como padrão para registros manuais/estimados.

O Docker monta `~/.claude` para o banco SQLite e `~/.codex` como leitura para importar os transcripts do Codex.

| Serviço | URL | Descrição |
|---------|-----|-----------|
| Dashboard | http://localhost:7799 | Gráficos, cache stats e otimizações |
| Prompts | http://localhost:7799/prompts | Histórico de prompts com filtros e ordenação |
| SQLite UI | http://localhost:7800 | Browse/query direto no banco |

### 3. Registrar MCP globalmente

Escolha o cliente que vai usar. Pode configurar os dois apontando para a mesma instalação do MTU.

#### Claude Code

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

#### Codex

Via CLI:

```bash
codex mcp add mtu \
  --env "PYTHONPATH=/caminho/para/mtu/src" \
  -- \
  /caminho/para/mtu/.venv/bin/python \
  -m mtu.server
```

Ou edite `~/.codex/config.toml`:

```toml
[mcp_servers.mtu]
command = "/caminho/para/mtu/.venv/bin/python"
args = ["-m", "mtu.server"]

[mcp_servers.mtu.env]
PYTHONPATH = "/caminho/para/mtu/src"
```

Substituir `/caminho/para/mtu` pelo diretório onde clonou.

Verificar no Codex: use `/mcp` na TUI ou `codex mcp --help` para comandos disponíveis.

> [!NOTE]
> Não versione arquivos de configuração MCP com caminhos locais, como `.mcp.json`, quando eles apontarem para `/caminho/para/mtu` ou para a sua home. Cada pessoa deve configurar o MCP no próprio ambiente via `claude mcp add`, `codex mcp add` ou `~/.codex/config.toml`.

### 4. Adicionar hook Stop

#### Claude Code

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

#### Codex

Codex também suporta hooks `Stop`. Para testar o mesmo hook do MTU, adicione em `~/.codex/hooks.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /caminho/para/mtu/hooks/mtu-record-prompt.py",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

Importante: o hook atual foi criado para o payload/transcript do Claude Code. No Codex, o caminho recomendado é usar o sync nativo do MTU, que lê `~/.codex/sessions/**/*.jsonl`. O hook `Stop` pode continuar configurado, mas é opcional e pode encerrar silenciosamente se o evento não fornecer `transcript_path` compatível.

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

No Claude Code, cada turn captura via transcript JSONL da sessão:

| Campo | Fonte |
| ------- | ------- |
| `input_tokens` | `message.usage.input_tokens` |
| `output_tokens` | `message.usage.output_tokens` |
| `cache_read_tokens` | `message.usage.cache_read_input_tokens` |
| `cache_creation_tokens` | `message.usage.cache_creation_input_tokens` |
| `model` | `message.model` |
| `prompt_preview` | Último user message com texto real (300 chars, pula tool_results) |
| `project` | `basename(cwd)` |

No Codex, cada turn é importado de `~/.codex/sessions/**/*.jsonl` durante o startup do MCP/web, no auto-sync do dashboard e no endpoint `/api/sync`:

| Campo | Fonte |
| ------- | ------- |
| `input_tokens` | `last_token_usage.input_tokens - cached_input_tokens` |
| `output_tokens` | `last_token_usage.output_tokens` |
| `cache_read_tokens` | `last_token_usage.cached_input_tokens` |
| `model` | `turn_context.model` ou modelo padrão |
| `prompt_preview` | Último user message antes do token count |
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
| `sync_codex_stats` | Importa histórico de `~/.codex/sessions/**/*.jsonl` |
| `sync_all_stats` | Importa todas as fontes suportadas |
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
