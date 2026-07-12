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


# ── Детерминированные триггеры «подстрока в задаче → скилл» (быстро, без LLM) ──
_SKILL_KW = {
    "frontend-design": ["сайт", "лендинг", "лэндинг", "вёрст", "верст", "страниц", "ui",
        "интерфейс", "типографик", "тёмн тем", "светл тем", "адаптив", "responsive",
        "landing", "website", "site", "page", "hero", "навигац", "одностраничн", "промо",
        "магазин", "shop", "портфолио", "блог", "визитк", "галере"],
    "designer-skills": ["дизайн", "ux", "макет", "прототип", "редизайн", "дизайн-систем",
        "бренд", "эстетик", "красив", "визуал", "стильн", "оформлен", "modern", "premium"],
    "paper-shaders": ["шейдер", "градиент", "живой фон", "анимированн фон", "webgl",
        "hero-фон", "параллакс", "glass", "стекл", "неон", "свеч", "glow", "блик", "aurora"],
    "lottie-animation": ["анимац", "animation", "переход", "transition", "микроинтеракц",
        "лоадер", "loader", "анимированн иконк", "появлен", "hover", "motion", "оживи", "эффект"],
    "frontend-slides": ["презентац", "слайд", "доклад", "питч", "pitch", "deck", "slides"],
    "mermaid-diagrams": ["диаграмм", "флоучарт", "flowchart", "er-диаграм", "gantt", "mermaid",
        "блок-схем", "схему процесс", "архитектурн схем"],
    "chartjs-dashboard": ["дашборд", "dashboard", "график", "kpi", "метрик", "аналитик",
        "chart", "визуализац данн", "статистик", "отчётн панел"],
    "designing-operational-dashboards": ["операционн дашборд", "мониторинг", "observability",
        "алерт", "sre", "incident", "grafana"],
    "react-native": ["react native", "react-native", "expo", "мобильн приложен", "ios",
        "android", "апк", "мобильное приложение"],
    "react-components": ["react", "компонент react", "хук", "jsx", "tsx", "next.js", "nextjs"],
    "godot": ["игр", "game", "godot", "платформер", "геймплей", "спрайт", "аркад", "змейк",
        "snake", "тетрис", "tetris", "2048", "крестики", "пинг-понг", "пинпонг", "судоку",
        "сапёр", "уровень игр"],
    "math-orchestr": ["математик", "доказательств", "теорем", "статистик", "ml-исслед",
        "research", "научн стат", "формул"],
    "knowledge-work": ["финанс", "юридическ", "договор", "продаж", "маркетинг", "офисн",
        "отчёт для", "письмо клиент", "бизнес-план", "стратег", "коммерческ предложен",
        "статья", "статью", "эссе", "оглавлен", "лонгрид", "блог-пост", "гайд", "руководств",
        "реферат", "конспект", "обзор", "напиши текст", "документ"],
    "writing-product-requirements-docs": ["prd", "требован к продукт", "product requirements",
        "спецификац продукт", "user stor"],
    "fastapi-backend": ["fastapi", "python-бэкенд", "питон-бэкенд", "питон api", "бэкенд на python"],
    "express-node-backend": ["express", "node.js", "nodejs", "node-бэкенд", "бэкенд на node"],
    "rest-api-design": ["rest", "эндпоинт", "endpoint", "пагинац", "api-дизайн", "openapi"],
    "sql-postgres": ["sql", "postgres", "postgresql", "база данных", "схема таблиц", "индекс бд", "n+1"],
    "migrating-databases-2": ["миграц бд", "db migration", "alembic", "liquibase", "flyway"],
    "auth-jwt": ["логин", "авторизац", "jwt", "сесси", "аутентификац", "oauth", "роли доступ"],
    "input-validation-security": ["xss", "инъекц", "csrf", "санитизац", "валидац ввод", "защит форм"],
    "env-secrets-config": ["секрет", ".env", "конфиг окружен", "переменн окружен"],
    "validating-environment-secrets": ["проверк секрет", "валидац env", "утечк секрет"],
    "docker-deploy": ["docker", "контейнер", "dockerfile", "деплой в контейнер"],
    "composing-docker-services": ["docker compose", "docker-compose", "compose-файл", "мультиконтейнер"],
    "api-testing": ["pytest", "e2e", "автотест", "api-тест", "тестировани api", "unit-тест"],
    "writing-runbooks-2": ["ранбук", "runbook", "операционн процедур"],
    "running-technology-evaluations": ["выбор технолог", "сравнени технолог", "какой стек"],
    "managing-git-dag-branches": ["git", "ветк", "rebase", "merge-конфликт"],
    "onboarding-codebase": ["вход в чужой код", "onboarding в код", "legacy-код", "разобрат в проект"],
    "onboarding-design-system-2": ["дизайн-систем", "компонентн библиотек", "storybook"],
    "automating-workspace-workflows": ["автоматизац рабоч", "workflow-автоматизац"],
    "executing-development-workflows": ["dev workflow", "процесс разработк"],
}
# признаки веб/визуальной задачи → базовый буст визуальному ядру (даже без прямых слов)
_WEB_HINT = ["сайт", "лендинг", "страниц", "landing", "site", "page", "website", "веб",
             "промо", "портфолио", "магазин", "shop", "галере", "блог", "визитк"]


def _rank_keywords(task, items, k):
    """Детерминированный ранкер: подстроки-триггеры + буст визуального ядра для веб-задач."""
    t = " " + (task or "").lower() + " "
    names = {s["name"] for s in items}
    score = {}
    for name, kws in _SKILL_KW.items():
        if name not in names:
            continue
        hits = sum(1 for kw in kws if kw in t)
        if hits:
            score[name] = score.get(name, 0) + hits * 2
    if any(h in t for h in _WEB_HINT):
        for name, boost in (("frontend-design", 5), ("designer-skills", 2),
                            ("paper-shaders", 2), ("lottie-animation", 2)):
            if name in names:
                score[name] = score.get(name, 0) + boost
    # даже если ничего не совпало — не возвращаем пусто и НЕ уходим в галлюцинирующий LLM:
    # ниже добьём детерминированно из PRIORITY (осмысленные методологии).
    pri = {n: i for i, n in enumerate(PRIORITY)}
    ranked = sorted(score.items(), key=lambda kv: (-kv[1], pri.get(kv[0], len(PRIORITY))))
    by_name = {s["name"]: s for s in items}
    result = [{"name": n, "text": by_name[n]["body"], "desc": by_name[n].get("desc", "")}
              for n, _ in ranked]
    if len(result) < 5:                     # добить минимум 5 «насыщенными» методологиями (PRIORITY), не шумом
        have = {r["name"] for r in result}
        for name in PRIORITY:
            if len(result) >= 5:
                break
            if name in by_name and name not in have:
                have.add(name)
                result.append({"name": name, "text": by_name[name]["body"],
                               "desc": by_name[name].get("desc", "")})
    return result[:max(k, 5)]


def _rank_llm_constrained(task, candidates, k, model, cfg):
    """LLM упорядочивает k лучших СТРОГО из детерминированного шортлиста — без галлюцинаций:
    любое имя вне шортлиста отбрасывается, недостача добивается детерминированным порядком."""
    try:
        from . import providers
        catalog = "\n".join(f"- {c['name']}: {(c.get('desc') or '')[:140]}" for c in candidates)
        prompt = (
            "Ты — tech lead. Упорядочь по релевантности задаче ЛУЧШИЕ скиллы СТРОГО из списка "
            f"ниже. Использовать ТОЛЬКО имена из списка, ничего не выдумывать.\n\n"
            f"ЗАДАЧА: {task}\n\nСПИСОК (только эти имена разрешены):\n{catalog}\n\n"
            f"Верни ТОЛЬКО JSON-массив из {max(k, 5)} имён из списка, по убыванию релевантности.")
        r = providers.chat(model, [{"role": "user", "content": prompt}],
                           max_tokens=200, temperature=0.0, cfg=cfg, timeout=30)
        m = re.search(r"\[.*?\]", r["text"], re.S)
        if not m:
            return []
        picked = json.loads(m.group(0))
        by_name = {c["name"]: c for c in candidates}
        seen, out = set(), []
        for name in picked:
            if name in by_name and name not in seen:        # анти-галлюцинация: только из шортлиста
                seen.add(name)
                out.append(by_name[name])
        for c in candidates:                                 # добить детерминированным порядком
            if len(out) >= max(k, 5):
                break
            if c["name"] not in seen:
                seen.add(c["name"])
                out.append(c)
        return out[:max(k, 5)]
    except Exception:                                        # noqa: BLE001 — фолбэк на детерминированный
        return []


def rank(task, k=5, model=None, cfg=None):
    """LLM-based ранжирование: судья выбирает МИНИМУМ 5 скиллов, отсортированных по
    релевантности ПО НИСХОДЯЩЕЙ, с приоритетом самых насыщенных (глубокие методологии:
    frontend-design, math-orchestr, …). Возвращает top-k (k>=5)."""
    items = load()
    if not items:
        return []
    k = max(k, 5)                      # политика: на одну задачу — минимум 5 скиллов

    # Детерминированный шортлист по ключевым словам (RU-запрос → EN-скиллы, без галлюцинаций).
    # Если задан model — LLM уточняет порядок СТРОГО внутри шортлиста (выдумать нельзя).
    cand = _rank_keywords(task, items, max(2 * k, 10))
    if cand:
        if model:
            refined = _rank_llm_constrained(task, cand, k, model, cfg)
            if refined:
                return refined
        return cand[:max(k, 5)]

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
