# SuperPromt MCP-сервер

Подключает SuperPromt к агенту **Kodik** (или любому MCP-клиенту) и добавляет к его модели слой
качества — **без сторонних API-ключей**, детерминированно.

## Инструменты
| Инструмент | Что делает |
|-----------|-----------|
| `webbackend_skills(task, k)` | экспертные web/backend-скиллы под задачу (REST-дизайн, FastAPI/Express, React, SQL, аутентификация, безопасность, Docker, тесты) — паттерны, чеклисты, анти-паттерны |
| `psq_prompt_gate(prompt)` | оценка постановки по методике **PSQ**: чеклист CSP-8 + детектор «накрутки» + рекомендации, как превратить сырую задачу в чёткую спецификацию |

## Подключение в Kodik
Через UI: «Добавить MCP-сервер» → указать команду. Или файл `~/.kodik/mcp.json` / `.kodik/mcp.json`:
```json
{ "mcpServers": { "superpromt": { "command": "python3", "args": ["<путь>/mcp/superpromt_mcp.py"] } } }
```
После подключения инструменты доступны агенту как `mcp__superpromt__webbackend_skills` и
`mcp__superpromt__psq_prompt_gate` — агент вызывает их сам перед генерацией кода.

## Протокол
MCP по stdio, JSON-RPC 2.0 (одно сообщение на строку). Только stdlib Python, без зависимостей.
Проверка вручную:
```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | python3 mcp/superpromt_mcp.py
```
