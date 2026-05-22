<p align="center">
  <img src="public/img/mtu.svg" width="200" height="200" alt="MTU logo" />
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
| ------- | ------- |
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
mtu/ /api/record
        └── templates/
            └── dashboard.html  # Tailwind dark + Chart.js
```
