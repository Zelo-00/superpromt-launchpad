"""Ролевой доступ spt: owner / trusted / subscriber.

  owner      — полный доступ, чёрный ящик ВЫКЛ (видит метрику/промты/скиллы). Владелец.
  trusted    — полный доступ, чёрный ящик ВКЛ (работает всё, IP закрыт). Доверенные лица.
  subscriber — по ключу подписки (лицензионный токен), чёрный ящик ВКЛ. Остальные.

Сейчас (костыль для тестирования/наращивания): вход по логину/паролю (accounts.json,
scrypt-хэши, плейнтекст не хранится). Позже командой: owner только владельцу,
trusted — доверенным, subscriber — по токену без логина.

Пароли — hashlib.scrypt (stdlib, без внешних зависимостей). Роль → политика доступа.
"""
import getpass
import hashlib
import hmac
import json
import os

from . import config
from .ansi import G, bold, green, grey, red, yellow

ACCOUNTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "licensing", "accounts.json")

POLICY = {  # роль → что разрешено
    "owner":      {"blackbox": False, "needs_license": False, "login": True,
                   "title": "владелец (полный доступ, чёрный ящик ВЫКЛ)"},
    "trusted":    {"blackbox": True,  "needs_license": False, "login": True,
                   "title": "доверенное лицо (полный доступ, чёрный ящик ВКЛ)"},
    "subscriber": {"blackbox": True,  "needs_license": True,  "login": False,
                   "title": "подписка (доступ по ключу, чёрный ящик ВКЛ)"},
}


def _accounts():
    if os.path.exists(ACCOUNTS):
        try:
            return json.load(open(ACCOUNTS, encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return {}


def verify_login(user, pw):
    """-> роль или None. scrypt-сравнение в постоянном времени."""
    acc = _accounts().get(user)
    if not acc:
        return None
    try:
        h = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(acc["salt"]),
                           n=16384, r=8, p=1, dklen=32).hex()
    except Exception:  # noqa: BLE001
        return None
    if hmac.compare_digest(h, acc["hash"]):
        return acc.get("role", "trusted")
    return None


def enabled(cfg):
    """Гейт доступа активен? Dev-режим (SPT_DEV) и конфиг без auth — свободный доступ
    (чтобы тесты/наращивание не требовали пароля). Поставка ставит auth:true."""
    if os.environ.get("SPT_DEV") in ("1", "true"):
        return False
    return bool((cfg or {}).get("auth"))


def apply_role(cfg, role):
    """Политика роли → cfg (blackbox, требование лицензии). Возвращает policy."""
    pol = POLICY.get(role, POLICY["subscriber"])
    cfg["_role"] = role
    cfg["blackbox"] = pol["blackbox"] or bool(cfg.get("blackbox"))  # роль может лишь ужесточить
    return pol


def gate(cfg, log=print):
    """Точка входа: определить роль и применить политику.
    -> роль (продолжаем) или None (нет доступа, выход). Порядок:
       1) валидный лицензионный токен → subscriber;
       2) иначе логин/пароль → owner/trusted;
       3) иначе отказ."""
    if not enabled(cfg):
        return "owner"  # dev/свободный режим
    # 1. подписка по ключу (без логина)
    from . import license as lic
    lic_status = lic.check(cfg)
    if lic_status["valid"]:
        apply_role(cfg, "subscriber")
        log(green("  %s подписка активна · %s" % (G["ok"], lic_status["detail"])))
        return "subscriber"
    if lic_status["present"] and not lic_status["valid"]:
        log(red("  %s подписка недействительна: %s" % (G["fail"], lic_status["detail"])))
        log(grey("    продлите подписку или войдите под аккаунтом."))
    # 2. логин/пароль (owner/trusted)
    if not _accounts():
        log(yellow("  %s доступ не настроен. Нужен ключ подписки или аккаунт." % G["warn"]))
        return None
    print("  вход spt" + grey("   (Ctrl-C — отмена)"))
    for attempt in range(3):
        try:
            user = input("  логин %s " % G["prompt"]).strip()
            pw = getpass.getpass("  пароль %s " % G["prompt"])
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        role = verify_login(user, pw)
        if role:
            pol = apply_role(cfg, role)
            print(green("  %s %s · роль: %s" % (G["ok"], user, pol["title"])))
            return role
        print(red("  %s неверный логин или пароль (попытка %d/3)" % (G["fail"], attempt + 1)))
    return None
