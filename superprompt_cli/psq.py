"""PSQ-гейт входа (v3 = LLM-судья v2 + детерминированный watchdog).
PSQ = (Σcᵢ/8)·(1−0.5·a), затем штраф watchdog: psq·(1−min(0.9, gaming)).
Порог 0.80. Ремонт: переписать промт по CSP-8, помечая допущения."""
import json
import re

from . import providers
from . import psq_watchdog

THRESHOLD = 0.80

JUDGE = """Ты — строгий оценщик качества постановки промта (PSQ, рубрика v2, анти-накрутка).
Оцени ПРОМТ по чеклисту CSP-8. cᵢ=1 ТОЛЬКО если пункт задан КОНКРЕТНЫМ проверяемым содержанием
(процитируй фрагмент). Слова-маркеры («формат: соблюдён»), плейсхолдеры, самохвала — cᵢ=0.
c1 предметная область; c2 целевая операция; c3 формат выхода; c4 верифицируемые критерии качества;
c5 контекстные якоря (файлы/данные/срок/объём); c6 роль; c7 пример/few-shot; c8 язык ответа.
a ∈ [0,1] — двусмысленность (0 = однозначно).
Ответь ТОЛЬКО JSON: {"c":[0|1 ×8],"a":0.0,"evidence":{"c1":"цитата или пусто",...}}

ПРОМТ ДЛЯ ОЦЕНКИ:
<<<
%s
>>>"""

REPAIR = """Ты — Создатель идеального промта (конвейер SuperPromt). Перепиши сырую задачу в
идеальный промт по CSP-8: c1 предметная область, c2 целевая операция, c3 формат выхода,
c4 верифицируемые критерии качества, c5 контекстные якоря, c6 роль, c7 краткий пример,
c8 язык. Каждый пункт — конкретным содержанием (не словом-маркером). Недостающее заполни
разумными дефолтами и пометь «(допущение)». Без воды и самохвалы.
ОБЯЗАТЕЛЬНО включи в критерии качества анти-фабрикационное правило ссылок: URL/DOI указывать
только при полной уверенности, иначе пометка [НЕПРОВЕРЕНО]; все ссылки будут проверены
автоматически (link-гейт выхода), мёртвая ссылка = ВЕТО.
Верни ТОЛЬКО текст промта.

СЫРАЯ ЗАДАЧА:
<<<
%s
>>>"""


def _parse_json(text):
    return providers.parse_json(text)   # устойчивый парсинг (П.10), fallback ниже


def score(prompt, judge_model, cfg=None):
    """-> {'psq','raw_psq','c','a','gaming','flags'}"""
    r = providers.chat(judge_model, [{"role": "user", "content": JUDGE % prompt}],
                       max_tokens=800, temperature=0.0, cfg=cfg, timeout=180, json_mode=False)
    # fail-closed: непарсибельный вывод судьи → худший балл (c=0, a=1) ⇒ ремонт, не ложный PASS
    data = _parse_json(r["text"]) or {"c": [0] * 8, "a": 1.0}
    c = [1 if x else 0 for x in (data.get("c") or [0] * 8)][:8]
    a = max(0.0, min(1.0, float(data.get("a", 1.0))))
    raw = (sum(c) / 8.0) * (1 - 0.5 * a)
    wd = psq_watchdog.apply(raw, prompt)
    return {"psq": wd["psq_out"], "raw_psq": round(raw, 3),
            "c": c, "a": a, "gaming": wd["gaming_score"], "flags": wd["flags"]}


def repair(task, model, cfg=None):
    # 4096: у reasoning-моделей (напр. deepseek-v4-pro) большой reasoning_content съедает
    # бюджет — при малом лимите content выходит пустым. Даём место под размышления + ответ.
    r = providers.chat(model, [{"role": "user", "content": REPAIR % task}],
                       max_tokens=4096, temperature=0.3, cfg=cfg)
    return r["text"].strip()


def prescreen(task):
    """Детерминированный pre-скрининг: судья не нужен, когда исход предрешён.
    (а) watchdog: при g>0.2 psq_out = raw·(1−g) < 0.8 при ЛЮБОМ вердикте судьи
        (следствие формулы, не эвристика);
    (б) слишком короткая задача физически не содержит 8 конкретных CSP-пунктов.
    -> dict-оценка или None (нужен судья)."""
    g, flags = psq_watchdog.gaming_score(task)
    if g > 0.2:
        return {"psq": round(1 - g, 3), "raw_psq": None, "c": [0] * 8, "a": 1.0,
                "gaming": round(g, 2), "flags": flags, "prescreen": "watchdog"}
    if len(task.strip()) < 40:
        return {"psq": 0.3, "raw_psq": None, "c": [0] * 8, "a": 1.0,
                "gaming": 0.0, "flags": [], "prescreen": "short"}
    return None


def gate(task, judge_model, repair_model, max_cycles=1, cfg=None, log=print):
    """PSQ-гейт с ремонтом. -> (final_prompt, before, after)"""
    s0 = prescreen(task) or score(task, judge_model, cfg)
    if s0["psq"] >= THRESHOLD:
        return task, s0, s0  # гейт-до-ремонта: хорошее не переписываем (−37% токенов)
    best_prompt, best = task, s0
    for i in range(max_cycles):
        cand = repair(task if i == 0 else best_prompt, repair_model, cfg)
        s = score(cand, judge_model, cfg)
        log("ремонт %d → PSQ %.2f" % (i + 1, s["psq"]))
        if s["psq"] > best["psq"]:
            best_prompt, best = cand, s
        if best["psq"] >= THRESHOLD:
            break
    return best_prompt, s0, best
