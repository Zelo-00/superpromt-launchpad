"""Каталог моделей провайдера для гибкого выбора внутри терминала.
OpenRouter/NIM/OpenAI-совместимые отдают список по GET /models; OpenRouter — ещё
цену и контекст. Кэш на сессию, чтобы не дёргать сеть повторно."""
import urllib.request

from . import config

_CACHE = {}


def _get_json(url, key, timeout=15):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        import json
        return json.load(r)


def list_models(prov_name, cfg):
    """-> [{'id','name','ctx','price','free'}] отсортировано (бесплатные и дешёвые выше).
    Пустой список = не удалось получить (нет ключа/сети/эндпоинта)."""
    if prov_name in _CACHE:
        return _CACHE[prov_name]
    prov = cfg["providers"].get(prov_name, {})
    key = config.resolve_key(prov)
    if not key or prov.get("style") == "anthropic":  # anthropic /models без списка цен
        _CACHE[prov_name] = []
        return []
    out = []
    try:
        data = _get_json(prov["base_url"].rstrip("/") + "/models", key)
        for m in data.get("data", []):
            pr = m.get("pricing") or {}
            price = pr.get("prompt")
            try:
                pf = float(price) if price is not None else None
            except (TypeError, ValueError):
                pf = None
            out.append({"id": m.get("id", ""), "name": m.get("name", m.get("id", "")),
                        "ctx": m.get("context_length"),
                        "price": pf, "free": pf == 0})
    except Exception:  # noqa: BLE001 — каталог опционален, выбор по id всегда доступен
        _CACHE[prov_name] = []
        return []
    out.sort(key=lambda x: (not x["free"], x["price"] if x["price"] is not None else 1e9,
                            x["id"]))
    _CACHE[prov_name] = out
    return out


def search(models, query="", limit=20):
    """Фильтр по подстроке id/name (регистронезависимо). Пустой запрос — топ по сортировке."""
    q = query.strip().lower()
    if q:
        models = [m for m in models if q in m["id"].lower() or q in m["name"].lower()]
    return models[:limit]


def fmt_price(m):
    if m["free"]:
        return "бесплатно"
    if m["price"] is None:
        return "—"
    per_m = m["price"] * 1_000_000
    return "$%.2f/1М" % per_m if per_m >= 0.01 else "$%.4f/1М" % per_m


def fmt_ctx(m):
    c = m.get("ctx")
    if not c:
        return ""
    return "%dK" % (c // 1000) if c >= 1000 else str(c)
