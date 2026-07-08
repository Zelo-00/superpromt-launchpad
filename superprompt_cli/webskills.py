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


def load():
    global _cache
    if _cache is None:
        _cache = []
        if os.path.isdir(_DIR):
            for d in sorted(os.listdir(_DIR)):
                p = os.path.join(_DIR, d, "SKILL.md")
                if os.path.isfile(p):
                    _cache.append(_parse(p))
    return _cache


def rank(task, k=5, model=None, cfg=None):
    """LLM-based ранжирование: отправляет задачу + список скиллов LLM-судье,
    который выбирает наиболее релевантные. Возвращает top-k скиллов."""
    items = load()
    if not items:
        return []

    # If no model provided, use TF-IDF fallback
    if not model:
        return _rank_tfidf(task, items, k)

    try:
        from . import providers

        # Build skills catalog for LLM
        catalog = "\n".join(
            f"{i+1}. {s['name']}: {s['desc'][:120]}"
            for i, s in enumerate(items)
        )

        prompt = f"""Ты — expert tech lead. Выбери релевантные скиллы для задачи.

ЗАДАЧА: {task}

ДОСТУПНЫЕ СКИЛЛЫ:
{catalog}

ВЫБЕРИ 2-4 самых релевантных скиллов. Верни ТОЛЬКО JSON-массив имён:
["skill-name-1", "skill-name-2", ...]

Правила:
- Если есть прямое совпадение — выбирай его (для API → fastapi-backend, для тестов → api-testing)
- Если прямого совпадения нет — выбирай универсальные: input-validation-security, react-components
- Не добавляй скиллы «на всякий случай» — только те что РЕАЛЬНО нужны
- Для фронтенда/визуала: react-components, input-validation-security
- Для бэкенда/API: fastapi-backend, rest-api-design, sql-postgres
- Для деплоя: docker-deploy, env-secrets-config
- Для тестов: api-testing
- Для безопасности: input-validation-security, auth-jwt"""

        r = providers.chat(model, [{"role": "user", "content": prompt}],
                          max_tokens=200, temperature=0.0, cfg=cfg, timeout=30)

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
                    result.append({"name": name, "text": name_to_skill[name]["body"]})
            if result:
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
            result.append({"name": s["name"], "text": s["body"]})
        if len(result) >= k:
            break
    return result
