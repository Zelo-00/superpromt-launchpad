"""spt — SuperPromt Terminal. «Проверено, а не выдумано.»
SuperPromt (PSQ-гейт входа · KSCR-гейт выхода с link-veto) встроен в каждый
запрос; любой провайдер по API-ключу или локальная нейросеть (Ollama/LM Studio/…).
Коды выхода (run): 0 PASS/без претензий · 3 ВЕТО удержано · 2 ошибка провайдера."""
import argparse
import datetime
import getpass
import json
import os
import sys
import urllib.request

from . import agentloop, ansi, config, i18n, lineeditor, memory, providers, selflearn, sessions, update
from .ansi import (G, badge, blue, bold, chip, cyan, green, grey, magenta, red,
                   trust_bar, yellow)
from .version import VERSION

KEY_PREFIX = {  # эвристика (подтверждается живым пингом, не доверием префиксу)
    "sk-or-": "openrouter", "nvapi-": "nim", "sk-ant-": "anthropic",
    "sk-proj-": "openai", "sk-": "openai", "AIza": "google",
}

HELP = """Задача — просто текст в строке ввода. Остальное:

 разговор     /retry повторить · /why разбор вердикта · /links библиография [md]
 SuperPromt   /tier min|mid|max · /gates on|off|strict · /model [имя] · /skills · /settings
 усиление     /max <задача> (N кандидатов+судья+KSCR) · /goal <цель> :: <задача>
 разрешения   /perm ask|auto|yolo · /auto (вопрос на критич.) · /yolo (автономный)
 язык         /lang <код> — интерфейс+ответы · /lang ui|answer <код> (ru en zh kk fr ja …)
 вид          /theme lava|ocean|mono · /spinner · /brand · @файл — вложить файл
 сессии       /continue последняя · /resume выбрать · /compact сжать историю
 память       /memory ядро · /distill · /teach
 провайдеры   /keys add|test [имя] · команда models — кто подключён
 прочее       /help · exit (или /exit, выход, q)

 one-shot:    spt run "задача"   -q тихий · --strict скептик · --yolo без вопросов
 пайп-гейт:   любой_агент | spt gate [-q|--json|--strict]  — проверка ЧУЖОГО ответа
              (--code исполняет python-блоки из stdin — только для доверенного входа)
 коды выхода: 0 PASS · 3 ВЕТО · 2 ошибка провайдера · 130 прервано"""


_ACTIVE_SPINNER = None  # текущий спиннер (чтобы _confirm его паузил — баг #2)


def _write_no_symlink(path, body):
    """Записать файл, ОТКАЗАВ, если путь — симлинк (иначе подложенный симлинк
    bibliography.md перезапишет чужой файл, аудит LOW). O_NOFOLLOW бьёт по финальному
    компоненту-симлинку; O_TRUNC — перезапись обычного файла."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(body)


def _visible(s):
    """Обезвредить управляющие символы (CSI/ESC/\\r/C1/0x7f) в показе действия: нельзя визуально
    подменить одну команду другой перед подтверждением (security-аудит M3). \\n сохраняем —
    он лишь добавляет строки, не «переписывает» показанное."""
    out = []
    for ch in str(s):
        o = ord(ch)
        out.append(ch if (ch == "\n" or (0x20 <= o != 0x7f and not 0x80 <= o <= 0x9f))
                   else "\\x%02x" % o)
    return "".join(out)


def _fmt_confirm(name, args):
    """Показать пользователю ПОЛНОЕ действие (не обрезать команду — иначе опасный хвост
    прячется за лимитом и одобряется вслепую, security-аудит HIGH). Управляющие символы
    обезврежены (_visible) — визуальная подмена невозможна."""
    if name == "bash":
        return "$ " + _visible(args.get("command", ""))  # команду целиком, но безопасно
    if name == "write_file":
        return "%s  (%d байт)" % (_visible(args.get("path", "")), len(args.get("content", "")))
    if name == "edit_file":
        return "%s  [%s → %s]" % (_visible(args.get("path", "")),
                                  _visible(str(args.get("old_string", ""))[:60]),
                                  _visible(str(args.get("new_string", ""))[:60]))
    return _visible(str(args)[:2000])


def _confirm(name, args, reason=None):
    sp = _ACTIVE_SPINNER
    if sp:
        sp.pause()                       # #2: спиннер не портит диалог подтверждения
    try:
        if reason:
            print(red("  ⚠ КРИТИЧНО: %s" % reason))
        print("  ? разрешить %s:\n    %s" % (name, _fmt_confirm(name, args)))
        try:
            return input("  [y/N] > ").strip().lower() in ("y", "д", "yes")
        except (EOFError, KeyboardInterrupt):
            return False  # Ctrl-C на вопросе = «нет», а не смерть REPL
    finally:
        if sp:
            sp.resume()


_STAT_WINDOW = 7   # окно счётчиков (задачи/ссылки/фабрикации)
_STREAK_MAX = 30   # предел «дней без фабрикаций»


def _week_stats():
    """Счётчик доверия по дневной памяти за 7 дней: задачи, ссылки, фабрикации + streak.
    Опт (аудит b3): идём newest→oldest и выходим, как только собрано окно и найден
    последний день с фабрикацией — не парсим все 30 файлов каждый старт."""
    tasks = links = fab = 0
    today = datetime.date.today()
    last_fab_day = None
    for d in range(_STREAK_MAX):
        day = today - datetime.timedelta(days=d)
        path = os.path.join(memory.MEM_DIR, "daily", day.isoformat() + ".jsonl")
        if os.path.exists(path):
            for line in open(path, encoding="utf-8"):
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("event") != "task":
                    continue
                if ev.get("n_fab") and last_fab_day is None:
                    last_fab_day = day
                if d < _STAT_WINDOW:
                    tasks += 1
                    links += ev.get("n_links", 0)
                    fab += ev.get("n_fab", 0)
        if d >= _STAT_WINDOW - 1 and last_fab_day is not None:
            break  # окно собрано и streak известен — старые файлы не нужны
    streak = (today - last_fab_day).days if last_fab_day else _STREAK_MAX
    return tasks, links, fab, streak


def _banner(cfg, args):
    """Приветствие: адаптивно — бокс на десктопе, компактные строки на узком экране.
    Все ярлыки через i18n (при смене языка меняется весь интерфейс)."""
    from .ansi import box, lava_accent, brand, layout, _dw, _truncate
    from . import anim
    model = args.model or cfg["default_model"]
    tier = args.tier or cfg.get("tier", "mid")
    core = memory.load_core()
    lang = cfg.get("ui_lang", "ru")
    L = lambda k: i18n.t(k, lang)  # noqa: E731
    cwd = os.getcwd().replace(os.path.expanduser("~"), "~")
    gtxt = green(L("insurance_on")) if not args.no_gates else yellow(L("insurance_off"))
    pm = cfg.get("perm", "ask")
    ptxt = {"auto": yellow(" · " + L("perm_auto")),
            "yolo": red(" · " + L("perm_yolo"))}.get(pm, "")
    bb = grey(" · " + L("blackbox")) if cfg.get("blackbox") else ""
    role = {"owner": L("role_owner"), "trusted": L("role_trusted"),
            "subscriber": L("role_subscriber")}.get(cfg.get("_role"), "")
    al = cfg.get("answer_lang", "ru")
    width, narrow = layout()
    mark = brand()
    title = "%s%s  %s" % ((lava_accent(mark) + " ") if mark else "",
                          bold("SuperPromt Terminal"), badge("BETA"))
    kv = [
        (L("k_cwd"), cwd),
        (L("k_model"), model),
        (L("k_mode"), "%s %s · %s%s%s" % (L("k_tier"), tier, gtxt, bb, ptxt)),
        (L("k_answers"), i18n.native_name(al)),
    ]
    tasks, links, fab, streak = _week_stats()
    memtxt = "%s %s" % (L("mem_core"),
                        "%.1f%s" % (len(core) / 1000, L("k1000")) if core else L("mem_empty"))
    if tasks:
        wk = (green("%d %s, %d %s" % (tasks, L("w_tasks"), streak, L("w_days_clean")))
              if fab == 0 else
              yellow("%d %s, %d %s" % (tasks, L("w_tasks"), fab, L("w_held"))))
        kv.append((L("k_memory"), "%s · %s: %s" % (memtxt, L("week"), wk)))
    else:
        kv.append((L("k_memory"), memtxt + ((" · " + role) if role else "")))
    labw = max(_dw(k) for k, _ in kv)
    body = [grey(k + " " * (labw - _dw(k))) + "  " + v for k, v in kv]
    upd = update.banner_note()
    if upd:
        body.append(magenta("%s  %s" % (G["arrow"], upd)))
    if not any(config.resolve_key(p) for p in cfg["providers"].values()):
        body.append(yellow("%s  %s" % (G["warn"], L("no_models"))))
    hint = L("just_type").split("/help")[0].rstrip(" .·")
    hint_line = "%s   %s" % (grey(hint + "."), blue("/help"))
    # строка-подсказка в стиле MiMo: лавовая точка + РОТИРУЕМАЯ подсказка (на языке интерфейса)
    tip_line = "%s %s %s" % (lava_accent(brand() or G["dot"]),
                             grey(L("tip") + ":"), grey(i18n.random_tip(lang)))
    slogan = grey(L("slogan"))
    sw = min(width + 2, ansi.term_cols() - 1)
    print()
    print(anim.sparkles(sw, band=0))      # ✦-искры над логотипом (декор, как у MiMo)
    try:
        anim.play_logo()  # «течёт лава» → застыть; на узком — компактный wordmark
    except KeyboardInterrupt:             # #6: Ctrl-C во время логотипа — чистый выход
        print("\033[0m" + anim.logo(lang))
    print(anim.sparkles(sw, band=2))      # ✦-искры под логотипом
    if narrow:                            # узко: без бокса — компактно, рамка не рвётся
        print(_truncate("%s  %s" % (grey("spt " + VERSION), badge("BETA")), width))  # версия
        print(_truncate(slogan, width))   # #5: слоган тоже обрезаем (на терминале уже слогана)
        print()
        for ln in body:
            print("  " + _truncate(ln, width))
        print("\n  " + _truncate(hint_line, width))          # обрезаем — гейт ловил overflow
        print("  " + _truncate(tip_line, width) + "\n")
    else:                                 # широко: бокс адаптивной ширины
        print(box([title, "", "    " + slogan, ""] + body + ["", hint_line]) + "\n")
        print("  " + _truncate(tip_line, ansi.term_cols() - 2))   # tip под боксом (MiMo-стиль)


def _print_result(res, quiet=False, lang="ru"):
    """Карточка результата в стиле дерева: ⏺ готово + ⎿ паспорт (домен · PSQ · модель)."""
    out = sys.stderr if quiet else sys.stdout
    p = res["passport"]
    if quiet:  # -q: сырой ответ в stdout + одна паспорт-строка в stderr (контракт для пайпов)
        print(res["answer"].strip())
        print("spt: done psq=%s tokens=%s" % (p.get("PSQ") or "—", p.get("токены", 0)), file=out)
        return
    from . import anim, mdrender
    print("\n" + mdrender.render(res["answer"].strip()) + "\n")
    L = lambda k: i18n.t(k, lang)  # noqa: E731
    stamp = "%s %s %s" % (ansi.brand() or G["bullet"], G["ok"], i18n.t("done", lang) if "done" in dir(i18n) else "готово")
    print(" %s   %s" % (green(bold(stamp)), grey("ответ готов")), file=out)
    pb, pa = res.get("psq_pair", (None, None))
    if pa is not None:
        psq_row = anim.play_metric(out, pb["psq"] if pb else None, pa["psq"], "PSQ")
    else:
        psq_row = "%s  %s" % (grey("PSQ ".ljust(4)), p.get("PSQ") or "—")
    rows = [
        "%s  %s · %s %s" % (grey(L("k_domain").ljust(8)), p["домен"], L("k_tier"), p["тир"]),
        "%s" % psq_row,
        "%s  %s · %s шагов · %sс" % (grey(L("k_model").ljust(8)), p["модель"], p["шагов"], p["сек"]),
    ]
    if p.get("токены"):  # топливная шкала (ресурс)
        rows.append("%s  %s" % (grey("топливо ".ljust(8)), anim.fuel_gauge(p["токены"])))
    if p.get("гардрейл"):
        rows.append("%s  %s" % (grey("гардрейл".ljust(8)), yellow(p["гардрейл"])))
    for r in rows:
        print("   %s %s" % (grey(G["branch"]), r), file=out)
    res["_actions"] = ["/why", "run"]
    mark = ansi.brand() or G["arrow"]
    acts = "  ".join("%s %s" % (chip(i + 1), lab) for i, lab in enumerate(["разбор", "повтор"]))
    print("   %s %s %s" % (grey(G["branch"]), blue("%s %s:" % (mark, i18n.t("next", lang))), acts), file=out)



# русские алиасы слэш-команд (английские остаются для совместимости)
_RU_ALIAS = {
    "/помощь": "/help", "/повтор": "/retry", "/почему": "/why", "/язык": "/lang",
    "/тема": "/theme", "/модель": "/model", "/цель": "/goal", "/навыки": "/skills",
    "/память": "/memory", "/настройки": "/settings", "/спиннер": "/spinner",
    "/бренд": "/brand", "/разрешения": "/perm", "/продолжить": "/continue",
    "/сессии": "/resume", "/сжать": "/compact", "/ключи": "/keys", "/ссылки": "/links",
    "/цвет": "/theme", "/схема": "/theme", "/макс": "/max",
    "/примеры": "/examples", "/пример": "/examples", "/меню": "/help", "/команды": "/help",
}


def _apply_alias(line):
    """Заменить русскую слэш-команду на английскую (с сохранением аргументов)."""
    head, _, rest = line.partition(" ")
    en = _RU_ALIAS.get(head.lower())
    return (en + ((" " + rest) if rest else "")) if en else line


def _footkey(text):
    """Футер-подсказка в стиле MiMo: ЖИРНАЯ клавиша + серое описание."""
    k, _, d = text.partition(" ")
    return bold(k) + (grey(" " + d) if d else "")


def _provider_error(e, model, cfg):
    print(" %s %s" % (red(G["fail"]), red("провайдер: %s" % str(e)[:200])))
    prov = cfg["providers"].get(model.split("/")[0], {})
    print("\n что сделать:")
    if not config.resolve_key(prov):
        print("   1. добавить ключ            /keys add   (ключа для %s ещё нет)"
              % model.split("/")[0])
    else:
        print("   1. проверить ключ           /keys test %s" % model.split("/")[0])
    print("   2. переключить модель       /model <провайдер/модель>")
    alive = []
    for name, prov in cfg["providers"].items():
        alive.append("%s %s" % (name, green(G["ok"]) if config.resolve_key(prov)
                                else grey("нет ключа")))
    print(grey("      подключены: " + " · ".join(alive)))
    print(grey("\n задача сохранена — /retry повторит её"))


import contextlib
import glob as _glob


@contextlib.contextmanager
def _nullctx():
    yield


_AT_RE = None


def _expand_at_files(task):
    """@путь в задаче → содержимое файла. Большие файлы усекаются
    с пометкой. Возвращает (обогащённая_задача, список_вложенных_файлов)."""
    import re
    global _AT_RE
    if _AT_RE is None:
        _AT_RE = re.compile(r"(?:^|\s)@([^\s@]+)")
    from . import sandbox
    import re as _re
    # @-файл НЕ должен утаскивать секреты/ключи в промт LLM (даже без blackbox)
    secret_re = _re.compile(r"\.env$|\.ssh/|\.aws/|\.pem$|\.key$|id_rsa|id_ed25519|"
                            r"authorized_keys|license\.jwt|/\.spt/|credential", _re.I)
    attached, refused = [], []
    for m in _AT_RE.finditer(task):
        pat = m.group(1)
        hit = False  # T3: разрешился ли @pat хоть во что-то (файл/отказ)
        for path in (_glob.glob(os.path.expanduser(pat)) or [os.path.expanduser(pat)]):
            if os.path.isfile(path):
                hit = True
                rp = os.path.realpath(path)
                if secret_re.search(rp) or sandbox.check_path(rp, {"blackbox": True}):
                    refused.append(path)
                    continue
                try:
                    if os.path.getsize(path) > 2_000_000:  # >2МБ / бинарь — пропуск
                        refused.append(path)
                        continue
                    txt = open(path, encoding="utf-8", errors="replace").read()
                    if "\x00" in txt[:4096]:  # бинарный файл
                        refused.append(path)
                        continue
                except OSError:
                    continue
                n = txt.count("\n") + 1
                if len(txt) > 12000:
                    txt = txt[:12000] + "\n[файл усечён: было %d строк]" % n
                attached.append((path, txt, n))
        if not hit:  # T3: @файл не найден — не молчим, предупреждаем пользователя
            refused.append("@%s (файл не найден)" % pat)
    if not attached:
        return task, [], refused
    blocks = "\n\n".join("=== файл %s (%d строк) ===\n%s" % (p, n, t)
                         for p, t, n in attached)
    return task + "\n\n" + blocks, attached, refused


def _run_one(task, cfg, args, history=None):
    from . import anim
    quiet = getattr(args, "quiet", False)
    lang = cfg.get("ui_lang", "ru")
    # @путь → вложить содержимое файлов в задачу
    if "@" in task:
        task, attached, refused = _expand_at_files(task)
        if not quiet:
            for p, _, n in attached:
                print("   %s %s %s %s" % (grey(G["branch"]), cyan("@"), p,
                                          grey("(%d строк)" % n)))
            for p in refused:
                note = "" if "не найден" in p else " (секрет/большой/бинарь — не вложен)"
                print("   %s %s %s%s" % (grey(G["branch"]), yellow(G["warn"]), p,
                                         yellow(note)))
    # спиннер с чередующимися словами (думаю/выполняю/проверяю) — только TTY, не -q
    global _ACTIVE_SPINNER
    spin = anim.Spinner(key="think", lang=lang) if not quiet else None
    _ACTIVE_SPINNER = spin  # чтобы _confirm паузил его на диалоге (#2)
    log = (lambda *a, **k: None) if quiet else (spin.log if spin else print)
    def status(key):
        if spin:
            spin.set_status(key)
    model = args.model or cfg["default_model"]
    judge = getattr(args, "judge", None) or cfg.get("judge_model") or None
    # offline-first: локальный прогон не ходит молча в облачного судью (приватность)
    if judge and config.is_local(cfg, model) and not config.is_local(cfg, judge):
        log(grey("· судья %s облачный, модель локальная → судит сама модель" % judge))
        judge = None
    gates_on = not (args.no_gates or cfg.get("gates") is False)
    strict = getattr(args, "strict", False) or bool(cfg.get("strict"))
    # режим разрешений: флаги > конфиг > дефолт ask
    perm = ("yolo" if args.yolo else getattr(args, "perm", None)
            or cfg.get("perm") or "ask")
    ctx = spin if spin else _nullctx()
    try:
        with ctx:
            res = agentloop.run_task(
                task, model=model,
                tier=args.tier or cfg.get("tier", "mid"),
                yolo=(perm == "yolo"), gates=gates_on, perm=perm,
                judge_model=judge, strict=strict,
                max_tokens=cfg.get("max_tokens"),
                temperature=(getattr(args, "_tmp", None) if getattr(args, "_tmp", None)
                             is not None else cfg.get("temperature")),  # #13: 0.0 != не задано
                cfg=cfg, confirm=_confirm, log=log, history=history, status=status)
    except providers.ProviderError as e:
        _provider_error(e, args.model or cfg["default_model"], cfg)
        return None
    if not getattr(args, "_silent_cand", False):  # #5: кандидаты Max Mode не печатать
        _print_result(res, quiet=quiet, lang=cfg.get("ui_lang", "ru"))
    if res.get("hard_won") and not quiet and not getattr(args, "_silent_cand", False):
        try:
            st, info = selflearn.harvest(res["journal"],
                                         cfg.get("judge_model") or
                                         (args.model or cfg["default_model"]), cfg)
            log(magenta("· самообучение: %s (%s)" % (st, str(info)[:90])))
        except Exception:  # noqa: BLE001 — самообучение не должно ронять ответ
            pass
    return res


def _why(last):
    if not last:
        print(grey("ещё нет ответа в этой сессии"))
        return
    pb, pa = last.get("psq_pair", (None, None))
    if pb:
        print(bold("PSQ:"), "%.2f → %.2f" % (pb["psq"], pa["psq"]),
              grey("c=%s a=%.2f накрутка=%.2f %s" %
                   ("".join(map(str, pa["c"])), pa["a"], pa["gaming"],
                    str([f[0] for f in pa["flags"]]) if pa["flags"] else "")))
    p = last.get("passport", {})
    print(grey("домен %s · тир %s · модель %s · %s шагов · %s токенов" % (
        p.get("домен", "?"), p.get("тир", "?"), p.get("модель", "?"),
        p.get("шагов", "?"), p.get("токены", 0))))




def _probe(prov, key):
    """(url, headers) живой проверки ключа. Anthropic ≠ Bearer: x-api-key + version."""
    if prov.get("style") == "anthropic":
        return (prov["base_url"].rstrip("/") + "/v1/models",
                {"x-api-key": key, "anthropic-version": "2023-06-01"})
    return (prov["base_url"].rstrip("/") + "/models",
            {"Authorization": "Bearer " + key})


def _settings_panel(cfg, args):
    """Панель быстрых настроек (/settings; аналог Ctrl+P у MiMo — но без raw-mode).
    Внизу — блок кастомизации внешнего вида (цвет/спиннер/бренд-глиф)."""
    from .ansi import box
    lang = cfg.get("ui_lang", "ru")
    rows = [
        "%s  %s" % (grey("модель   "), args.model or cfg["default_model"]),
        "%s  %s" % (grey("тир      "), args.tier or cfg.get("tier", "mid")),
        "%s  %s" % (grey("гейты    "), "off" if args.no_gates else
                    ("strict" if (getattr(args, "strict", False) or cfg.get("strict"))
                     else "on")),  # #7: читаем реальный strict (args, не только cfg)
        "%s  %s" % (grey("разреш.  "), cfg.get("perm", "ask")),
        "%s  %s / %s" % (grey("язык     "), i18n.native_name(lang),
                         i18n.native_name(cfg.get("answer_lang", "ru"))),
        "%s  %s" % (grey("чёрн.ящик"), "вкл" if cfg.get("blackbox") else "выкл"),
        grey("── внешний вид (кастомизация) ──"),
        "%s  %s" % (grey("цвет.схема"), "%s — %s" % (cfg.get("theme", "lava"),
                    ansi._SCHEMES.get(cfg.get("theme", "lava"), {}).get("desc", ""))),
        "%s  %s" % (grey("спиннер  "), _SPINNERS_UI.get(cfg.get("spinner", "pulse"))),
        "%s  %s" % (grey("бренд    "), _BRANDS_UI.get(cfg.get("brand", "triangle"))),
        "%s  %s" % (grey("✦ искры  "), "вкл" if cfg.get("sparkles", True) else "выкл"),
    ]
    head = grey("Настройки spt  ·  /model /tier /gates /perm /lang /theme /spinner /brand")
    print(box([head] + rows))


def _stats_panel(days=14):
    """Роллап телеметрии гейтов из дневной памяти (harness-eng П.9): pass-rate, вето,
    CAPO (cost-per-accepted-outcome), токены по фазам, срабатывания гардрейлов."""
    from .ansi import box
    import collections
    daily = os.path.join(memory.MEM_DIR, "daily")
    phase = collections.Counter()
    n = tok = guard = 0
    psq_sum = psq_cnt = 0.0
    today = datetime.date.today()
    for d in range(days):
        p = os.path.join(daily, (today - datetime.timedelta(days=d)).isoformat() + ".jsonl")
        if not os.path.exists(p):
            continue
        for line in open(p, encoding="utf-8"):
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("event") != "task":
                continue
            n += 1
            tok += ev.get("tokens", 0)
            guard += 1 if ev.get("guardrail") else 0
            _ps = ev.get("psq") or ""
            if "→" in _ps:
                try:
                    psq_sum += float(_ps.split("→")[1]); psq_cnt += 1
                except ValueError:
                    pass
            for k, v in (ev.get("phase_tok") or {}).items():
                phase[k] += v
    if not n:
        print(grey(" статистики ещё нет — выполните задачи (метрики копятся в память)"))
        return
    fk = lambda x: "%.1fk" % (x / 1000) if x >= 1000 else str(int(x))  # noqa: E731
    avg_psq = (psq_sum / psq_cnt) if psq_cnt else None
    rows = [
        "%s  %d задач за %d дн" % (grey("всего   "), n, days),
        "%s  %s" % (grey("ср. PSQ "), ("%.2f" % avg_psq) if avg_psq is not None else "—"),
        "%s  ~%s / задачу · гардрейл ×%d" % (grey("токены  "), fk(tok / n), guard),
    ]
    if phase:
        top = " · ".join("%s %s" % (k, fk(v)) for k, v in phase.most_common(5))
        rows.append("%s  %s" % (grey("фазы    "), top))
    print(box([grey("Статистика · PSQ-телеметрия (%d дн)" % days)] + rows))


def _apply_ui(cfg):
    """Применить кастомизацию из конфига: цвет chrome, бренд-глиф, стиль спиннера.
    Дефолты (lava/triangle/pulse) дают согласованный вид «из коробки»."""
    from . import anim
    # env имеет приоритет (для превью/скриншот-харнесса), иначе — из конфига
    ansi.set_scheme(os.environ.get("SPT_SCHEME") or os.environ.get("SPT_THEME")
                    or cfg.get("theme", "lava"))
    ansi.set_brand(cfg.get("brand", "triangle"))
    anim.set_spinner(cfg.get("spinner", "pulse"))
    anim.set_sparkles(cfg.get("sparkles", True))


# доступные значения кастомизации (для /settings и валидации)
_SPINNERS_UI = {"pulse": "пульс-точка ●∙∙", "fire": "огонь ▁▂▃", "braille": "брайль ⠋⠙⠹",
                "dots": "точки ···"}
_BRANDS_UI = {"triangle": "лава-треугольник ▲", "diamond": "ромб ◆", "dot": "точка ●",
              "spark": "звезда ✻", "square": "квадрат ◼", "none": "без глифа"}


def _ui_cmd(line, cfg, kind):
    """/spinner и /brand: показать/сменить стиль. kind='spinner'|'brand'."""
    from . import anim
    opts = _SPINNERS_UI if kind == "spinner" else _BRANDS_UI
    setter = anim.set_spinner if kind == "spinner" else ansi.set_brand
    parts = line.split()
    cur = cfg.get(kind)
    if len(parts) < 2:
        for k, d in opts.items():
            print(" %s %-9s %s" % (G["pick"] if k == cur else " ", k, grey(d)))
        return
    v = parts[1]
    if v not in opts:
        print(red(" %s: %s" % (kind, " | ".join(opts))))
        return
    cfg[kind] = v
    setter(v)
    config.save(cfg)
    print(green(" %s %s: %s" % (G["ok"], kind, opts[v])))


# меню команд (палитра в стиле MiMo): секция → [(команда, подсказка/алиас)]
_MENU = [
    ("Разговор", [("/retry", "повторить · /повтор"), ("/why", "разбор вердикта · /почему"),
                  ("/links [md]", "библиография · /ссылки")]),
    ("SuperPromt", [("/tier min|mid|max", "бюджет-тир"), ("/gates on|off|strict", "гейты"),
                  ("/model [имя]", "список моделей / сменить (сохраняется) · /модель"),
                  ("/max <задача>", "N кандидатов+судья+KSCR"),
                  ("/goal <цель> :: <задача>", "цель-DoD")]),
    ("Разрешения", [("/perm ask|auto|yolo", "режим · /разрешения"),
                    ("/auto", "без вопросов, кроме критич."), ("/yolo", "автономный")]),
    ("Вид", [("/theme <схема>", "цвет.схема · /цвет /схема"), ("/spinner", "анимация"),
             ("/brand", "бренд-глиф"), ("/lang <код>", "язык · /язык")]),
    ("Сессии · память", [("/continue · /resume", "загрузить сессию"),
                         ("/compact", "сжать историю · /сжать"),
                         ("/memory · /distill · /teach", "самообучение")]),
    ("Прочее", [("@файл", "вложить файл в задачу"), ("/keys add|test", "ключи · /ключи"),
                ("/settings", "все настройки · /настройки"),
                ("exit", "выход · /выход, q")]),
]


def _command_menu(lang="ru"):
    """Палитра команд в стиле MiMo: секции + команда (акцент) + подсказка/алиас (серый).
    Каждая секция несёт серый рельс до правого края — структурно читается как у MiMo."""
    from .ansi import box, blue, layout, _dw
    head = "%s   %s" % (bold("Команды"), grey("наберите / и Tab · esc — закрыть"))
    width, _ = layout()
    inner = width - 2
    lines = []
    for sec, items in _MENU:
        lines.append("")
        rail = max(0, inner - _dw(sec) - 1)                  # рельс от имени секции до края
        lines.append("%s %s" % (blue(bold(sec)), grey(G["box_h"] * rail)))
        for cmd, hint in items:
            lines.append("  %s   %s" % (bold(cmd), grey(hint)))
    print(box([head] + lines, width=width))
    print(grey(" быстрые действия после результата: жать 1 / 2 / 3"))


# примеры-заготовки задач (первый запуск) — показать, что умеет конвейер
_EXAMPLES = {
    "ru": ["Напиши функцию на Python: устойчивый парсер ISO-8601 дат с тестами",
           "Собери сводку по 5 источникам про <тема> с проверяемыми ссылками",
           "Проверь и исправь этот код: @файл.py — найди баги и объясни правки",
           "Составь план лендинга: секции, оффер, CTA, тон — для <продукт>"],
    "en": ["Write a Python function: robust ISO-8601 date parser with tests",
           "Summarize 5 sources on <topic> with verifiable links",
           "Review and fix this code: @file.py — find bugs and explain fixes",
           "Draft a landing plan: sections, offer, CTA, tone — for <product>"],
}


def _examples(lang="ru"):
    """Примеры задач: показать заготовки, чтобы новичок понял формат ввода."""
    from .ansi import box
    ru = lang == "ru"
    head = "%s   %s" % (bold("Примеры задач" if ru else "Example tasks"),
                        grey("скопируйте и адаптируйте" if ru else "copy and adapt"))
    lines = [""]
    for ex in _EXAMPLES.get(lang, _EXAMPLES["en"]):
        lines.append("%s %s" % (blue(G["pick"]), ex))
    lines.append("")
    lines.append(grey(("подсказка: @файл вкладывает файл · /help — все команды" if ru
                       else "hint: @file attaches a file · /help — all commands")))
    print(box(lines, title=("Примеры" if ru else "Examples")))


def _startup_menu(cfg, lang="ru"):
    """Стартовое меню (getting-started): показывается один раз при
    запуске. Возвращает список (метка, команда) для нумерованного быстрого пуска (жать 1/2/3/4)."""
    from .ansi import box, layout, _dw, _truncate
    ru = lang == "ru"
    have_keys = any(config.resolve_key(p) for p in cfg["providers"].values())
    a1 = (("Примеры задач", "/examples") if have_keys else
          ("Добавить ключ", "/keys add")) if ru else (
          ("Example tasks", "/examples") if have_keys else ("Add API key", "/keys add"))
    actions = [a1,
               (("Все команды" if ru else "All commands"), "/help"),
               (("Настройки" if ru else "Settings"), "/settings"),
               (("Оформление" if ru else "Appearance"), "/theme")]
    lead = ("SuperPromt сам подберёт домен, проверит факты и вернёт паспорт с вердиктом."
            if ru else
            "SuperPromt routes your task, verifies facts and returns a verdict passport.")
    width, narrow = layout()
    cells = ["%s  %s" % (chip(i), lab) for i, (lab, _) in enumerate(actions, 1)]
    body = [grey(_truncate(lead, width - 4)), ""]
    if narrow:                                   # телефон: по одной кнопке-чипу в строку
        body += ["  %s" % c for c in cells]
    else:                                        # десктоп: сетка 2×2 (ровные колонки)
        colw = (width - 6) // 2
        for r in range(0, len(cells), 2):
            left = cells[r]
            pad = " " * max(2, colw - _dw(left))
            rest = cells[r + 1] if r + 1 < len(cells) else ""
            body.append("  %s%s%s" % (left, pad, rest))
    print(box(body, title=("С чего начать" if ru else "Getting started")))
    return actions


def _theme_cmd(line, cfg):
    """/theme (или /scheme, /цвет) — ЦВЕТОВАЯ СХЕМА (логотип+chrome+акценты меняются вместе).
    Светофор доверия (PASS/WARN/VETO) НЕ меняется ни в одной схеме — безопасность."""
    from . import ansi
    parts = line.split()
    schemes = {n: ansi._SCHEMES[n]["desc"] for n in ansi.scheme_names()}
    if len(parts) < 2:
        cur = cfg.get("theme", "lava")
        print(bold(" Цветовые схемы:"))
        for t, d in schemes.items():
            sh = ansi._SCHEMES[t]["logo"][0]
            sw = ("\033[38;5;%dm███\033[0m" % sh) if ansi._ON else "   "  # образец цвета
            print(" %s %s %-7s %s" % (G["pick"] if t == cur else " ", sw, t, grey(d)))
        print(grey(" смена: /theme <имя>. Светофор доверия не меняется (безопасность)."))
        return
    t = parts[1]
    if t not in schemes:
        print(red(" схема: " + " | ".join(schemes)))
        return
    cfg["theme"] = t
    ansi.set_scheme(t)
    config.save(cfg)
    print(green(" %s цветовая схема: %s — %s" % (G["ok"], t, schemes[t])))
    from . import anim                       # перерисовать логотип в новой схеме (превью)
    print("\n" + anim.logo(cfg.get("ui_lang", "ru")) + "\n")


def _lang_cmd(line, cfg):
    """/lang — язык интерфейса и ответов. Формы:
       /lang            — показать доступные и текущие
       /lang <код>      — сменить ОБА (интерфейс + ответы)
       /lang ui <код>   — только интерфейс
       /lang answer <код> — только язык ответов LLM"""
    parts = line.split()
    if len(parts) == 1:
        print(" текущий: интерфейс %s · ответы %s" %
              (i18n.native_name(cfg.get("ui_lang", "ru")),
               i18n.native_name(cfg.get("answer_lang", "ru"))))
        print(" доступные:")
        for code, name in i18n.list_langs():
            print("   %-3s %s" % (code, name))
        print(grey(" смена: /lang <код> (оба) · /lang ui <код> · /lang answer <код>"))
        return
    if parts[1] in ("ui", "answer"):
        if len(parts) < 3:  # #8: /lang ui без кода — подсказать форму, не трактовать «ui» как язык
            print(grey(" форма: /lang %s <код>  (напр. /lang %s en)" % (parts[1], parts[1])))
            return
        code = i18n.norm(parts[2])
        key = "ui_lang" if parts[1] == "ui" else "answer_lang"
        cfg[key] = code
        config.save(cfg)
        label = i18n.t("lang_ui_set" if parts[1] == "ui" else "lang_answer_set", code)
        print(green(" %s %s: %s" % (G["ok"], label, i18n.native_name(code))))
        return
    code = i18n.norm(parts[1])
    cfg["ui_lang"] = code
    cfg["answer_lang"] = code
    config.save(cfg)
    print(green(" %s язык: %s (интерфейс + ответы)" % (G["ok"], i18n.native_name(code))))


def _set_model(cfg, args, spec):
    """Сменить модель И СОХРАНИТЬ (default_model в конфиг) — действует сейчас и после перезапуска."""
    args.model = spec
    cfg["default_model"] = spec
    config.save(cfg)
    print(green(" %s модель: %s → сохранено" % (G["ok"], spec)))


def _model_cmd(line, cfg, args):
    """/model <id> — задать и СОХРАНИТЬ. /model без аргумента — показать список моделей и выбрать
    (номер · /слово поиск · точный id). Провайдер берётся из текущей модели, если не указан."""
    cur = args.model or cfg["default_model"]
    prov = cur.partition("/")[0]
    parts = line.split(None, 1)
    if len(parts) > 1:                                    # /model <id> — задать напрямую
        spec = parts[1].strip()
        if "/" not in spec or spec.split("/")[0] not in cfg["providers"]:
            spec = prov + "/" + spec                      # первый сегмент не провайдер → текущий
        _set_model(cfg, args, spec)
        return
    from . import models_api, wizard                      # /model — интерактивный выбор из списка
    print(grey(" текущая: %s" % cur))
    catalog = models_api.list_models(prov, cfg)
    if not catalog:
        print(yellow(" %s список моделей недоступен (нет ключа/сети). Задай id: /model %s/<модель>"
                     % (G["warn"], prov)))
        return
    shown = models_api.search(catalog, "", 10)
    print(bold(" Модели %s (дешёвые/бесплатные выше):" % prov))
    wizard._print_model_rows(shown)
    print(grey(" выбор: номер · /слово поиск · точный id · Enter отмена"))
    while True:
        try:
            sel = input(" model %s " % G["prompt"]).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not sel:
            return
        if sel.startswith("/"):
            found = models_api.search(catalog, sel[1:], 10)
            shown = found or shown
            print(grey("   найдено %d:" % len(shown)) if found else grey("   ничего, уточните"))
            wizard._print_model_rows(shown)
            continue
        if sel.isdigit() and 1 <= int(sel) <= len(shown):
            chosen = shown[int(sel) - 1]["id"]
            break
        chosen = sel
        break
    spec = (chosen if "/" in chosen and chosen.split("/")[0] in cfg["providers"]
            else prov + "/" + chosen)
    _set_model(cfg, args, spec)


def _keys(cmdline, cfg):
    parts = cmdline.split()
    sub = parts[1] if len(parts) > 1 else "add"
    if sub == "add":
        try:
            key = getpass.getpass(" ключ %s " % G["prompt"]).strip()
        except (EOFError, KeyboardInterrupt):
            return
        prov_name = next((p for pref, p in KEY_PREFIX.items()
                          if key.startswith(pref)), None)
        if not prov_name:
            prov_name = input(" провайдер (openrouter/nim/openai/anthropic/google): ").strip()
        if prov_name not in cfg["providers"]:
            print(red(" неизвестный провайдер"))
            return
        var = prov_name.upper() + "_API_KEY"
        envp = os.path.join(config.SPT_DIR, ".env")
        os.makedirs(config.SPT_DIR, exist_ok=True)
        with open(envp, "a", encoding="utf-8") as f:
            f.write("%s=%s\n" % (var, key))
        os.chmod(envp, 0o600)
        cfg["providers"][prov_name]["api_key_file"] = "%s:%s" % (envp, var)
        config.save(cfg)
        print(" %s сохранён указателем в %s (0600); в config.json — только ссылка" %
              (green(G["ok"]), envp))
        _keys("/keys test %s" % prov_name, cfg)
        def_prov = cfg.get("default_model", "").partition("/")[0]
        if def_prov != prov_name and not config.resolve_key(
                cfg["providers"].get(def_prov, {})):
            print(yellow(" модель по умолчанию (%s) без ключа — переключите: "
                         "/model %s/<модель>" % (cfg.get("default_model"), prov_name)))
    elif sub == "test":
        prov_name = parts[2] if len(parts) > 2 else ""
        prov = cfg["providers"].get(prov_name)
        if not prov:
            print(red(" укажите провайдера: /keys test openrouter"))
            return
        key = config.resolve_key(prov)
        if not key:
            print(red(" ключа нет — /keys add"))
            return
        try:
            url, headers = _probe(prov, key)
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as r:
                print(" %s %s живой (HTTP %d)" % (green(G["ok"]), prov_name, r.status))
        except Exception as e:  # noqa: BLE001
            print(" %s %s не отвечает: %s" % (red(G["fail"]), prov_name, str(e)[:120]))


def _post_run(res, task_label, sid, history, session_links):
    """Единая пост-обработка задачи: библиография + история + запись сессии (#4).
    -> (last_task, history, session_links)."""
    if res.get("link_report"):
        seen = {r["value"] for r in session_links}
        session_links = session_links + [r for r in res["link_report"]["results"]
                                         if r["value"] not in seen]
    history = [m for m in res["messages"] if m["role"] in ("user", "assistant")
               and not m.get("tool_calls")][-12:]
    try:
        sessions.append(sid, res["messages"], sessions.next_n(sid))
    except Exception:  # noqa: BLE001 — журнал не важнее ответа
        pass
    return task_label, history, session_links


def repl(cfg, args):
    lang = cfg.get("ui_lang", "ru")  # язык интерфейса (для бокса ввода/подсказок)
    try:  # история ввода + автодополнение слэш-команд (Unix; на Windows молча без них)
        import readline  # noqa: F401
        histfile = os.path.join(config.SPT_DIR, "history")
        os.makedirs(config.SPT_DIR, exist_ok=True)
        try:
            readline.read_history_file(histfile)
        except OSError:
            pass
        import atexit
        atexit.register(lambda: readline.write_history_file(histfile))
        _cmds = sorted(["/help", "/examples", "/retry", "/why", "/links", "/links md",
                        "/tier", "/gates", "/model", "/skills", "/settings", "/max", "/goal",
                        "/perm", "/auto", "/yolo", "/lang", "/theme", "/spinner",
                        "/brand", "/continue", "/resume", "/compact", "/memory",
                        "/distill", "/teach", "/keys", "/exit"] + list(_RU_ALIAS))

        def _completer(text, state):     # дополняем только когда строка — слэш-команда
            if not text.startswith("/"):
                return None
            hits = [c for c in _cmds if c.startswith(text.lower())]
            return hits[state] + " " if state < len(hits) else None
        readline.set_completer(_completer)
        readline.set_completer_delims(" \t")
        readline.parse_and_bind("tab: complete")
    except ImportError:
        pass
    _banner(cfg, args)
    boot_actions = _startup_menu(cfg, lang)   # стартовое меню (getting-started, жать 1/2/3/4)
    sid = sessions.new()
    history, last, last_task = [], None, None
    session_links = []  # верифицированная библиография сессии
    input_hist = []     # история строк ввода (для raw-mode редактора ↑↓)
    while True:
        # адаптивный ввод: статус-строка + футер + СИНИЙ БОКС вокруг ❯ (ширина под терминал)
        w, narrow = ansi.layout()
        cols = ansi.term_cols()
        model_now = args.model or cfg["default_model"]
        gt = green(i18n.t("insurance_on", lang)) if not args.no_gates \
            else yellow(i18n.t("insurance_off", lang))
        pm_now = cfg.get("perm", "ask")
        pmt = {"auto": yellow(" · " + i18n.t("perm_auto", lang)),
               "yolo": red(" · " + i18n.t("perm_yolo", lang))}.get(pm_now, "")
        left = (grey("  %s · %s %s · " % (model_now, i18n.t("k_tier", lang),
                args.tier or cfg.get("tier", "mid"))) + gt + pmt)
        ver = grey("spt " + VERSION)                     # P1.4: версия внизу-справа (стиль MiMo)
        if narrow:
            status = left
        else:
            pad = max(1, cols - ansi._dw(left) - ansi._dw(ver))
            status = left + " " * pad + ver
        print(ansi._truncate(status, cols))
        # футер в стиле MiMo: ЖИРНАЯ клавиша + серое описание (без сиротской точки в начале)
        fitems = [i18n.t("hint_tab", lang), i18n.t("hint_files", lang),
                  i18n.t("hint_cmds", lang)]
        if not narrow:
            fitems.append(i18n.t("hint_interrupt", lang))
        foot = "  " + grey(" · ").join(_footkey(x) for x in fitems)
        print(ansi._truncate(foot, cols))
        # ❯/грань красятся по РЕЖИМУ: зелёный ask+гейты · жёлтый auto/без гейтов · красный yolo
        gcol = red if pm_now == "yolo" else (
            yellow if (pm_now == "auto" or args.no_gates) else green)
        phtxt = i18n.t("input_ph", lang)
        if lineeditor.available():          # RAW-MODE: живой замкнутый бокс + выпадашки / @
            try:
                line = lineeditor.read_line(w, gcol, phtxt, input_hist)
            except KeyboardInterrupt:
                print(blue(G["box_bl"] + G["box_h"] * w + G["box_br"]))
                break
            except Exception as e:          # noqa: BLE001 — сбой raw-mode НЕ роняет терминал
                lineeditor.disable()        # дальше только readline-фолбэк
                print(grey(" (raw-режим отключён: %s)" % str(e)[:60]))
                continue
            if line is None:                # Ctrl-D
                break
            line = line.strip()
        else:                               # ФОЛБЭК readline: рамка + плейсхолдер в верхней грани
            ph = " " + phtxt + " "
            fill = w - 1 - ansi._dw(ph)
            top = ((gcol(G["box_tl"] + G["box_h"]) + grey(ph)
                    + gcol(G["box_h"] * fill + G["box_tr"])) if fill >= 2
                   else gcol(G["box_tl"] + G["box_h"] * w + G["box_tr"]))
            print(top)
            prompt = ansi.rl(blue(G["box_v"]) + " " + gcol(G["prompt"]) + " ")
            try:
                line = input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                print("\n" + blue(G["box_bl"] + G["box_h"] * w + G["box_br"]))
                break
            print(blue(G["box_bl"] + G["box_h"] * w + G["box_br"]))       # низ рамки после ввода
        if not line:
            continue
        input_hist.append(line)             # история для raw-редактора
        # нумерованное быстрое действие: «1» → команда стартового меню (до первой задачи)…
        if line.isdigit() and not last and boot_actions:
            idx = int(line)
            if 1 <= idx <= len(boot_actions):
                line = boot_actions[idx - 1][1]
        # …или из меню прошлого результата (после задачи)
        elif line.isdigit() and last and last.get("_actions"):
            acts = last["_actions"]
            if 1 <= int(line) <= len(acts):
                line = acts[int(line) - 1]
        line = _apply_alias(line)                    # русская слэш-команда → английская
        if line.lower() in ("/exit", "/quit", "exit", "quit", "выход", "q"):
            break
        if line in ("/help", "?", "/menu", "/команды", "/меню"):
            _command_menu(lang)
            continue
        if line in ("/examples", "/example", "/примеры", "/пример"):
            _examples(lang)
            continue
        if line == "/why":
            _why(last)
            continue
        if line.startswith("/links"):
            if not session_links:
                print(grey("ссылок в сессии ещё не было"))
                continue
            if line.endswith(" md"):
                today = datetime.date.today().isoformat()
                body = "# Верифицированная библиография (spt, %s)\n\n" % today
                for r in session_links:
                    if r["status"] in ("ALIVE", "ARCHIVED"):
                        body += "- %s — %s, проверено %s%s\n" % (
                            r["value"], r["status"], today,
                            (", архив " + r["archived_ts"][:8])
                            if r.get("archived_ts") else "")
                path = os.path.join(os.getcwd(), "bibliography.md")
                try:
                    _write_no_symlink(path, body)  # не идём по подложенному симлинку
                except OSError:  # cwd read-only ИЛИ путь — симлинк (аудит LOW)
                    path = os.path.join(config.ensure_dir(), "bibliography.md")
                    _write_no_symlink(path, body)
                    print(yellow("текущая папка недоступна/небезопасна — сохранено в ~/.spt/"))
                # анимация экспорта: «печать» живых ссылок с зелёными галками ⭐
                alive = [r for r in session_links if r["status"] in ("ALIVE", "ARCHIVED")]
                import time as _t
                _tty = sys.stdout.isatty()
                for r in alive:
                    print("   %s %s" % (green(G["ok"]), r["value"][:64]))
                    if _tty and not os.environ.get("SPT_NO_ANIM"):
                        _t.sleep(0.04)
                print(green("экспортировано: %s (%d проверенных источников)"
                            % (path, len(alive))))
            else:
                _links_table(session_links)
            continue
        if line == "/retry":
            if not last_task:
                print(grey("нечего повторять"))
                continue
            line = last_task
        elif line.startswith("/keys"):
            _keys(line, cfg)
            continue
        elif line.startswith("/model"):
            _model_cmd(line, cfg, args)
            continue
        elif line.startswith("/tier"):
            arg = line.split(None, 1)
            if len(arg) > 1 and arg[1] in ("min", "mid", "max"):
                args.tier = arg[1]
            cur = args.tier or cfg.get("tier", "mid")
            for t, d in (("min", "8 шагов · 1 ремонт · 1 скилл — быстро и дёшево"),
                         ("mid", "16 · 2 · 3 — баланс (по умолчанию)"),
                         ("max", "32 · 3 · 5 — сложные задачи, дольше")):
                print(" %s %s   %s" % (G["pick"] if t == cur else " ", t, grey(d)))
            continue
        elif line.split()[0] == "/gates":  # #12: точный разбор, не startswith
            sub = (line.split() + [""])[1]
            if sub not in ("on", "off", "strict"):
                print(grey(" форма: /gates on|off|strict"))
                continue
            args.no_gates = sub == "off"
            args.strict = sub == "strict"
            cfg["gates"] = sub != "off"       # #T6: синхронизируем cfg, иначе strict из
            cfg["strict"] = sub == "strict"   # config.json «залипает» (аудит-тест)
            print(yellow(G["warn"] + " без страховки — ответы не проверяются")
                  if args.no_gates else
                  (red(bold("режим «скептик»: неопределённое = вето")) if args.strict
                   else green("страховка on")))
            continue
        elif line.startswith("/lang"):
            _lang_cmd(line, cfg)
            continue
        elif line.startswith("/perm") or line.startswith("/auto") or line.startswith("/yolo"):
            arg = line.split()
            if line.startswith("/auto"):
                mode = "auto"
            elif line.startswith("/yolo"):
                mode = "yolo"
            elif len(arg) > 1 and arg[1] in ("ask", "auto", "yolo"):
                mode = arg[1]
            else:
                mode = cfg.get("perm", "ask")
            cfg["perm"] = mode
            args.perm = mode
            args.yolo = (mode == "yolo")
            desc = {"ask": green("с подтверждением опасных действий"),
                    "auto": yellow("без подтверждений, но вопрос на КРИТИЧНЫЕ"),
                    "yolo": red(bold("автономный — без ограничений"))}[mode]
            print(" режим разрешений: %s — %s" % (bold(mode), desc))
            continue
        elif line.startswith("/resume") or line.startswith("/continue"):
            sess = sessions.last_sessions(10)
            if not sess:
                print(grey(" нет сохранённых сессий"))
                continue
            if line.startswith("/continue"):
                pick = sess[0][0]  # последняя
            else:
                print(" сессии:")
                for i, (sid_, title, upd) in enumerate(sess, 1):
                    print("   %d %s %s" % (i, grey(upd), (title or "")[:45]))
                try:
                    sel = input(" номер (Enter — отмена) %s " % G["prompt"]).strip()
                except (EOFError, KeyboardInterrupt):
                    continue
                if not sel.isdigit() or not 1 <= int(sel) <= len(sess):
                    continue
                pick = sess[int(sel) - 1][0]
            msgs = sessions.load(pick)
            history = [m for m in msgs if m.get("role") in ("user", "assistant")
                       and not m.get("tool_calls")][-12:]
            print(green(" %s сессия загружена: %d реплик" % (G["ok"], len(history))))
            continue
        elif line.split()[0] in ("/theme", "/scheme"):
            _theme_cmd(line, cfg)
            continue
        elif line == "/spinner" or line.startswith("/spinner "):
            _ui_cmd(line, cfg, "spinner")
            continue
        elif line == "/brand" or line.startswith("/brand "):
            _ui_cmd(line, cfg, "brand")
            continue
        elif line.split()[0] in ("/sparkles", "/искры"):
            from . import anim
            val = (line.split() + [""])[1].lower()
            on = val in ("on", "вкл", "1", "да", "") and val != "off"
            if val in ("off", "выкл", "0", "нет"):
                on = False
            cfg["sparkles"] = on
            anim.set_sparkles(on)
            config.save(cfg)
            print(green(" %s ✦ искры: %s" % (G["ok"], "вкл" if on else "выкл")))
            continue
        elif line.startswith("/compact"):
            from . import memory as _mem
            try:  # T1: ошибка провайдера/Ctrl-C не роняют REPL
                path = _mem.distill(cfg.get("judge_model") or cfg["default_model"], cfg)
            except (KeyboardInterrupt, providers.ProviderError) as e:
                print(yellow("\n дистилляция прервана" if isinstance(e, KeyboardInterrupt)
                             else " дистилляция: %s" % str(e)[:80]))
                continue
            history = history[-4:] if history else []  # сжать активную историю
            print(magenta(" %s история сжата, ядро: %s" %
                          (G["ok"], "обновлено" if path else "нет событий")))
            continue
        elif line.startswith("/settings"):
            _settings_panel(cfg, args)
            continue
        elif line.split()[0] in ("/stats", "/статистика"):
            _stats_panel()
            continue
        elif line.startswith("/max"):
            arg = line.split(None, 1)
            if len(arg) < 2:
                print(grey(" форма: /max <задача>  (N кандидатов + судья + KSCR)"))
                continue
            from . import features
            def _mm(t, tmp):
                args._tmp = tmp
                args._silent_cand = True   # #5: кандидаты не печатаем
                r = _run_one(t, cfg, args, history)
                args._tmp = None
                args._silent_cand = False
                return r
            try:  # #3: Ctrl-C/ошибка провайдера не роняют REPL
                res = features.max_mode(arg[1], cfg, args, _mm, n=3, log=print)
            except (KeyboardInterrupt, providers.ProviderError) as e:
                print(yellow("\n прервано" if isinstance(e, KeyboardInterrupt)
                             else " ошибка: %s" % str(e)[:80]))
                continue
            if res:
                _print_result(res, lang=lang)   # #5: печатаем только лучший
                last = res
                last_task, history, session_links = _post_run(  # #4: сохранить сессию
                    res, "/max " + arg[1], sid, history, session_links)
            continue
        elif line.startswith("/goal"):
            rest = line[len("/goal"):].strip()
            sep = "::" if "::" in rest else ("|" if "|" in rest else None)
            if not sep:  # #12: проверяем наличие разделителя, не число токенов
                print(grey(" форма: /goal <цель-DoD> :: <задача>"))
                print(grey(" пример: /goal 5 рабочих ссылок :: подбери статьи по RAG"))
                continue
            goal, gtask = [x.strip() for x in rest.split(sep, 1)]
            if not goal or not gtask:
                print(grey(" укажите и цель, и задачу"))
                continue
            from . import features
            try:  # #3
                res = features.run_with_goal(gtask, goal, cfg, args,
                                             lambda t: _run_one(t, cfg, args, history))
            except (KeyboardInterrupt, providers.ProviderError) as e:
                print(yellow("\n прервано" if isinstance(e, KeyboardInterrupt)
                             else " ошибка: %s" % str(e)[:80]))
                continue
            if res:
                last = res
                last_task, history, session_links = _post_run(
                    res, "/goal " + rest, sid, history, session_links)
            continue
        elif line == "/skills":
            for n, d in selflearn.list_skills():
                print(" ", n, "—", d)
            continue
        elif line == "/memory":
            print(memory.load_core() or grey("(ядро пусто)"))
            continue
        elif line == "/distill":
            try:  # T1
                path = memory.distill(cfg.get("judge_model") or cfg["default_model"], cfg)
                print(magenta("дистилляция: %s" % (path or "нет событий")))
            except (KeyboardInterrupt, providers.ProviderError) as e:
                print(yellow("\n прервано" if isinstance(e, KeyboardInterrupt)
                             else " дистилляция: %s" % str(e)[:80]))
            continue
        elif line == "/teach":
            try:  # T1
                data = selflearn.teach(cfg.get("judge_model") or cfg["default_model"], cfg)
                print(magenta("обучатель: " + ("нет данных" if not data else
                              "; ".join(map(str, data.get("diagnosis", [])[:3])))))
            except (KeyboardInterrupt, providers.ProviderError) as e:
                print(yellow("\n прервано" if isinstance(e, KeyboardInterrupt)
                             else " обучатель: %s" % str(e)[:80]))
            continue
        elif line.startswith("/"):
            print(grey("неизвестная команда — /help"))
            continue
        last_task = line
        n0 = len(history)
        try:
            res = _run_one(line, cfg, args, history)
        except KeyboardInterrupt:
            print(yellow("\n" + G["warn"] + " прервано — /retry повторит задачу"))
            memory.record("interrupted", {"task": line[:200]})
            continue
        if res:
            last = res
            if res.get("link_report"):
                seen = {r["value"] for r in session_links}
                session_links += [r for r in res["link_report"]["results"]
                                  if r["value"] not in seen]
            history = [m for m in res["messages"] if m["role"] in ("user", "assistant")
                       and not m.get("tool_calls")][-12:]
            try:
                sessions.append(sid, res["messages"][n0:], n0)
            except Exception:  # noqa: BLE001 — журнал никогда не важнее ответа
                print(grey("(история сессии не записана — база занята)"))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="spt", description=__doc__)
    ap.add_argument("command", nargs="?", default="repl",
                    help="repl | run | gate | setup | models | sessions | distill | "
                         "teach | creative")
    ap.add_argument("task", nargs="*", help="задача (для run)")
    ap.add_argument("--model", help="провайдер/модель (напр. ollama/qwen3:8b)")
    ap.add_argument("--judge", help="модель-судья PSQ (по умолчанию из конфига; "
                                    "для локальной модели облачный судья не используется)")
    ap.add_argument("--tier", choices=["min", "mid", "max"])
    ap.add_argument("--yolo", action="store_true",
                    help="автономный режим без ограничений (не спрашивать НИКОГДА)")
    ap.add_argument("--perm", choices=["ask", "auto", "yolo"],
                    help="разрешения: ask (спрашивать) · auto (вопрос только на критич.) · "
                         "yolo (автономный)")
    ap.add_argument("--auto", action="store_true",
                    help="то же, что --perm auto: без подтверждений, но вопрос на критич.")
    ap.add_argument("--no-gates", action="store_true", help="отключить PSQ/KSCR-гейты")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="stdout = только ответ; паспорт-строка в stderr")
    ap.add_argument("-v", "--verbose", action="store_true", help="подробный лог")
    ap.add_argument("--strict", action="store_true",
                    help="режим «скептик»: неопределённые ссылки = вето")
    ap.add_argument("--json", action="store_true", help="(gate) отчёт в JSON")
    ap.add_argument("--code", action="store_true",
                    help="(gate) также исполнять python-чеки из текста")
    ap.add_argument("--lang", help="язык интерфейса и ответов (ru en zh kk fr ja es de …)")
    ap.add_argument("--no-wizard", action="store_true",
                    help="не запускать визуальный мастер настройки")
    ap.add_argument("--setup", action="store_true",
                    help="запустить визуальный мастер настройки принудительно")
    args, extra = ap.parse_known_args(argv)
    args.task = list(args.task) + extra
    if getattr(args, "auto", False) and not args.perm:
        args.perm = "auto"
    # не-UTF локаль (LANG=C, cp1251-редирект): жить с '?', а не падать с трейсбеком
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure") and not (s.encoding or "").lower().startswith("utf"):
            s.reconfigure(errors="replace")
    cfg = config.load()
    _apply_ui(cfg)  # тема/бренд-глиф/спиннер из конфига (кастомизация в /settings)

    # язык из флага --lang (разово переопределяет конфиг для этого запуска)
    if args.lang:
        code = i18n.norm(args.lang)
        cfg["ui_lang"] = code
        cfg["answer_lang"] = code

    # ролевой доступ (owner / trusted / subscriber) — бета-костыль вход по логину/подписке
    if args.command in ("repl", "run", "gate", "setup") and sys.stdin.isatty():
        from . import auth
        if auth.enabled(cfg):
            role = auth.gate(cfg)
            if role is None:
                print(red(" доступ закрыт. Нужен аккаунт (логин/пароль) или ключ подписки."))
                sys.exit(4)

    # визуальный онбординг: первый запуск repl без ключей на TTY (или --setup)
    if args.command in ("repl", "setup") or args.setup:
        no_key = not any(config.resolve_key(p) for p in cfg["providers"].values())
        want = args.setup or args.command == "setup" or (
            no_key and not cfg.get("onboarded") and not args.no_wizard
            and not os.environ.get("SPT_NO_WIZARD"))
        if want and sys.stdin.isatty():
            from . import wizard
            try:
                if not wizard.run(cfg):
                    return
            except KeyboardInterrupt:
                print(yellow("\n мастер прерван"))
            cfg = config.load()
        if args.command == "setup":
            return

    if args.command == "run":
        if not args.task:
            ap.error("run требует текст задачи")
        try:
            res = _run_one(" ".join(args.task), cfg, args)
        except KeyboardInterrupt:
            sys.exit(130)  # прерывание пользователем; вне контракта 0/2/3
        if res is None:
            sys.exit(2)
        sys.exit(3 if res.get("verdict") == "VETO" else 0)
    elif args.command == "models":
        for name, p in cfg["providers"].items():
            key = config.resolve_key(p)
            mark = (green(G["ok"] + " локальный") if p.get("local") and key == "local"
                    else green(G["ok"]) if key else red(G["fail"] + " нет ключа"))
            print("%-12s %-9s %-45s %s" % (name, p.get("style"), p["base_url"], mark))
    elif args.command == "sessions":
        for sid, title, upd in sessions.last_sessions():
            print(sid, upd, title)
    elif args.command == "distill":
        print(memory.distill(cfg.get("judge_model") or cfg["default_model"], cfg)
              or "нет событий")
    elif args.command == "teach":
        data = selflearn.teach(cfg.get("judge_model") or cfg["default_model"], cfg)
        print("нет данных" if not data else
              "\n".join("- " + str(d) for d in data.get("diagnosis", [])))
    elif args.command == "creative":
        data = selflearn.creative_cycle(cfg.get("judge_model") or cfg["default_model"], cfg)
        if not data:
            print("нет данных")
        else:
            for i in data.get("ideas", []):
                print(magenta("- " + str(i)))
    else:
        repl(cfg, args)


if __name__ == "__main__":
    main()
