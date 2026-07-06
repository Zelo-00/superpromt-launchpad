"""Трёхуровневая память spt (архитектура CowAgent, адаптирована):
  1. контекст   — сообщения текущей сессии (sqlite, sessions.py);
  2. дневная    — ~/.spt/memory/daily/YYYY-MM-DD.jsonl: события (задачи, вердикты
                  гейтов, уроки, ошибки→исправления);
  3. ядерная    — ~/.spt/memory/core.md: дистиллированные проверенные факты,
                  подгружается в системный промт каждой сессии (≤4000 знаков).
«Deep Dream»-дистилляция: distill() консолидирует дневные логи в ядро по правилу
промоции (self-learning): в ядро попадает только то, что подтверждено проверкой;
догадки помечаются [неподтверждено] или отбрасываются."""
import datetime
import json
import os
import re

from . import config, providers

# анти-отравление ядра (critical-находка SelfLearning): текст задачи персистит в daily → distill →
# core.md → системный промт КАЖДОЙ сессии. Обезвреживаем разметку tool-вызовов и фразы-перехваты
# инструкций ДО записи, чтобы недоверенная задача (в т.ч. из недельного питания) не отравила ядро.
_POISON = re.compile(
    r"</?(?:tool_call|function|invoke|parameter|system|assistant)\b|"
    r"ignore\s+(?:all\s+)?(?:previous|above|prior)\s+instructions?|new\s+instructions?\s*:|"
    r"you\s+are\s+now\b|игнорируй\s+(?:все\s+)?(?:предыдущие|выше|инструкции)|"
    r"забудь\s+(?:все\s+)?инструкции|ты\s+теперь\b|системный\s+промт", re.I)


def _defang(v):
    return _POISON.sub("⟦x⟧", v) if isinstance(v, str) else v

MEM_DIR = os.path.join(config.SPT_DIR, "memory")
CORE = os.path.join(MEM_DIR, "core.md")

DISTILL = """Ты — механизм «Deep Dream» консолидации памяти ИИ-агента.
Ниже: (1) текущее ЯДРО памяти, (2) события за последние дни (jsonl).
Перепиши ядро: устаревшее удали, повторяющееся объедини, новые ВАЖНЫЕ и ПОДТВЕРЖДЁННЫЕ
уроки добавь. Правило промоции: факт входит в ядро только если он был проверен
(тест прошёл, гейт дал вердикт, команда сработала); догадки — только с пометкой
[неподтверждено] и лишь при высокой ценности. Формат: markdown-список ≤ 60 строк,
разделы: Пользователь и предпочтения / Проверенные пути (golden paths) /
Ошибки и как их избегать / Незавершённое. Верни ТОЛЬКО новое ядро.

=== ЯДРО СЕЙЧАС ===
%s

=== СОБЫТИЯ ===
%s"""


def record(kind, payload):
    config.ensure_dir(MEM_DIR)
    config.ensure_dir(os.path.join(MEM_DIR, "daily"))
    day = datetime.date.today().isoformat()
    path = os.path.join(MEM_DIR, "daily", day + ".jsonl")
    ev = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
          "event": kind, **{k: _defang(v) for k, v in payload.items()}}
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    if new:
        config.harden_file(path)  # 0600: дневная память приватна (аудит MEDIUM)


def load_core(limit=4000):
    if os.path.exists(CORE):
        return open(CORE, encoding="utf-8").read()[:limit]
    return ""


def recent_events(days=7, limit_chars=12000):
    out = []
    today = datetime.date.today()
    for d in range(days):
        day = (today - datetime.timedelta(days=d)).isoformat()
        path = os.path.join(MEM_DIR, "daily", day + ".jsonl")
        if os.path.exists(path):
            out.append(open(path, encoding="utf-8").read())
    return "\n".join(out)[-limit_chars:]


def distill(model, cfg=None, days=7):
    """Deep Dream: дневная память -> новое ядро. Возвращает путь к ядру."""
    events = recent_events(days)
    if not events.strip():
        return None
    core_old = load_core(8000)
    r = providers.chat(model, [{"role": "user",
                                "content": DISTILL % (core_old or "(пусто)", events)}],
                       max_tokens=2000, temperature=0.2, cfg=cfg)
    new_core = r["text"].strip()
    if len(new_core) < 40:  # защита от пустой дистилляции
        return None
    os.makedirs(MEM_DIR, exist_ok=True)
    if os.path.exists(CORE):
        os.replace(CORE, CORE + ".bak")
    open(CORE, "w", encoding="utf-8").write(new_core)
    record("distill", {"chars": len(new_core)})
    return CORE
