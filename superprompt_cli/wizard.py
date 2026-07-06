"""Визуальный онбординг-мастер spt: welcome → ключ → модель → настройка → запрос.
Дизайн — по спеке агента-креативщика. stdlib-минимализм: input() с номерами/фильтром,
не raw-mode. Запускается ТОЛЬКО на TTY без единого ключа и без флага onboarded.
Ctrl-C/Esc на любом шаге = отмена, не роняет терминал."""
import getpass
import os
import urllib.request

from . import config, i18n, models_api
from .ansi import G, bold, cyan, green, grey, red, yellow, _UTF

# дефолтная модель на провайдера (для прямых API — где список не нужен)
DEFAULTS = {
    "openai": "openai/gpt-5.4-mini", "anthropic": "anthropic/claude-sonnet-5",
    "google": "google/gemini-3.5-flash", "nim": "nim/moonshotai/kimi-k2.6",
}
PROV_ORDER = ["openrouter", "openai", "anthropic", "google", "nim"]
LOCAL = [("ollama", 11434), ("lmstudio", 1234), ("vllm", 8000), ("llamacpp", 8080)]


def _hr(w=68):
    print(grey("  " + ("─" if _UTF else "-") * w))


def _welcome():
    from . import anim
    from .version import VERSION
    print()
    for ln in anim.logo("ru").split("\n"):         # НОВЫЙ лавовый логотип SuperPromt (как в терминале)
        print("  " + ln)
    print()
    print("  %s   %s" % (bold("SuperPromt Terminal"), grey("v" + VERSION)))
    print("  " + grey("«Проверено, а не выдумано.»"))
    print()
    print("  Терминал, который проверяет каждый ответ ИИ на выдумки")
    print("  и мёртвые ссылки — прежде чем показать его вам.")
    print()
    print(yellow("  %s Провайдер не подключён — нужен ключ API или локальная модель"
                 % G["abstain"]))
    print()
    print("  Настроим за 3 шага (≈30 секунд):")
    print("     %s 1. ключ API   %s   %s" %
          (cyan(G["pick"]), grey("2. модель"), grey("3. первый запрос")))
    print()
    print("  %s начать  ·  %s локальная модель (без ключа)  ·  %s выход" %
          (bold("[Enter]"), bold("[L]"), bold("[Q]")))
    try:
        return input("  ▸ ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "q"


def _probe(prov, key):
    if prov.get("style") == "anthropic":
        return (prov["base_url"].rstrip("/") + "/v1/models",
                {"x-api-key": key, "anthropic-version": "2023-06-01"})
    return prov["base_url"].rstrip("/") + "/models", {"Authorization": "Bearer " + key}


def _ping(prov, key):
    """-> ('ok'|'rejected'|'network', детали). Различаем плохой ключ и мёртвую сеть."""
    import urllib.error
    url, headers = _probe(prov, key)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                    timeout=8) as r:
            return "ok", "HTTP %d" % r.status
    except urllib.error.HTTPError as e:
        return "rejected", "HTTP %d" % e.code
    except Exception as e:  # noqa: BLE001 — таймаут/DNS/refused = сеть, не плохой ключ
        return "network", str(e)[:80]


def _save_key(cfg, prov_name, key):
    var = prov_name.upper() + "_API_KEY"
    envp = os.path.join(config.SPT_DIR, ".env")
    os.makedirs(config.SPT_DIR, exist_ok=True)
    with open(envp, "a", encoding="utf-8") as f:
        f.write("%s=%s\n" % (var, key))
    os.chmod(envp, 0o600)
    cfg["providers"].setdefault(prov_name, {})["api_key_file"] = "%s:%s" % (envp, var)
    config.save(cfg)
    return envp


def _step_key(cfg):
    """Шаг 1/3. -> имя провайдера или None (отмена)."""
    print()
    print("  Шаг 1/3 — ключ API%s" % grey("                                    [Q] отмена"))
    _hr()
    print("  Вставьте ключ провайдера. Ввод скрыт (как пароль).")
    print(grey("  Ключ хранится только у вас: ~/.spt/.env (0600), не в облаке."))
    print(grey("  OpenRouter openrouter.ai/keys · OpenAI/Anthropic/Google/NVIDIA — свои консоли."))
    print()
    try:
        key = getpass.getpass("  ключ %s " % G["prompt"]).strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not key or key.lower() == "q":
        return None
    prov_name = next((p for pref, p in config.KEY_PREFIX.items()
                      if key.startswith(pref)), None) \
        if hasattr(config, "KEY_PREFIX") else None
    if not prov_name:
        from .cli import KEY_PREFIX
        prov_name = next((p for pref, p in KEY_PREFIX.items() if key.startswith(pref)), None)
    if not prov_name:
        print(cyan("  %s префикс не распознан. Какой это провайдер?" % G["tool"]))
        print("    " + "   ".join("%d %s" % (i + 1, p)
                                  for i, p in enumerate(PROV_ORDER)))
        try:
            sel = input("  провайдер %s " % G["prompt"]).strip()
        except (EOFError, KeyboardInterrupt):
            return None
        prov_name = PROV_ORDER[int(sel) - 1] if sel.isdigit() and \
            1 <= int(sel) <= len(PROV_ORDER) else sel
    if prov_name not in cfg["providers"]:
        print(red("  неизвестный провайдер"))
        return None
    print(cyan("  %s префикс → %s. Проверяю ключ вживую…" % (G["tool"], prov_name)))
    status, detail = _ping(cfg["providers"][prov_name], key)
    if status == "ok":
        envp = _save_key(cfg, prov_name, key)
        print(green("  %s %s отвечает (%s). Ключ сохранён: %s" %
                    (G["ok"], prov_name, detail, envp)))
        return prov_name
    if status == "rejected":
        print(red("  %s %s отклонил ключ (%s)." % (G["fail"], prov_name, detail)))
        print(grey("    ключ скопирован целиком, без пробелов? не отозван ли?"))
    else:
        print(red("  %s сеть недоступна (%s) — не смог проверить ключ." %
                  (G["fail"], detail)))
        print(grey("    ключ мог быть верным."))
    try:
        a = input("  %s сохранить без проверки · %s ввести заново · %s отмена: "
                  % (bold("[S]"), bold("[R]"), bold("[Q]"))).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None
    if a == "s":
        _save_key(cfg, prov_name, key)
        print(yellow("  сохранён без проверки."))
        return prov_name
    if a == "r":
        return _step_key(cfg)
    return None


def _print_model_rows(models):
    print(grey("    #   модель                                 контекст   $/1М (вх)"))
    for i, m in enumerate(models, 1):
        pr = models_api.fmt_price(m)
        col = green if m["free"] else grey
        print("   %s %-40s %7s  %s" % (
            (cyan(G["pick"]) if i == 1 else "%2d" % i), m["id"][:40],
            models_api.fmt_ctx(m), col(pr)))


def _step_model_openrouter(cfg, prov_name):
    print()
    print("  Шаг 2/3 — модель %s" % prov_name)
    _hr()
    catalog = models_api.list_models(prov_name, cfg)
    if not catalog:
        print(yellow("  %s список моделей недоступен. Введите id вручную (Enter = дефолт):"
                     % G["warn"]))
        try:
            mid = input("  model %s " % G["prompt"]).strip()
        except (EOFError, KeyboardInterrupt):
            return None
        return (prov_name + "/" + mid) if mid else cfg["default_model"]
    shown = models_api.search(catalog, "", 8)
    print("  Популярные (бесплатные и дешёвые выше):")
    _print_model_rows(shown)
    print(grey("  выбор: номер · /слово поиск · точный id · Enter = верхняя(1) · /q отмена"))
    while True:
        try:
            sel = input("  model %s " % G["prompt"]).strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if sel in ("/q", "q"):
            return None
        if not sel:
            chosen = shown[0]["id"]
            break
        if sel.startswith("/"):
            shown = models_api.search(catalog, sel[1:], 8)
            if not shown:
                print(grey("    ничего не найдено, уточните"))
                shown = models_api.search(catalog, "", 8)
            else:
                print(grey("    найдено, показаны %d:" % len(shown)))
                _print_model_rows(shown)
            continue
        if sel.isdigit() and 1 <= int(sel) <= len(shown):
            chosen = shown[int(sel) - 1]["id"]
            break
        chosen = sel  # точный id
        break
    spec = chosen if "/" in chosen and chosen.split("/")[0] in cfg["providers"] \
        else prov_name + "/" + chosen
    cfg["default_model"] = spec
    config.save(cfg)
    print(green("  %s модель: %s → сохранено" % (G["ok"], spec)))
    return spec


def _step_model_direct(cfg, prov_name):
    print()
    print("  Шаг 2/3 — модель %s" % prov_name)
    _hr()
    default = DEFAULTS.get(prov_name, prov_name + "/default")
    print("  По умолчанию для %s:  %s" % (prov_name, bold(default)))
    print(grey("  [Enter] оставить  ·  или введите id модели"))
    try:
        sel = input("  model %s " % G["prompt"]).strip()
    except (EOFError, KeyboardInterrupt):
        return None
    spec = default if not sel else \
        (sel if sel.split("/")[0] in cfg["providers"] else prov_name + "/" + sel)
    cfg["default_model"] = spec
    config.save(cfg)
    print(green("  %s модель: %s → сохранено" % (G["ok"], spec)))
    print()
    print(green("  Готово, вы подключены к %s. Осталось задать первый вопрос." % prov_name))
    return spec


def _step_local(cfg):
    """Ветка [L]: найти живой локальный сервер, выбрать модель без ключа."""
    print()
    print("  Локальная модель — ищу запущенный сервер…")
    for name, port in LOCAL:
        try:
            with urllib.request.urlopen(
                    "http://localhost:%d/v1/models" % port, timeout=2):
                print(green("  %s найден %s на :%d" % (G["ok"], name, port)))
                return _step_model_openrouter(cfg, name)
        except Exception:  # noqa: BLE001
            continue
    print(yellow("  %s локальный сервер не найден (ollama/LM Studio/llama.cpp/vLLM)." % G["warn"]))
    print(grey("  Запустите его (INSTALL.md §4) и повторите, или подключите ключ API."))
    return None


def _tune(cfg):
    """Меню тонкой настройки: тир, max_tokens, temperature, гейты, судья."""
    print()
    print("  Тонкая настройка%s" % grey("               (Enter в пустой строке — готово)"))
    _hr()
    fields = [
        ("тир", "tier", "mid", "min · [mid] · max"),
        ("max_tokens", "max_tokens", None, "число · [авто]"),
        ("температура", "temperature", 0.2, "0.0–2.0 · [0.2]"),
        ("гейты", "gates", "on", "on · off · strict · [on]"),
        ("язык интерфейса", "ui_lang", "ru", "ru en zh kk fr ja …"),
        ("язык ответов", "answer_lang", "ru", "ru en zh kk fr ja …"),
        ("судья (PSQ)", "judge_model", "", "id модели · [как модель]"),
    ]
    while True:
        for i, (label, key, dflt, opts) in enumerate(fields, 1):
            cur = cfg.get(key)
            cur = "авто" if cur in (None, "") and key in ("max_tokens", "judge_model") \
                else cur
            print("   %d  %-13s %-14s %s" % (i, label, bold(str(cur)), grey(opts)))
        try:
            sel = input("  наст %s " % G["prompt"]).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not sel:
            break
        if not sel.isdigit() or not 1 <= int(sel) <= len(fields):
            continue
        label, key, dflt, opts = fields[int(sel) - 1]
        try:
            val = input("      %s = " % label).strip()
        except (EOFError, KeyboardInterrupt):
            continue
        if val == "":
            continue
        if key == "gates":
            if val == "off":
                cfg["gates"] = False
            elif val == "strict":
                cfg["gates"] = True
                cfg["strict"] = True
            else:
                cfg["gates"] = True
                cfg["strict"] = False
        elif key in ("ui_lang", "answer_lang"):
            cfg[key] = i18n.norm(val)
        elif key in ("max_tokens",):
            cfg[key] = int(val) if val.isdigit() else None
        elif key == "temperature":
            try:
                cfg[key] = max(0.0, min(2.0, float(val)))
            except ValueError:
                continue
        else:
            cfg[key] = val
        print(green("      %s %s = %s" % (G["ok"], label, val)))
    config.save(cfg)
    print(green("  %s настройки сохранены: ~/.spt/config.json" % G["ok"]))


def _step_lang(cfg):
    """Шаг 0: язык интерфейса и ответов (по умолчанию русский)."""
    print()
    print("  Язык / Language / 语言 / Тіл" + grey("   [Enter] — русский"))
    _hr()
    langs = i18n.list_langs()
    for i, (code, name) in enumerate(langs[:9], 1):
        print("   %d %s (%s)" % (i, name, code))
    print(grey("   [Enter] Русский · номер · код языка (es de pt ja ko …)"))
    try:
        sel = input("  язык %s " % G["prompt"]).strip()
    except (EOFError, KeyboardInterrupt):
        return
    if not sel:
        return
    if sel.isdigit() and 1 <= int(sel) <= len(langs[:9]):
        code = langs[int(sel) - 1][0]
    else:
        code = i18n.norm(sel)
    cfg["ui_lang"] = code
    cfg["answer_lang"] = code
    config.save(cfg)
    print(green("  %s %s: %s" % (G["ok"], i18n.t("lang_ui_set", code),
                                 i18n.native_name(code))))


def run(cfg):
    """Полный мастер. -> True если настроен (можно продолжать в REPL), False — выход."""
    _step_lang(cfg)
    choice = _welcome()
    if choice == "q":
        return False
    prov_name = _step_local(cfg) if choice == "l" else None
    if choice == "l" and not prov_name:
        return _has_key(cfg)
    if choice != "l":
        prov_name = _step_key(cfg)
        if not prov_name:
            print(yellow("  мастер прерван — /keys add вернёт к настройке."))
            return _has_key(cfg)
        if prov_name == "openrouter" or config.resolve_key(
                cfg["providers"].get(prov_name, {})) == "local":
            _step_model_openrouter(cfg, prov_name)
        else:
            _step_model_direct(cfg, prov_name)
    # шаг 3: развилка
    print()
    print("  Шаг 3/3 — почти готово")
    _hr()
    print("  Провайдер %s   модель %s %s   страховка %s" %
          (green(G["ok"]), green(G["ok"]), bold(cfg.get("default_model", "")),
           green("on") if cfg.get("gates", True) else yellow("off")))
    print()
    print("  %s  сразу ввести запрос" % green(bold("[Enter]")))
    print("  %s        тонкая настройка (тир · токены · гейты · температура · судья)"
          % bold("[T]"))
    try:
        a = input("  ▸ ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        a = ""
    if a == "t":
        _tune(cfg)
    cfg["onboarded"] = True
    config.save(cfg)
    print()
    return True


def _has_key(cfg):
    return any(config.resolve_key(p) for p in cfg["providers"].values())
