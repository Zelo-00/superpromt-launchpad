"""Визуальный язык spt: светофор доверия (ANSI), глифы, кроссплатформенная деградация.
Правила: цвет никогда не единственный носитель смысла (рядом глиф+слово);
текст ответа модели не раскрашивается; NO_COLOR/не-TTY/dumb — цвета off."""
import os
import re
import shutil
import sys

_WIN_VT = False


def _enable_win_vt():
    """Windows 10+: включить обработку VT-последовательностей в консоли."""
    global _WIN_VT
    if os.name == "nt" and not _WIN_VT:
        os.system("")  # побочный эффект: включает VT в cmd/PowerShell
        _WIN_VT = True


def color_on(stream=None):
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR") or os.environ.get("CLICOLOR_FORCE"):
        return True
    if os.environ.get("TERM") == "dumb":
        return False
    if not hasattr(stream, "isatty") or not stream.isatty():
        return False
    _enable_win_vt()
    return True


_ON = color_on()


def _c(code, s):
    return "\033[%sm%s\033[0m" % (code, s) if _ON else str(s)


def green(s):  # PASS, живая ссылка, живой провайдер
    return _c("32", s)


def red(s):  # VETO, фабрикация, фатальная ошибка
    return _c("31", s)


def yellow(s):  # WARN, ABSTAIN, [НЕПРОВЕРЕНО], ремонт, без страховки
    return _c("33", s)


def cyan(s):  # процесс: роутер, PSQ, шаги, инструменты
    return _c("36", s)


def magenta(s):  # самообучение/память
    return _c("35", s)


def grey(s):  # вторичное: тайминги, рамки, подсказки
    return _c("90", s)


def bold(s):
    return _c("1", s)


def chip(n):
    """Кнопка-цифра: reverse-video « n » при цвете (читается как нажимаемая кнопка),
    [n] в ч/б/ASCII. Единый вид нумерованных действий (старт-меню, «дальше», выбор)."""
    s = str(n)
    if not _ON:
        return "[%s]" % s
    return "\033[7m %s \033[0m" % s            # инверсия — атрибут, работает и в mono-схеме


def badge(text):
    """Пилюля-бейдж: тёмный текст на цветном фоне (« BETA ») при цвете, [TEXT] в ч/б."""
    if not _ON:
        return "[%s]" % text
    return "\033[30;43m %s \033[0m" % text     # чёрный на жёлтом (нейтрально к схеме)


_UTF = (sys.stdout.encoding or "").lower().startswith("utf") and not os.environ.get("SPT_ASCII")

G = {  # глифы: UTF-8 / ASCII
    "ok": "✓" if _UTF else "OK",
    "fail": "✗" if _UTF else "XX",
    "warn": "⚠" if _UTF else "!!",
    "abstain": "○" if _UTF else "--",
    "tool": "⚙" if _UTF else "*",
    "repair": "↻" if _UTF else "~",
    "dot": "·" if _UTF else ".",
    "bar_on": "▰" if _UTF else "#",
    "bar_off": "▱" if _UTF else "-",
    "prompt": "❯" if _UTF else ">",
    "pick": "▸" if _UTF else ">",
    # бренд-марка и рамки (стиль Claude Code, тема лавы)
    "spark": "✻" if _UTF else "*",
    "box_tl": "╭" if _UTF else "+", "box_tr": "╮" if _UTF else "+",
    "box_bl": "╰" if _UTF else "+", "box_br": "╯" if _UTF else "+",
    "box_h": "─" if _UTF else "-", "box_v": "│" if _UTF else "|",
    # дерево tool-use / этапов
    "bullet": "⏺" if _UTF else "*", "branch": "⎿" if _UTF else "\\_",
    "arrow": "→" if _UTF else "->", "back": "←" if _UTF else "<-",
    # todo-чеклист
    "todo_done": "☑" if _UTF else "[x]", "todo_now": "▸" if _UTF else ">",
    "todo_wait": "☐" if _UTF else "[ ]", "todo_skip": "⊘" if _UTF else "[-]",
}


def _dw(s):
    """Дисплей-ширина строки без ANSI: широкие CJK/эмодзи = 2 колонки (иначе рамки
    боксов «поедут» на китайском/японском/корейском интерфейсе)."""
    import unicodedata
    s = re.sub(r"\033\[[0-9;]*m", "", s)
    w = 0
    for ch in s:
        if unicodedata.combining(ch):
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


# ЦВЕТОВЫЕ СХЕМЫ — НАСТРАИВАЕМЫЕ (цвет логотипа + chrome + акцентов меняется вместе).
# chrome — акцент рамок/дерева/промпта; logo — градиент логотипа (верх→низ); hot — раскалённый
# гребень/блик. Светофор доверия (green/yellow/red) НЕ входит — ЗАФИКСИРОВАН (безопасность).
_SCHEMES = {
    "lava":   {"chrome": 39,   "logo": [220, 214, 208, 202, 160], "hot": 226,
               "desc": "оранжево-красная лава + синий (по умолчанию)"},
    "ocean":  {"chrome": 45,   "logo": [51, 45, 39, 33, 27],      "hot": 87,
               "desc": "бирюзово-синяя волна"},
    "forest": {"chrome": 35,   "logo": [82, 46, 40, 34, 22],      "hot": 118,
               "desc": "зелёный лес"},
    "royal":  {"chrome": 99,   "logo": [213, 171, 141, 99, 57],   "hot": 219,
               "desc": "фиолетово-пурпурный"},
    "amber":  {"chrome": 244,  "logo": [226, 220, 214, 208, 202], "hot": 231,
               "desc": "золотисто-янтарный"},
    "rose":   {"chrome": 168,  "logo": [219, 213, 205, 199, 161], "hot": 225,
               "desc": "розово-малиновый"},
    "anthropic": {"chrome": 173, "logo": [216, 180, 173, 167, 131], "hot": 215,
                  "desc": "тёплая терракота Anthropic/Claude (#d97757)"},
    "mono":   {"chrome": None,  "logo": [252, 248, 244, 240, 236], "hot": 255,
               "desc": "монохром (ч/б, узкие терминалы)"},
}
SCHEME = os.environ.get("SPT_SCHEME") or os.environ.get("SPT_THEME") or "lava"


def scheme_names():
    return list(_SCHEMES)


def set_scheme(name):
    """Сменить цветовую схему (логотип+chrome+акценты). Светофор доверия не трогается."""
    global SCHEME
    if name in _SCHEMES:
        SCHEME = name


set_theme = set_scheme               # обратная совместимость (/theme, старые вызовы)
THEME = SCHEME                        # алиас для старого кода


def scheme():
    return _SCHEMES.get(SCHEME, _SCHEMES["lava"])


def chrome_shade():
    return scheme()["chrome"]


def logo_shades():
    return scheme()["logo"]


def hot_shade():
    return scheme()["hot"]


def blue(s):
    """Акцент chrome (рамки, дерево, промпт). Цвет зависит от активной схемы."""
    if not _ON:
        return s
    shade = chrome_shade()
    if shade is None:  # mono — серый жирный
        return "\033[1;90m%s\033[0m" % s
    return "\033[38;5;%dm%s\033[0m" % (shade, s)


def term_cols():
    """Ширина терминала в колонках (уважает $COLUMNS — удобно для тестов --narrow)."""
    return shutil.get_terminal_size((80, 24)).columns


def layout():
    """Адаптивная раскладка: (внутр_ширина_бокса, is_narrow). Один источник истины —
    все боксы/линии/футер берут ширину отсюда, поэтому рамки не «висят» на телефоне."""
    cols = term_cols()
    width = max(4, min(72, cols - 2))    # рамка ВСЕГДА влезает: width+2 <= cols (без пола 20,
    return width, cols < 50              # иначе при cols<22 бокс был шире экрана)


def _truncate(s, maxw):
    """Обрезать строку до maxw дисплей-колонок, сохраняя ANSI-коды и добавляя «…»."""
    import unicodedata
    if _dw(s) <= maxw:
        return s
    ell = "…" if _UTF else ".."
    budget = maxw - _dw(ell)         # резервируем место под многоточие → _dw(итог) ≤ maxw всегда
    if budget < 0:                   # даже «…» не влезает (крайне узко) — режем жёстко, без многоточия
        budget, ell = maxw, ""
    out, w, i = [], 0, 0
    while i < len(s):
        m = re.match(r"\033\[[0-9;]*m", s[i:])
        if m:
            out.append(m.group(0))
            i += m.end()
            continue
        ch = s[i]
        cw = 0 if unicodedata.combining(ch) else (
            2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1)
        if w + cw > budget:
            break
        out.append(ch)
        w += cw
        i += 1
    return "".join(out) + ell + ("\033[0m" if _ON else "")


def box(lines, width=None, accent=None, title=None):
    """Бокс с рамкой (стиль Claude Code). width=None → адаптивно под терминал.
    title → заголовок ВСТРОЕН в верхнюю грань: ╭─ Заголовок ─────╮ (MiMo-стиль).
    Длинные строки аккуратно обрезаются по ширине (рамка не ломается)."""
    accent = accent or blue
    if width is None:
        width, _ = layout()
    inner = width - 2
    if title:                                   # заголовок в рамке: TL H ' ' title ' ' H*fill TR
        tt = _truncate(title, max(1, width - 5))
        fill = max(0, width - 3 - _dw(tt))
        top = (accent(G["box_tl"] + G["box_h"] + " ") + bold(tt)
               + accent(" " + G["box_h"] * fill + G["box_tr"]))
    else:
        top = accent(G["box_tl"] + G["box_h"] * width + G["box_tr"])
    bot = accent(G["box_bl"] + G["box_h"] * width + G["box_br"])
    out = [top]
    for ln in lines:
        seg = _truncate(ln, inner)
        pad = inner - _dw(seg)
        out.append(accent(G["box_v"]) + " " + seg + " " * max(0, pad) + " "
                   + accent(G["box_v"]))
    out.append(bot)
    return "\n".join(out)


def rl(s):
    """Обернуть ANSI-коды в маркеры readline (\\001..\\002), чтобы курсор/перенос ввода
    считались верно — иначе рамка-промпт «съезжает» при редактировании."""
    return re.sub(r"(\033\[[0-9;]*m)", "\001\\1\002", s)


# бренд-акцент (замена «звёздочки»): конфигурируемо, дефолт — лавовый треугольник
_BRANDS = {"triangle": "▲", "diamond": "◆", "dot": "●", "spark": "✻",
           "square": "◼", "none": ""}
_BRAND = "triangle"


def set_brand(name):
    global _BRAND
    if name in _BRANDS:
        _BRAND = name


def brand():
    """Текущий бренд-глиф (для баннера/статусов). ASCII-fallback — '^'."""
    if not _UTF:
        return "" if _BRAND == "none" else "^"
    return _BRANDS.get(_BRAND, "▲")


def lava_accent(s, shade=None):
    """Акцент бренда в цвете АКТИВНОЙ СХЕМЫ (по умолч. средний тон логотипа)."""
    if not _ON:
        return s
    if shade is None:
        sh = logo_shades()
        shade = sh[len(sh) // 2]
    return "\033[38;5;%dm%s\033[0m" % (shade, s)


def lava_gradient(s):
    """Строка в градиенте активной схемы посимвольно (верхний тон → нижний)."""
    if not _ON or not s.strip():
        return s
    sh = logo_shades()
    n = max(1, len(s) - 1)
    out = []
    for i, ch in enumerate(s):
        shade = sh[min(len(sh) - 1, i * len(sh) // (n + 1))]
        out.append("\033[38;5;%dm%s" % (shade, ch))
    return "".join(out) + "\033[0m"


def trust_bar(alive, total, width=10):
    """Полоска доверия: доля подтверждённых ссылок."""
    if total <= 0:
        return grey("— без внешних фактов —")
    filled = round(width * alive / total)
    bar = G["bar_on"] * filled + G["bar_off"] * (width - filled)
    if alive == total:
        return green(bar)
    return yellow(bar) if alive > 0 else red(bar)
