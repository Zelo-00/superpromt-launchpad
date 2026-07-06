#!/usr/bin/env python3
"""superpromt_mcp.py — MCP-сервер SuperPromt для Kodik (и любого MCP-клиента).

Подключается к агенту Kodik по протоколу MCP и добавляет к ЕГО модели (те самые 250 кредитов) слой
качества SuperPromt — БЕЗ сторонних ключей, детерминированно:
  · webbackend_skills — экспертные web/backend-скиллы (best practices + чеклисты) под задачу;
  · psq_prompt_gate   — оценка постановки задачи по методике PSQ (чеклист CSP-8 + детектор накрутки).

Так продукт живёт ВНУТРИ Kodik: агент сам вызывает эти инструменты перед генерацией кода.
Транспорт: stdio, JSON-RPC 2.0 (одно сообщение на строку). Зависимостей нет — только stdlib.

Подключение в Kodik (~/.kodik/mcp.json или через UI «Добавить MCP-сервер»):
  {"mcpServers": {"superpromt": {"command": "python3", "args": ["<путь>/mcp/superpromt_mcp.py"]}}}
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from superprompt_cli import psq_watchdog, webskills  # noqa: E402

VERSION = "1.0.0"
PROTO = "2024-11-05"

CSP8 = [
    "предметная область (что и где: стек, домен, окружение)",
    "целевая операция (что именно сделать: реализовать/отрефакторить/исправить)",
    "формат выхода (файлы/код/эндпоинты/схема — что вернуть)",
    "критерии качества (верифицируемые: тесты зелёные, линт, ответ 2xx)",
    "контекстные якоря (файлы/данные/версии/срок/объём)",
    "роль исполнителя (напр. senior backend-разработчик)",
    "пример или few-shot (образец ввода/вывода, если уместно)",
    "язык ответа",
]

TOOLS = [
    {"name": "webbackend_skills",
     "description": "Вернуть экспертные web/backend-скиллы (проверенные паттерны, best practices, "
                    "чеклисты, анти-паттерны) под задачу разработки. Вызывай ПЕРЕД написанием кода "
                    "фронтенда или бэкенда, чтобы следовать проверенным практикам (REST-дизайн, "
                    "FastAPI/Express, React, SQL/Postgres, аутентификация, безопасность, Docker, тесты).",
     "inputSchema": {"type": "object", "properties": {
         "task": {"type": "string", "description": "описание задачи разработки"},
         "k": {"type": "integer", "description": "сколько скиллов вернуть (1-5, по умолчанию 3)"}},
         "required": ["task"]}},
    {"name": "psq_prompt_gate",
     "description": "Оценить и помочь улучшить ПОСТАНОВКУ задачи по методике PSQ (Prompt Specification "
                    "Quality): чеклист CSP-8, детектор «накрутки»/пустых маркеров, рекомендации. Вызывай, "
                    "чтобы превратить сырую расплывчатую задачу в чёткую спецификацию ПЕРЕД реализацией.",
     "inputSchema": {"type": "object", "properties": {
         "prompt": {"type": "string", "description": "формулировка задачи для оценки"}},
         "required": ["prompt"]}},
]


def tool_skills(args):
    task = (args.get("task") or "").strip()
    if not task:
        return "Укажи task — описание задачи разработки."
    k = min(max(int(args.get("k", 3) or 3), 1), 5)
    res = webskills.rank(task, k)
    if not res:
        return "Релевантных web/backend-скиллов под эту задачу не нашлось."
    return "\n\n".join("### Скилл: %s\n%s" % (s["name"], s["text"]) for s in res)


def tool_psq(args):
    prompt = (args.get("prompt") or "").strip()
    if not prompt:
        return "Укажи prompt — формулировку задачи."
    g, flags = psq_watchdog.gaming_score(prompt)
    out = ["## PSQ · оценка постановки задачи",
           "Детектор накрутки: %.2f %s" % (
               g, "— есть маркеры-пустышки, переформулируй конкретикой" if g > 0.15 else "— чисто")]
    if flags:
        out.append("Флаги: " + ", ".join(str(f[0] if isinstance(f, (list, tuple)) else f) for f in flags))
    out.append("\n## Чеклист CSP-8 — закрой каждый пункт КОНКРЕТНЫМ проверяемым содержанием (не словом-маркером):")
    out += ["c%d. %s" % (i, it) for i, it in enumerate(CSP8, 1)]
    out.append("\n## Как улучшить\nПерепиши задачу, закрыв все 8 пунктов конкретикой; недостающее заполни "
               "разумным дефолтом с пометкой «(допущение)». Плейсхолдеры, самохвала («эксперт мирового "
               "уровня») и тавтологии («формат: соблюдён») НЕ засчитываются и снижают качество постановки. "
               "Затем выполняй задачу по улучшенной формулировке.")
    return "\n".join(out)


HANDLERS = {"webbackend_skills": tool_skills, "psq_prompt_gate": tool_psq}


def _send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _result(mid, text, is_error=False):
    _send({"jsonrpc": "2.0", "id": mid,
           "result": {"content": [{"type": "text", "text": text}], "isError": is_error}})


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        mid, method = msg.get("id"), msg.get("method")
        if method == "initialize":
            pv = (msg.get("params") or {}).get("protocolVersion") or PROTO
            _send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": pv, "capabilities": {"tools": {}},
                "serverInfo": {"name": "superpromt", "version": VERSION}}})
        elif method == "notifications/initialized":
            continue                                  # уведомление — без ответа
        elif method == "ping":
            _send({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            p = msg.get("params") or {}
            h = HANDLERS.get(p.get("name"))
            if not h:
                _send({"jsonrpc": "2.0", "id": mid,
                       "error": {"code": -32601, "message": "unknown tool: %s" % p.get("name")}})
                continue
            try:
                _result(mid, h(p.get("arguments") or {}))
            except Exception as e:  # noqa: BLE001 — не роняем сервер, отдаём ошибку клиенту
                _result(mid, "ошибка инструмента: " + str(e)[:300], is_error=True)
        elif mid is not None:
            _send({"jsonrpc": "2.0", "id": mid,
                   "error": {"code": -32601, "message": "method not found: %s" % method}})


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, BrokenPipeError):
        pass
