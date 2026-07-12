"""Клиентская сторона лицензий spt (подписка по ключу).

Хранит токен ~/.spt/license.jwt. Проверка — публичным ключом Ed25519 (license_public.pem).
Приватного ключа у клиента НЕТ (подделать токен нельзя без сервера лицензий).

ЧЕСТНАЯ ГРАНИЦА (принцип честной границы): локальная проверка — UX-слой, НЕ крипто-стойкий барьер.
Владелец машины может патчить клиент/переводить часы. Стойкий enforcement подписки =
СЕРВЕРНЫЙ режим (licensing/server/spt_server.py): «мозг» продукта за токеном, истёк —
сервер молчит, обходить нечего. См. LICENSING.md.

Митигации (из пентеста):
- алгоритм ЖЁСТКО EdDSA (options require exp/iss/aud); анти alg=none и EdDSA→HS256 confusion;
- iss/aud фиксированы; leeway=0;
- device-binding: сверка device_id из токена с локальным fingerprint (при наличии);
- анти-часы-назад: монотонный last_seen в ~/.spt/.seen — время не откатывается ниже виденного.
"""
import datetime
import hashlib
import json
import os
import uuid

from . import config

PUB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "license_public.pem")
TOKEN_PATH = os.path.join(config.SPT_DIR, "license.jwt")
SEEN_PATH = os.path.join(config.SPT_DIR, ".seen")
ISS, AUD = "spt-license", "spt-cloud"
PLAN_RU = {"week": "неделя", "month": "месяц", "3month": "3 месяца",
           "year": "год", "lifetime": "бессрочно"}


def device_id():
    """Стабильный fingerprint машины (для device-binding). Не PII."""
    raw = "%s|%s" % (uuid.getnode(), os.environ.get("HOSTNAME", ""))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _read_token():
    if os.path.exists(TOKEN_PATH):
        return open(TOKEN_PATH, encoding="utf-8").read().strip()
    return os.environ.get("SPT_LICENSE", "").strip()


def save_token(token):
    os.makedirs(config.SPT_DIR, exist_ok=True)
    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        f.write(token.strip() + "\n")
    os.chmod(TOKEN_PATH, 0o600)


def _monotonic_now():
    """Время, которое нельзя откатить назад (анти-часы-атака)."""
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    seen = 0
    if os.path.exists(SEEN_PATH):
        try:
            seen = int(open(SEEN_PATH).read().strip())
        except (OSError, ValueError):
            seen = 0
    eff = max(now, seen)
    try:
        os.makedirs(config.SPT_DIR, exist_ok=True)
        open(SEEN_PATH, "w").write(str(eff))
    except OSError:
        pass
    return eff


def check(cfg=None):
    """-> {'present','valid','detail','claims'}. Крипто-проверка + exp по монотонному времени."""
    token = _read_token()
    if not token:
        return {"present": False, "valid": False, "detail": "нет ключа подписки", "claims": {}}
    try:
        import jwt
    except ImportError:
        return {"present": True, "valid": False,
                "detail": "PyJWT не установлен — используйте серверный режим", "claims": {}}
    if not os.path.exists(PUB):
        return {"present": True, "valid": False, "detail": "нет публичного ключа", "claims": {}}
    pub = open(PUB, "rb").read()
    try:
        # alg ЖЁСТКО EdDSA: анти alg=none / algorithm-confusion (CVE-2015-9235-класс)
        claims = jwt.decode(token, pub, algorithms=["EdDSA"], audience=AUD, issuer=ISS,
                            leeway=0, options={"require": ["iat", "jti"]})
    except Exception as e:  # noqa: BLE001
        return {"present": True, "valid": False,
                "detail": "подпись/формат недействительны (%s)" % str(e)[:60], "claims": {}}
    # exp по монотонному времени (нельзя обойти переводом часов назад)
    exp = claims.get("exp")
    now = _monotonic_now()
    if exp is not None and now >= exp:
        left = datetime.datetime.fromtimestamp(exp, datetime.timezone.utc)
        return {"present": True, "valid": False,
                "detail": "подписка истекла %s" % left.strftime("%Y-%m-%d"),
                "claims": claims}
    # device-binding: токен, привязанный к другому устройству, не действует
    dev = claims.get("device")
    if dev and dev != device_id():
        return {"present": True, "valid": False,
                "detail": "ключ привязан к другому устройству", "claims": claims}
    plan = PLAN_RU.get(claims.get("plan"), claims.get("plan", "?"))
    if exp is None:
        detail = "план: %s (бессрочно)" % plan
    else:
        days = (exp - now) // 86400
        detail = "план: %s · осталось %d дн." % (plan, days)
    return {"present": True, "valid": True, "detail": detail, "claims": claims}
