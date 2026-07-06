"""Самообучение spt (механика self-learning + агент-обучатель).

1. harvest() — после задачи: если путь был «выстрадан» (были ремонты гейтов,
   ошибки инструментов с последующим успехом) и выполняется правило промоции
   (есть ПРОШЕДШАЯ проверка + именованный паттерн ошибки + отброшенный тупик) —
   LLM извлекает golden path в скилл ~/.spt/skills/<name>.md. Иначе — заметка
   в дневную память (уровень 2), не скилл.
2. teach() — агент-обучатель: читает дневные логи, статистику гейтов и созданные
   скиллы; улучшает слабые скиллы, обновляет СВОЮ инструкцию (~/.spt/teacher.md)
   — самообучение обучателя. Запускать вручную или еженедельно (cron)."""
import datetime
import json
import os
import re

from . import config, memory, providers

SKILLS_DIR = os.path.join(config.SPT_DIR, "skills")
TEACHER_MD = os.path.join(config.SPT_DIR, "teacher.md")
CREATIVE_MD = os.path.join(config.SPT_DIR, "creative.md")

CREATIVE_DEFAULT = """# Агент-креативщик spt (v1)
Роль: синтезирую новые идеи/продукты из знаний (дайджест трендов+науки × наша система),
самообучаюсь на судьбе собственных прошлых идей.
Принципы: (1) идея = синтез двух источников, а не пересказ одного; (2) у идеи есть
проверяемый первый шаг (что сделать за час, чтобы проверить ценность); (3) непроверенные
гипотезы помечаю [неподтверждено]; (4) ревизия: прошлые идеи без движения ≥2 циклов —
списываю с уроком «почему не взлетела»; (5) уникальность: прежде чем предлагать — ищу,
не существует ли уже (иначе это не синтез, а находка)."""

TEACHER_DEFAULT = """# Агент-обучатель spt (v1)
Роль: анализирую прогоны, обучаю остальных агентов/скиллы, самообучаюсь.
Принципы: (1) правило промоции — в скилл только проверенное (чек прошёл, назван
паттерн ошибки, есть отброшенный тупик); (2) фиксирую и провалы — тупики ценнее
golden path; (3) секреты в скиллы не пишу — только ГДЕ они лежат; (4) дедуп —
обновляю существующий скилл, а не плоду дубль; (5) выводы через KSCR-гейт: не
выдаю неподтверждённое за проверенное."""

HARVEST = """Ты — механизм самообучения (harvest golden path). Ниже журнал выполнения задачи.
Правило промоции (все 3 обязательны): 1) есть ПРОШЕДШАЯ проверка (тест/гейт/команда);
2) назван паттерн ошибки, который путь обходит; 3) есть хотя бы один отброшенный тупик.
Если правило НЕ выполняется — ответь ровно: NOT_PROMOTABLE: <причина одной строкой>.
Если выполняется — верни скилл в формате markdown с frontmatter:
---
name: <kebab-case>
description: <когда применять, 1-2 предложения>
---
# <название>
## Golden path
<шаги: точные команды/пути/порядок>
## Что НЕ сработало
<тупики и почему>
## Проверка
<как убедиться, что путь работает>
Секретные ЗНАЧЕНИЯ не включай — только где лежат.

=== ЖУРНАЛ ===
%s"""

TEACH = """%s

Ты — этот агент-обучатель. Ниже данные для урока:
(A) события за 7 дней (гейты, ремонты, ошибки), (B) текущие скиллы (имена+описания),
(C) свежий дайджест развития (тренды GitHub + наука), если есть.
Сделай:
1. ДИАГНОЗ: 3-5 главных слабостей системы по данным (конкретно, со ссылкой на события).
2. УЛУЧШЕНИЯ СКИЛЛОВ: для 1-2 скиллов — конкретный патч (имя скилла + новый текст раздела).
3. САМООБУЧЕНИЕ: 1-3 новых принципа для ТВОЕЙ инструкции (если данные это оправдывают).
4. ИДЕИ ДЛЯ КРЕАТИВЩИКА: 2-4 идеи-синтеза «знание из дайджеста × наша система» — что
   уникального можно создать/встроить; помечай непроверенные гипотезы [неподтверждено].
Ответь JSON: {"diagnosis":[...], "skill_patches":[{"name":"...","section":"...","text":"..."}],
"self_update":["принцип", ...], "ideas":["идея", ...]}

=== A: СОБЫТИЯ ===
%s

=== B: СКИЛЛЫ ===
%s

=== C: ДАЙДЖЕСТ ===
%s"""

IDEAS_MD = os.path.expanduser(
    "~/metodika/PromtMaster/knowledge_base/creative_ideas/product.md")


def _latest_digest(limit_chars=6000):
    # queue лежит рядом с пакетом (product/parsers/queue) — портируемо
    qdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "parsers", "queue")
    if not os.path.isdir(qdir):
        return ""
    files = sorted(f for f in os.listdir(qdir) if f.startswith("tasks_"))
    if not files:
        return ""
    return open(os.path.join(qdir, files[-1]), encoding="utf-8").read()[:limit_chars]


def _slug(text):
    s = re.sub(r"[^a-z0-9а-яё]+", "-", text.lower()).strip("-")
    return s[:50] or "skill"


def harvest(journal, model, cfg=None):
    """Журнал прогона -> скилл или заметка в память. Возвращает (status, path|reason)."""
    r = providers.chat(model, [{"role": "user", "content": HARVEST % journal[-12000:]}],
                       max_tokens=1500, temperature=0.2, cfg=cfg)
    text = r["text"].strip()
    if text.startswith("NOT_PROMOTABLE"):
        memory.record("lesson_note", {"note": text[:500]})
        return "note", text
    m = re.search(r"name:\s*([a-z0-9\-а-яё]+)", text)
    name = m.group(1) if m else _slug(text.splitlines()[0] if text else "skill")
    os.makedirs(SKILLS_DIR, exist_ok=True)
    path = os.path.join(SKILLS_DIR, name + ".md")
    open(path, "w", encoding="utf-8").write(text)
    memory.record("skill_harvested", {"skill": name, "path": path})
    return "skill", path


def list_skills():
    if not os.path.isdir(SKILLS_DIR):
        return []
    out = []
    for fn in sorted(os.listdir(SKILLS_DIR)):
        if fn.endswith(".md"):
            head = open(os.path.join(SKILLS_DIR, fn), encoding="utf-8").read(400)
            m = re.search(r"description:\s*(.+)", head)
            out.append((fn[:-3], (m.group(1).strip() if m else "")[:120]))
    return out


def teacher_instruction():
    if os.path.exists(TEACHER_MD):
        return open(TEACHER_MD, encoding="utf-8").read()
    os.makedirs(config.SPT_DIR, exist_ok=True)
    open(TEACHER_MD, "w", encoding="utf-8").write(TEACHER_DEFAULT)
    return TEACHER_DEFAULT


CREATIVE_CYCLE = """%s

Ты — этот агент-креативщик. Еженедельный цикл самообучения. Данные:
(A) свежий дайджест развития (тренды GitHub + наука),
(B) ядро памяти системы,
(C) ТВОИ прошлые идеи (хвост базы идей) — оцени их судьбу критически.
Сделай:
1. РЕВИЗИЯ: какие из прошлых идей мертвы/устарели (и почему — это твой урок).
2. СИНТЕЗ: 3-5 НОВЫХ идей «знание из дайджеста × наша система» — уникальных, с
   проверяемым первым шагом; гипотезы помечай [неподтверждено].
3. САМООБУЧЕНИЕ: 1-2 новых принципа для ТВОЕЙ инструкции, выведенных из ревизии
   (только если ревизия это оправдывает — не выдумывай принципы ради принципов).
Ответь JSON: {"revision":[{"idea":"...","fate":"мертва/жива","lesson":"..."}],
"ideas":["..."], "self_update":["..."]}

=== A: ДАЙДЖЕСТ ===
%s

=== B: ЯДРО ПАМЯТИ ===
%s

=== C: ПРОШЛЫЕ ИДЕИ ===
%s"""


def creative_instruction():
    if os.path.exists(CREATIVE_MD):
        return open(CREATIVE_MD, encoding="utf-8").read()
    os.makedirs(config.SPT_DIR, exist_ok=True)
    open(CREATIVE_MD, "w", encoding="utf-8").write(CREATIVE_DEFAULT)
    return CREATIVE_DEFAULT


def creative_cycle(model, cfg=None):
    """Еженедельное самообучение креативщика: ревизия своих идей → синтез → самообновление."""
    digest = _latest_digest() or "(нет)"
    core = memory.load_core() or "(пусто)"
    past = ""
    if os.path.exists(IDEAS_MD):
        past = open(IDEAS_MD, encoding="utf-8").read()[-6000:]
    r = providers.chat(model, [{"role": "user", "content":
                                CREATIVE_CYCLE % (creative_instruction(), digest,
                                                  core, past or "(ещё нет)")}],
                       max_tokens=2500, temperature=0.6, cfg=cfg, json_mode=True)
    data = providers.parse_json(r["text"])       # структурный JSON + устойчивый фолбэк (П.10)
    if not isinstance(data, dict):
        return None
    ideas = [i for i in data.get("ideas", []) if isinstance(i, str) and i.strip()]
    if ideas:
        os.makedirs(os.path.dirname(IDEAS_MD), exist_ok=True)
        with open(IDEAS_MD, "a", encoding="utf-8") as f:
            f.write("\n## Креативщик, цикл %s\n" % datetime.date.today().isoformat())
            for i in ideas:
                f.write("- %s\n" % i.strip())
    ups = [u for u in data.get("self_update", []) if isinstance(u, str) and u.strip()]
    if ups:
        with open(CREATIVE_MD, "a", encoding="utf-8") as f:
            f.write("\n## Выучено %s\n" % datetime.date.today().isoformat())
            for u in ups:
                f.write("- %s\n" % u.strip())
    memory.record("creative_cycle", {"n_ideas": len(ideas), "self_update": ups,
                                     "revision": data.get("revision", [])[:5]})
    return data


def teach(model, cfg=None):
    """Один цикл обучателя. Возвращает разбор (dict) или None."""
    events = memory.recent_events(7)
    if not events.strip():
        return None
    skills = "\n".join("%s — %s" % (n, d) for n, d in list_skills()) or "(нет)"
    digest = _latest_digest() or "(нет)"
    r = providers.chat(model, [{"role": "user", "content":
                                TEACH % (teacher_instruction(), events, skills, digest)}],
                       max_tokens=2500, temperature=0.3, cfg=cfg, json_mode=True)
    data = providers.parse_json(r["text"])       # структурный JSON + устойчивый фолбэк (П.10)
    if not isinstance(data, dict):
        return None
    # применить патчи скиллов
    for patch in data.get("skill_patches", []):
        path = os.path.join(SKILLS_DIR, patch.get("name", "") + ".md")
        if os.path.exists(path) and patch.get("text"):
            with open(path, "a", encoding="utf-8") as f:
                f.write("\n\n## [обучатель %s] %s\n%s\n" %
                        (datetime.date.today().isoformat(),
                         patch.get("section", "улучшение"), patch["text"]))
    # самообучение: дописать принципы в собственную инструкцию
    ups = [u for u in data.get("self_update", []) if isinstance(u, str) and u.strip()]
    if ups:
        with open(TEACHER_MD, "a", encoding="utf-8") as f:
            f.write("\n## Выучено %s\n" % datetime.date.today().isoformat())
            for u in ups:
                f.write("- %s\n" % u.strip())
    # идеи → база креативщика (корм для синтеза новых продуктов)
    ideas = [i for i in data.get("ideas", []) if isinstance(i, str) and i.strip()]
    if ideas and os.path.isdir(os.path.dirname(IDEAS_MD)):
        with open(IDEAS_MD, "a", encoding="utf-8") as f:
            f.write("\n## От обучателя, %s\n" % datetime.date.today().isoformat())
            for i in ideas:
                f.write("- %s\n" % i.strip())
    memory.record("teacher_cycle", {"diagnosis": data.get("diagnosis", [])[:5],
                                    "patched": [p.get("name") for p in
                                                data.get("skill_patches", [])],
                                    "self_update": ups, "ideas": ideas[:4]})
    return data
