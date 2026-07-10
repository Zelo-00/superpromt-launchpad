"""PSQ-гейт с интеграцией LLM-based ранжирования скиллов.
Объединяет оценку качества промта (PSQ) с подбором лучших скиллов для задачи.
Конкурсный режим: PSQ + Skills + KSCR = полный конвейер."""
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
автоматически (KSCR link-гейт), мёртвая ссылка = ВЕТО.
Верни ТОЛЬКО текст промта.

СЫРАЯ ЗАДАЧА:
<<<
%s
>>>"""

# ─── Prompt для выбора скиллов (из webskills.py) ───
SKILLS_PROMPT = """Ты — expert tech lead. Ранжируй скиллы по релевантности задаче.

ЗАДАЧА: {task}

ДОСТУПНЫЕ СКИЛЛЫ:
{catalog}

Верни ТОЛЬКО JSON-массив из 5–7 имён, ОТСОРТИРОВАННЫЙ ПО РЕЛЕВАНТНОСТИ ПО НИСХОДЯЩЕЙ
(первый = главный скилл задачи): ["skill-1", "skill-2", ...]

Правила ранжирования:
1. ПЕРВЫМ — скилл с прямым совпадением по предмету задачи:
   лендинг/вёрстка/UI/типографика → frontend-design;
   дизайн/UX/макет/дизайн-система → designer-skills;
   математика/доказательство/ML → math-orchestr;
   финансы/юридическое/PRD/маркетинг → knowledge-work;
   React-компоненты/хуки → react-components;
   REST/эндпоинты → rest-api-design; FastAPI/Python-бэкенд → fastapi-backend;
   Node/Express → express-node-backend; SQL/схема/индексы → sql-postgres;
   Docker/контейнеры → docker-deploy;
   тесты/pytest/e2e → api-testing.
2. Дальше — по убыванию пользы: сначала САМЫЕ НАСЫЩЕННЫЕ методологии,
   затем смежные технические, затем поддерживающие (безопасность/тесты/деплой).
3. МИНИМУМ 5 имён, максимум 7. Только имена из списка, без пояснений."""


def _parse_json(text):
    return providers.parse_json(text)


def score(prompt, judge_model, cfg=None):
    """-> {'psq','raw_psq','c','a','gaming','flags'}"""
    r = providers.chat(judge_model, [{"role": "user", "content": JUDGE % prompt}],
                       max_tokens=800, temperature=0.0, cfg=cfg, timeout=180, json_mode=False)
    data = _parse_json(r["text"]) or {"c": [0] * 8, "a": 1.0}
    c = [1 if x else 0 for x in (data.get("c") or [0] * 8)][:8]
    a = max(0.0, min(1.0, float(data.get("a", 1.0))))
    raw = (sum(c) / 8.0) * (1 - 0.5 * a)
    wd = psq_watchdog.apply(raw, prompt)
    return {"psq": wd["psq_out"], "raw_psq": round(raw, 3),
            "c": c, "a": a, "gaming": wd["gaming_score"], "flags": wd["flags"]}


def repair(task, model, cfg=None):
    r = providers.chat(model, [{"role": "user", "content": REPAIR % task}],
                       max_tokens=1500, temperature=0.3, cfg=cfg)
    return r["text"].strip()


def prescreen(task):
    """Детерминированный pre-скрининг."""
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
        return task, s0, s0
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


def select_skills(task, model, cfg=None, k=5):
    """LLM-based выбор скиллов для задачи (из webskills.py).
    Возвращает список {'name', 'text'} отсортированных по релевантности."""
    try:
        from . import webskills
        return webskills.rank(task, k=k, model=model, cfg=cfg)
    except Exception:
        return []


def score_with_skills(prompt, task, judge_model, skills=None, cfg=None):
    """Комбинированная оценка: PSQ + Skills.
    Возвращает {'psq': ..., 'skills': [...], 'psq_before': ..., 'psq_after': ...}"""
    # 1. PSQ оценка
    psq_result = score(prompt, judge_model, cfg)
    
    # 2. Если скиллы не переданы — выбираем через LLM
    if skills is None:
        skills = select_skills(task, judge_model, cfg)
    
    return {
        "psq": psq_result["psq"],
        "raw_psq": psq_result["raw_psq"],
        "c": psq_result["c"],
        "a": psq_result["a"],
        "gaming": psq_result["gaming"],
        "flags": psq_result["flags"],
        "skills": skills,
        "skills_count": len(skills),
    }


def gate_with_skills(task, judge_model, repair_model, max_cycles=1, cfg=None, log=print):
    """Полный PSQ-гейт с выбором скиллов.
    Возвращает (final_prompt, psq_before, psq_after, skills)"""
    # 1. Выбираем скиллы
    skills = select_skills(task, judge_model, cfg)
    log("скиллы: %s" % ", ".join(s["name"] for s in skills[:5]))
    
    # 2. PSQ гейт
    final_prompt, psq_before, psq_after = gate(task, judge_model, repair_model,
                                                 max_cycles=max_cycles, cfg=cfg, log=log)
    
    return final_prompt, psq_before, psq_after, skills
