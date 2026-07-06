"""Курированный web/backend скилл-пак (SKILL.md, формат Kodik/Claude Code) + офлайн-ранжирование
по релевантности задаче. Только stdlib: косинусный TF-IDF, без сети и зависимостей. Скиллы лежат в
`skills/<name>/SKILL.md` рядом с пакетом и одновременно публикуются на маркетплейс Kodik."""
import math
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
    """Список скиллов пака (кэш). -> [{name, desc, body, search}]."""
    global _cache
    if _cache is None:
        _cache = []
        if os.path.isdir(_DIR):
            for d in sorted(os.listdir(_DIR)):
                p = os.path.join(_DIR, d, "SKILL.md")
                if os.path.isfile(p):
                    _cache.append(_parse(p))
    return _cache


def rank(task, k=3):
    """Top-k релевантных скиллов -> [{name, text}] (косинусный TF-IDF, офлайн)."""
    items = load()
    q = _WORD.findall(task.lower())
    if not q or not items:
        return []
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

    qv = vec(q)
    qn = math.sqrt(sum(v * v for v in qv.values())) or 1.0
    scored = []
    for s, toks in zip(items, docs):
        dv = vec(toks)
        dot = sum(qv.get(w, 0.0) * dv.get(w, 0.0) for w in qv)
        if dot <= 0:
            continue
        dn = math.sqrt(sum(v * v for v in dv.values())) or 1.0
        scored.append((dot / (qn * dn), s))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"name": s["name"], "text": s["body"]} for _, s in scored[:k]]
