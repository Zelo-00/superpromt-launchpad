"""Проверка обновлений spt (фундамент; бета). Читает манифест последней версии
и сообщает, если доступна новая. Кэш ~/.spt/.update — не чаще раза в сутки.
Сеть только если UPDATE_MANIFEST_URL задан И пользователь не отключил (SPT_NO_UPDATE).

Формат манифеста (JSON): {"version":"1.3.0","channel":"beta","url":"...","notes":"..."}.
Обновление НЕ применяется автоматически (бета, ручной контроль) — только уведомление.
"""
import json
import os
import urllib.request

from . import config
from .version import CHANNEL, UPDATE_MANIFEST_URL, VERSION

CACHE = os.path.join(config.SPT_DIR, ".update")


def _parse_ver(v):
    core = v.split("-")[0]
    return tuple(int(x) for x in core.split(".") if x.isdigit())


def is_newer(remote, local=VERSION):
    try:
        return _parse_ver(remote) > _parse_ver(local)
    except Exception:  # noqa: BLE001
        return False


def check(force=False):
    """-> dict|None. None = проверка выключена/нет манифеста/сеть недоступна."""
    if os.environ.get("SPT_NO_UPDATE") or not UPDATE_MANIFEST_URL:
        return None
    try:
        req = urllib.request.Request(UPDATE_MANIFEST_URL,
                                     headers={"User-Agent": "spt/%s" % VERSION})
        with urllib.request.urlopen(req, timeout=6) as r:
            manifest = json.load(r)
    except Exception:  # noqa: BLE001 — обновление опционально, не мешаем работе
        return None
    if manifest.get("channel") and manifest["channel"] != CHANNEL:
        return None
    if is_newer(manifest.get("version", "0")):
        try:
            os.makedirs(config.SPT_DIR, exist_ok=True)
            json.dump(manifest, open(CACHE, "w", encoding="utf-8"))
        except OSError:
            pass
        return manifest
    return None


def banner_note():
    """Короткая строка для баннера, если в кэше есть новость об обновлении."""
    if os.path.exists(CACHE):
        try:
            m = json.load(open(CACHE, encoding="utf-8"))
            if is_newer(m.get("version", "0")):
                return "доступно обновление %s — %s" % (m["version"], m.get("url", ""))
        except (OSError, ValueError):
            pass
    return ""
