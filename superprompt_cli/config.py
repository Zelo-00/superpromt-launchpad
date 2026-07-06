"""Конфиг spt: ~/.spt/config.json. Ключи НЕ хранятся в конфиге — только ссылки
(env-переменная или файл .env + имя переменной). Провайдер-агностик: любой
OpenAI-совместимый endpoint (OpenRouter, NIM, OpenAI, Google-compat, кастомный)
или Anthropic native."""
import json
import os
import re

SPT_DIR = os.path.expanduser(os.environ.get("SPT_HOME", "~/.spt"))


def ensure_dir(path=None):
    """Создать каталог под ~/.spt с правами 0700 (данные видны только владельцу).
    ~/.spt содержит .env, сессии, память — не должно быть world-readable (аудит MEDIUM)."""
    path = path or SPT_DIR
    os.makedirs(path, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:  # чужой каталог/права — не критично
        pass
    return path


def harden_file(path):
    """Ограничить файл под ~/.spt правами 0600 (только владелец)."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path

DEFAULT = {
    "default_model": "openrouter/xiaomi/mimo-v2.5",
    "judge_model": "",  # пусто = использовать default_model
    "tier": "mid",      # min | mid | max
    "gates": True,
    "strict": False,
    "temperature": None,  # None = дефолт провайдера (задаётся мастером)
    "max_tokens": None,
    "blackbox": False,    # True = инструменты не видят внутренние файлы (BLACKBOX.md)
    "onboarded": False,
    "ui_lang": "ru",      # язык интерфейса терминала (по умолчанию русский)
    "answer_lang": "ru",  # язык ответа LLM (по умолчанию русский); можно сменить
    "perm": "ask",        # разрешения: ask | auto (вопрос на критич.) | yolo (автономный)
    "theme": "lava",      # цвет chrome: lava(синий) | ocean | mono (светофор не меняется)
    "spinner": "pulse",   # индикатор процесса: pulse | fire | braille | dots
    "brand": "triangle",  # бренд-глиф: triangle ▲ | diamond ◆ | dot ● | spark ✻ | square | none
    "sparkles": True,     # ✦-искры вокруг логотипа (декор, стиль MiMo)
    "narrow_tools": False,  # опт-ин: сужать тул-спейс по домену (harness-eng П.11); дефолт — все
    "providers": {
        "openrouter": {"style": "openai", "base_url": "https://openrouter.ai/api/v1",
                       "api_key_env": "OPENROUTER_API_KEY", "api_key_file": ""},
        "nim": {"style": "openai", "base_url": "https://integrate.api.nvidia.com/v1",
                "api_key_env": "NVIDIA_API_KEY", "api_key_file": ""},
        "openai": {"style": "openai", "base_url": "https://api.openai.com/v1",
                   "api_key_env": "OPENAI_API_KEY", "api_key_file": ""},
        "anthropic": {"style": "anthropic", "base_url": "https://api.anthropic.com",
                      "api_key_env": "ANTHROPIC_API_KEY", "api_key_file": ""},
        "google": {"style": "openai",
                   "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                   "api_key_env": "GEMINI_API_KEY", "api_key_file": ""},
        # локальные нейросети (OpenAI-совместимые серверы, ключ не нужен)
        "ollama": {"style": "openai", "base_url": "http://localhost:11434/v1",
                   "api_key_env": "OLLAMA_API_KEY", "api_key_file": "", "local": True},
        "lmstudio": {"style": "openai", "base_url": "http://localhost:1234/v1",
                     "api_key_env": "LMSTUDIO_API_KEY", "api_key_file": "", "local": True},
        "vllm": {"style": "openai", "base_url": "http://localhost:8000/v1",
                 "api_key_env": "VLLM_API_KEY", "api_key_file": "", "local": True},
        "llamacpp": {"style": "openai", "base_url": "http://localhost:8080/v1",
                     "api_key_env": "LLAMACPP_API_KEY", "api_key_file": "", "local": True},
    },
}


def load():
    path = os.path.join(SPT_DIR, "config.json")
    cfg = json.loads(json.dumps(DEFAULT))  # deep copy
    if os.path.exists(path):
        try:
            user = json.load(open(path, encoding="utf-8"))
            if not isinstance(user, dict):
                raise ValueError("config.json не является объектом")
        except Exception:  # noqa: BLE001 — битый/нечитаемый конфиг НЕ должен ронять запуск (polish_suite)
            try:
                os.replace(path, path + ".corrupt")   # сохранить для разбора, не терять данные молча
            except OSError:
                pass
            return cfg                                 # фолбэк на дефолт вместо трейсбека
        cfg.update({k: v for k, v in user.items() if k != "providers"})
        for name, p in (user.get("providers") or {}).items():
            cfg["providers"].setdefault(name, {}).update(p)
    return cfg


def save(cfg):
    os.makedirs(SPT_DIR, exist_ok=True)
    path = os.path.join(SPT_DIR, "config.json")
    json.dump(cfg, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.chmod(path, 0o600)


def is_local(cfg, spec):
    """Провайдер модели 'провайдер/модель' — локальный?"""
    prov = cfg["providers"].get(spec.partition("/")[0], {})
    return bool(prov.get("local")) or re.match(
        r"https?://(localhost|127\.0\.0\.1|0\.0\.0\.0)[:/]", prov.get("base_url", "")) is not None


_ENV_CACHE = {}  # path -> (mtime, {VAR: value}) — .env парсим один раз на mtime (аудит b1)


def _read_env_file(path):
    """Разобрать .env в {VAR: value} с кэшем по mtime (resolve_key зовётся в циклах)."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    hit = _ENV_CACHE.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    data = {}
    try:
        for line in open(path, encoding="utf-8", errors="replace"):
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line.strip())
            if m:
                data[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    except OSError:
        return {}
    _ENV_CACHE[path] = (mtime, data)
    return data


def resolve_key(prov):
    """env → api_key_file ('/path/.env:VAR') → для локальных серверов ключ не нужен."""
    key = os.environ.get(prov.get("api_key_env", ""), "")
    if key:
        return key
    ref = prov.get("api_key_file", "")
    if ":" in ref:
        path, var = ref.rsplit(":", 1)
        val = _read_env_file(path).get(var)
        if val:
            return val
    if prov.get("local") or re.match(r"https?://(localhost|127\.0\.0\.1|0\.0\.0\.0)[:/]",
                                     prov.get("base_url", "")):
        return "local"  # локальный сервер: Authorization формально нужен, значение любое
    return ""
