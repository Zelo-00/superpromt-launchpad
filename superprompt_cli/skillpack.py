"""Упакованная библиотека скиллов: ВЕСЬ каталог PromtMaster (метаданные + тексты .md) сжат в
ОДИН непрозрачный файл `lib.dat` (zlib + XOR-обфускация ключом, зашитым в байткод). Наружу
.md/INDEX не кладутся — читает только этот код (в blackbox-поставке — .pyc). Барьер, как и
blackbox исходников: не абсолютная защита (ключ в байткоде), но глазами/текстовым редактором
не прочитать. Ранжирование — ОФЛАЙН TF-IDF по name+desc(+ru), без сети и ключей.
"""
import json
import math
import os
import re
import zlib

# ключ обфускации — в .pyc не читается глазами (барьер, не крипто-гарантия)
_KEY = bytes((0x2b, 0xd3, 0x59, 0x8f, 0x11, 0xfa, 0x42, 0x80,
              0xc7, 0x05, 0xac, 0x5b, 0x3c, 0xea, 0x03, 0x76))


def _xor(b):
    k, n = _KEY, len(_KEY)
    return bytes(c ^ k[i % n] for i, c in enumerate(b))


def build_pack(pm_dir, out_file):
    """СБОРКА (только на билд-машине): INDEX.json + .md → единый blob. -> число упакованных."""
    idx = json.load(open(os.path.join(pm_dir, "INDEX.json"), encoding="utf-8"))["skills"]
    items = []
    for s in idx:
        rel = s.get("path")
        if not rel:
            continue
        try:
            text = open(os.path.join(pm_dir, rel), encoding="utf-8").read()
        except OSError:
            continue
        search = "%s %s %s" % (s["name"].replace("__", " ").replace("_", " "),
                               s.get("desc", ""), s.get("desc_ru", ""))
        items.append({"n": s["name"], "d": s.get("domain", ""),
                      "src": s.get("source", ""), "s": search, "t": text})
    blob = zlib.compress(json.dumps(items, ensure_ascii=False).encode("utf-8"), 9)
    with open(out_file, "wb") as f:
        f.write(_xor(blob))
    return len(items)


_CACHE = {}


def load(dat_file):
    """Раскодировать blob (кэш по mtime). -> список скиллов."""
    key = (dat_file, os.path.getmtime(dat_file))
    if _CACHE.get("k") == key:
        return _CACHE["v"]
    with open(dat_file, "rb") as f:
        items = json.loads(zlib.decompress(_xor(f.read())).decode("utf-8"))
    _CACHE.update(k=key, v=items)
    return items


_WORD = re.compile(r"[a-zа-яё0-9]+", re.I)


def rank(items, task, domain, k):
    """Офлайн КОСИНУСНЫЙ TF-IDF: top-k [{name, text}] по релевантности. Нормировка по длине дока
    (иначе длинные скиллы всплывают ложно). Буст source=improved (×1.08). Матч по name+desc+desc_ru
    — кросс-язык слабее эмбеддера, но без сети и всегда работает."""
    pool = [s for s in items if not domain or s["d"] == domain] or items
    qtok = _WORD.findall(task.lower())
    if not qtok or not pool:
        return []
    df, docs = {}, []
    for s in pool:
        toks = _WORD.findall(s["s"].lower())
        docs.append(toks)
        for w in set(toks):
            df[w] = df.get(w, 0) + 1
    n = len(pool)

    def vec(toks):
        tf = {}
        for w in toks:
            tf[w] = tf.get(w, 0) + 1
        return {w: (c / len(toks)) * math.log(1 + n / (1 + df.get(w, 0)))
                for w, c in tf.items()} if toks else {}

    qv = vec(qtok)
    qn = math.sqrt(sum(v * v for v in qv.values())) or 1.0
    scored = []
    for s, toks in zip(pool, docs):
        dv = vec(toks)
        dot = sum(qv.get(w, 0.0) * dv.get(w, 0.0) for w in qv)
        if dot <= 0:
            continue
        dn = math.sqrt(sum(v * v for v in dv.values())) or 1.0
        sc = (dot / (qn * dn)) * (1.08 if s.get("src") == "improved" else 1.0)
        scored.append((sc, s))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"name": s["n"], "text": s["t"]} for _, s in scored[:k]]


def rank_remote(url, token, task, domain, k, timeout=10):
    """СЕРВЕРНЫЙ РЕЖИМ (PoC poc/skill_server.py): получить top-k [{name,text}] с сервера скиллов —
    библиотека НЕ у клиента (закрывает A2). Недоступность/ошибка → [] (скиллы опциональны, не роняем
    конвейер). Возвращает ту же форму, что rank(), поэтому router.pick_skills не различает источник."""
    import urllib.request
    body = json.dumps({"task": task, "domain": domain, "k": k}).encode()
    req = urllib.request.Request(url.rstrip("/") + "/rank", data=body,
                                 headers={"Authorization": "Bearer " + token,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r).get("skills", [])
    except Exception:  # noqa: BLE001
        return []
