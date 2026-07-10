"""Курированный web/backend скилл-пак + LLM-based ранжирование.
Скиллы лежат в `skills/<name>/SKILL.md`. Ранжирование через LLM-судью для точности."""
import json
import os
import re

_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")
_WORD = re.compile(r"[a-zа-яё0-9]+", re.I)
_cache = None


def _parse(path):
    t = open(path, encoding="utf-8").read()
    name = os.path.basename(os.path.dirname(path))
    m = re.search(r"^description:\s*(.+)$", t, re.M)
    desc = m.group(1).strip() if m else ""
    body = re.sub(r"^---.*?---\s*", "", t, flags=re.S).strip()
    return {"name": name, "desc": desc, "body": body,
            "search": (name.replace("-", " ") + " " + desc + " " + body).lower()}


# порядок в каталоге судьи: САМЫЕ НАСЫЩЕННЫЕ — ВЫШЕ ОСТАЛЬНЫХ (политика владельца):
# универсальные методологии → топ-12 библиотеки (improved) → базовый курированный пак.
PRIORITY = [
    "designer-skills", "knowledge-work", "math-orchestr", "frontend-design",
    "paper-shaders", "frontend-slides", "lottie-animation", "mermaid-diagrams",
    "chartjs-dashboard", "react-native", "godot",
    "writing-runbooks-2", "automating-workspace-workflows", "onboarding-design-system-2",
    "designing-operational-dashboards", "validating-environment-secrets",
    "executing-development-workflows", "managing-git-dag-branches",
    "writing-product-requirements-docs", "running-technology-evaluations",
    "composing-docker-services", "onboarding-codebase", "migrating-databases-2",
]


def load():
    global _cache
    if _cache is None:
        _cache = []
        if os.path.isdir(_DIR):
            for d in sorted(os.listdir(_DIR)):
                p = os.path.join(_DIR, d, "SKILL.md")
                if os.path.isfile(p):
                    _cache.append(_parse(p))
        pri = {n: i for i, n in enumerate(PRIORITY)}
        _cache.sort(key=lambda s: (pri.get(s["name"], len(PRIORITY)), s["name"]))
    return _cache


def rank(task, k=5, model=None, cfg=None):
    """LLM-based ранжирование: судья выбирает МИНИМУМ 5 скиллов, отсортированных по
    релевантности ПО НИСХОДЯЩЕЙ, с приоритетом самых насыщенных (глубокие методологии:
    frontend-design, math-orchestr, …). Возвращает top-k (k>=5)."""
    items = load()
    if not items:
        return []
    k = max(k, 5)                      # политика: на одну задачу — минимум 5 скиллов

    # If no model provided, use TF-IDF fallback
    if not model:
        return _rank_tfidf(task, items, k)

    try:
        from . import providers

        # Build skills catalog for LLM
        catalog = "\n".join(
            f"{i+1}. {s['name']}: {s['desc'][:160]}"
            for i, s in enumerate(items)
        )

        prompt = f"""Ты — expert tech lead. Ранжируй скиллы по релевантности задаче.

ЗАДАЧА: {task}

ДОСТУПНЫЕ СКИЛЛЫ:
{catalog}

Верни ТОЛЬКО JSON-массив из 5–7 имён, ОТСОРТИРОВАННЫЙ ПО РЕЛЕВАНТНОСТИ ПО НИСХОДЯЩЕЙ
(первый = главный скилл задачи): ["skill-1", "skill-2", ...]

Правила ранжирования:
1. ПЕРВЫМ — скилл с прямым совпадением по предмету задачи:
   лендинг/вёрстка/UI/типографика/тёмная тема → frontend-design;
   дизайн/UX/макет/дизайн-система/прототип/редизайн → designer-skills;
   шейдер/анимированный градиент/живой фон/hero-фон/WebGL-эффект → paper-shaders;
   презентация/слайды/доклад/питч/deck → frontend-slides;
   анимация/lottie/микроинтеракция/лоадер/анимированная иконка → lottie-animation;
   диаграмма/схема/флоучарт/архитектура/ER/gantt → mermaid-diagrams;
   дашборд/график данных/KPI/визуализация метрик/аналитика/chart → chartjs-dashboard;
   мобильное приложение/react native/expo/ios/android/апка → react-native;
   игра/godot/платформер/геймплей/спрайт/2d/3d/уровень → godot;
   математика/доказательство/ML-исследование/статистика/научная статья → math-orchestr;
   финансы/юридическое/договор/продажи/PRD-контент/маркетинг/офисная работа → knowledge-work;
   React-компоненты/хуки → react-components;
   REST/эндпоинты/пагинация → rest-api-design; FastAPI/Python-бэкенд → fastapi-backend;
   Node/Express → express-node-backend; SQL/схема/индексы/N+1 → sql-postgres;
   миграция БД → migrating-databases-2; логин/JWT/сессии/роли → auth-jwt;
   XSS/инъекции/CSRF/санитизация → input-validation-security;
   Docker/контейнеры → docker-deploy или composing-docker-services;
   секреты/.env/конфиги → env-secrets-config или validating-environment-secrets;
   тесты/pytest/e2e → api-testing; ранбук/операционная процедура → writing-runbooks-2;
   PRD/требования → writing-product-requirements-docs; выбор технологии → running-technology-evaluations;
   git/ветки → managing-git-dag-branches; вход в чужой код → onboarding-codebase;
   операционный дашборд/метрики → designing-operational-dashboards.
2. Дальше — по убыванию пользы: сначала САМЫЕ НАСЫЩЕННЫЕ методологии (верх каталога:
   designer-skills, knowledge-work, math-orchestr, frontend-design и топ библиотеки) —
   их ставь высоко при любой близости к теме; затем смежные технические, затем
   поддерживающие (безопасность/тесты/деплой — полезный хвост списка).
3. МИНИМУМ 5 имён, максимум 7. Только имена из списка, без пояснений."""

        r = providers.chat(model, [{"role": "user", "content": prompt}],
                          max_tokens=300, temperature=0.0, cfg=cfg, timeout=45)

        # Parse response
        text = r["text"].strip()
        # Extract JSON array
        m = re.search(r'\[.*?\]', text, re.S)
        if m:
            selected_names = json.loads(m.group(0))
            # Match to full skill objects
            name_to_skill = {s["name"]: s for s in items}
            result = []
            for name in selected_names:
                if name in name_to_skill and name not in [r["name"] for r in result]:
                    s = name_to_skill[name]
                    result.append({"name": name, "text": s["body"], "desc": s.get("desc", "")})
            if result:
                # жёсткий пол политики: LLM мог вернуть <5 — допаковать по TF-IDF-релевантности,
                # не ломая порядок судьи (насыщенные/релевантные хвостом, без дублей)
                if len(result) < 5:
                    have = {s["name"] for s in result}
                    for s in _rank_tfidf(task, items, len(items)):
                        if len(result) >= 5:
                            break
                        if s["name"] not in have:
                            have.add(s["name"])
                            result.append(s)
                return result[:k]

    except Exception:
        pass

    # Fallback to TF-IDF
    return _rank_tfidf(task, items, k)


def _rank_tfidf(task, items, k):
    """TF-IDF fallback (быстрый, без LLM)."""
    import math
    q_lower = task.lower()
    q_words = _WORD.findall(q_lower)

    df, docs = {}, []
    for s in items:
        toks = _WORD.findall(s["search"])
        docs.append(toks)
        for w in set(toks):
            df[w] = df.get(w, 0) + 1
    n = len(items)

    def vec(toks):
        tf = {}
        for w in toks:
            tf[w] = tf.get(w, 0) + 1
        return {w: (c / len(toks)) * math.log(1 + n / (1 + df.get(w, 0)))
                for w, c in tf.items()} if toks else {}

    qv = vec(q_words)
    qn = math.sqrt(sum(v * v for v in qv.values())) or 1.0

    scored = []
    for s, toks in zip(items, docs):
        dv = vec(toks)
        dot = sum(qv.get(w, 0.0) * dv.get(w, 0.0) for w in qv)
        if dot > 0:
            dn = math.sqrt(sum(v * v for v in dv.values())) or 1.0
            scored.append((dot / (qn * dn), s))

    scored.sort(key=lambda x: x[0], reverse=True)
    seen = set()
    result = []
    for _, s in scored:
        if s["name"] not in seen:
            seen.add(s["name"])
            result.append({"name": s["name"], "text": s["body"], "desc": s.get("desc", "")})
        if len(result) >= k:
            break
    if len(result) < k:
        # политика «минимум 5 скиллов»: допаковать насыщенными/универсальными в фикс. порядке
        # (детерминизм фолбэка сохраняется — порядок не зависит от сети/рандома)
        pad = ["frontend-design", "math-orchestr", "input-validation-security",
               "api-testing", "env-secrets-config", "rest-api-design"]
        by_name = {s["name"]: s for s in items}
        for name in pad + [s["name"] for s in items]:
            if len(result) >= k:
                break
            if name in by_name and name not in seen:
                seen.add(name)
                result.append({"name": name, "text": by_name[name]["body"],
                               "desc": by_name[name].get("desc", "")})
    return result
