"""Анимации spt: логотип SuperPromt с «текущей лавой» и спиннер ожидания с
чередующимися словами-статусами (думаю / выполняю / проверяю …). stdlib-ANSI,
работает в фоновом потоке; на не-TTY/NO_COLOR — тихо деградирует (без анимации)."""
import itertools
import os
import shutil
import sys
import threading
import time

from . import i18n
from .ansi import _ON, _UTF, blue, bold, grey, hot_shade, logo_shades, red, yellow


def _rows():
    """Палитра логотипа из АКТИВНОЙ цветовой схемы (верх раскалён → низ остывает)."""
    return logo_shades()


def _lava(ch, shade):
    if not _ON:
        return ch
    return "\033[38;5;%dm%s\033[0m" % (shade, ch)


# логотип «SuperPromt» — ЗАЛИТЫЙ блочный шрифт (стиль MiMo Code), буквы закрашены лавой.
# Широкий экран → блочный SUPERPROMT (59 кол); узкий (телефон) → лавовый wordmark (влезает).
_LETTERS = {
    "S": ["█████", "█    ", "█████", "    █", "█████"],
    "U": ["█   █", "█   █", "█   █", "█   █", "█████"],
    "P": ["█████", "█   █", "█████", "█    ", "█    "],
    "E": ["█████", "█    ", "████ ", "█    ", "█████"],
    "R": ["█████", "█   █", "█████", "█  █ ", "█   █"],
    "O": ["█████", "█   █", "█   █", "█   █", "█████"],
    "M": ["█   █", "██ ██", "█ █ █", "█   █", "█   █"],
    "T": ["█████", "  █  ", "  █  ", "  █  ", "  █  "],
}
def _block_of(word):
    """5-строчный залитый блок для слова."""
    return [" ".join(_LETTERS[c][r] for c in word) for r in range(5)]


_BLOCK = _block_of("SUPERPROMT")                 # широкий: одна строка (59 кол)
_BLOCK_W = len(_BLOCK[0])
# УЗКИЙ (телефон): БОЛЬШИЕ буквы в 2 строки. ПУСТАЯ строка-зазор между словами, иначе низ
# SUPER касается верха PROMT и слова сливаются в кашу (жалоба «сливается друг под другом»).
_SUP, _PRO = _block_of("SUPER"), _block_of("PROMT")
_STACK_W = len(_SUP[0])
_STACK = _SUP + [" " * _STACK_W] + _PRO
_WORDMARK = "SuperPromt"


def _logo_segments(cols):
    """Сегменты логотипа под ширину (каждый = блок-строки одного слова). Между сегментами
    и под низом печатается фирменная лавовая полоса. Широкий → [SUPERPROMT] одним сегментом;
    телефон → [SUPER, PROMT] (полоса-разделитель между ними чинит слипание); <31 → None (wordmark)."""
    if not _UTF:
        return None
    if cols >= _BLOCK_W + 2:
        return [_BLOCK]
    if cols >= _STACK_W + 2:
        return [_SUP, _PRO]
    return None


def _shade_at(i, n):
    """Тон вертикального жара для строки i из n (верх раскалён → низ остывает)."""
    rows = _rows()
    return rows[min(len(rows) - 1, i * len(rows) // max(1, n))]

# слова-статусы для спиннера (мультиязык; ключи → фразы)
STATUS = {
    "think":  {"ru": "думаю", "en": "thinking", "zh": "思考中", "kk": "ойлаймын",
               "fr": "réflexion", "ja": "考え中"},
    "route":  {"ru": "маршрутизирую", "en": "routing", "zh": "路由中", "kk": "бағыттаймын",
               "fr": "routage", "ja": "ルーティング"},
    "psq":    {"ru": "оцениваю запрос", "en": "scoring prompt", "zh": "评估提示",
               "kk": "сұранысты бағалаймын", "fr": "évaluation", "ja": "評価中"},
    "exec":   {"ru": "выполняю", "en": "executing", "zh": "执行中", "kk": "орындаймын",
               "fr": "exécution", "ja": "実行中"},
    "tool":   {"ru": "работаю инструментом", "en": "running tool", "zh": "调用工具",
               "kk": "құралмен жұмыс", "fr": "outil", "ja": "ツール実行"},
    "verify": {"ru": "проверяю ссылки", "en": "verifying links", "zh": "验证链接",
               "kk": "сілтемелерді тексеремін", "fr": "vérification", "ja": "検証中"},
    "repair": {"ru": "чиню результат", "en": "repairing", "zh": "修复中",
               "kk": "түзетемін", "fr": "réparation", "ja": "修復中"},
    "search": {"ru": "ищу", "en": "searching", "zh": "搜索中", "kk": "іздеймін",
               "fr": "recherche", "ja": "検索中"},
}

# индикатор процесса — КОНФИГУРИРУЕМ (набор в /settings). Дефолт — пульс-точка.
_SPINNERS = {
    "pulse":   ["●∙∙", "∙●∙", "∙∙●", "∙●∙"],          # бегущая точка (выбор пользователя)
    "fire":    list("▁▂▃▄▅▆▇▆▅▄▃▂"),                   # огненные блоки (прежний)
    "braille": list("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"),                  # брайль (как у многих CLI)
    "dots":    ["·  ", "·· ", "···", " ··", "  ·", "   "],
}
_SPIN_STYLE = "pulse"
_SPIN_ASCII = ["o..", ".o.", "..o", ".o."]           # ASCII-fallback (пульс)


def set_spinner(name):
    global _SPIN_STYLE
    if name in _SPINNERS:
        _SPIN_STYLE = name


def _spin_frames():
    if not _UTF:
        return _SPIN_ASCII
    return _SPINNERS.get(_SPIN_STYLE, _SPINNERS["pulse"])


def _render_spin(frame, shade):
    """Раскрасить кадр: активные символы — лавой (жар растёт), фон-точки — серым."""
    if not _ON:
        return frame
    return "".join(_lava(c, shade) if c not in ("∙", " ", ".") else grey(c)
                   for c in frame)


def _heat(el):
    """«Жар растёт»: цвет по времени — <5с оранж, 5-15с, >15с алый (задача накаляется)."""
    if el < 5:
        return 214
    if el < 15:
        return 208
    return 160


def status_word(key, lang="ru"):
    d = STATUS.get(key, {})
    return d.get(i18n.norm(lang)) or d.get("en") or key


def fuel_gauge(tokens, cap=None):
    """Топливная шкала токенов (блоки, цвет по заполнению — НЕ светофор доверия, это ресурс)."""
    from .ansi import G, green, grey, red, yellow, _ON
    cap = cap or 32000
    frac = min(1.0, tokens / cap) if cap else 0
    w = 12
    filled = round(w * frac)
    block, empty = ("█", "░") if _UTF else ("#", "-")
    bar = block * filled + empty * (w - filled)
    col = green if frac < 0.7 else (yellow if frac < 0.9 else red)
    tail = " (сожми: /compact)" if frac >= 0.9 else ""
    ktok = "%.1fk" % (tokens / 1000) if tokens >= 1000 else str(tokens)
    sep = "▐" if _UTF else "|"            # разделитель тоже деградирует на ASCII (иначе мохибейк)
    return "%s %s%s токенов%s" % (col(bar) if _ON else bar, grey(sep), ktok,
                                  grey(tail)) if _ON else "%s %s токенов%s" % (bar, ktok, tail)


def metric_bar(value, width=12, threshold=0.8):
    """Шкала метрики 0..1 (PSQ): зелёная если ≥ порога, жёлтая ниже. Не светофор доверия."""
    from .ansi import green, grey, yellow, _ON
    v = max(0.0, min(1.0, value))
    filled = round(width * v)
    block, empty = ("▰", "▱") if _UTF else ("#", "-")
    bar = block * filled + empty * (width - filled)
    col = green if v >= threshold else yellow
    return (col(bar) if _ON else bar) + " %.2f" % value


def play_metric(stream, before, after, label="PSQ", threshold=0.8):
    """Анимация метрики: шкала растёт от before к after (видно ремонт). -> финальная строка."""
    from .ansi import grey
    final = "%s %s" % (grey(label.ljust(4)), metric_bar(after, threshold=threshold))
    if not _anim_ok(stream) or before is None or abs(after - before) < 0.01:
        return final
    steps = 8
    for k in range(steps + 1):
        v = before + (after - before) * k / steps
        stream.write("\r %s %s" % (grey(label.ljust(4)), metric_bar(v, threshold=threshold)))
        stream.flush()
        time.sleep(0.04)
    stream.write("\r\033[K")
    stream.flush()
    return final


def separator(width=None):
    """Разделитель между этапами: синяя линия с лавовым бренд-акцентом (адаптивная ширина)."""
    from .ansi import G, blue, brand, layout
    if width is None:
        width = layout()[0]
    line = G["box_h"] * width
    mark = brand()
    if not _ON or not _UTF or not mark:
        return blue(line)
    mid = width // 2
    return blue(line[:mid]) + _lava(mark, hot_shade()) + blue(line[mid + len(mark):])


def _anim_ok(stream=None):
    """Анимации только на TTY с цветом и без SPT_NO_ANIM."""
    stream = stream or sys.stdout
    return (_ON and hasattr(stream, "isatty") and stream.isatty()
            and not os.environ.get("SPT_NO_ANIM"))


def _paint_row(line, shade):
    """Вертикальный жар: строка залита одним тоном (верх раскалён → низ остывает) —
    расплав «стекает вниз», а не пятнистый горизонтальный градиент."""
    if not _ON:
        return line
    return "".join(("\033[38;5;%dm%s" % (shade, ch)) if ch != " " else " "
                   for ch in line) + "\033[0m"


def _paint_col(line, hot, shade):
    """Кадр анимации: вертикальный жар (тон строки) + БЕГУЩИЙ раскалённый блик в колонке hot —
    логотип переливается и одновременно стекает вниз (цвета из активной схемы)."""
    if not _ON:
        return line
    rows = _rows()
    base = shade
    lead = rows[1] if len(rows) > 1 else base
    out = []
    for x, ch in enumerate(line):
        if ch == " ":
            out.append(" ")
            continue
        d = abs(x - hot)
        shade = hot_shade() if d == 0 else (lead if d == 1 else base)   # блик поверх жара
        out.append("\033[38;5;%dm%s" % (shade, ch))
    return "".join(out) + "\033[0m"


def _paint_grad(line, bold_it=False):
    """Статичный лавовый градиент по колонкам (оранжевый слева → красный справа)."""
    if not _ON:
        return line
    w = len(line)
    b = "1;" if bold_it else ""
    row = []
    for x, ch in enumerate(line):
        if ch == " ":
            row.append(" ")
            continue
        rows = _rows()
        shade = rows[min(len(rows) - 1, x * len(rows) // max(1, w))]
        row.append("\033[%s38;5;%dm%s" % (b, shade, ch))
    return "".join(row) + "\033[0m"


_SPARK_ON = True   # ✦-искры вкл/выкл (кастомизируется из конфига)


def set_sparkles(on):
    global _SPARK_ON
    _SPARK_ON = bool(on)


def sparkles(width, band=0):
    """Декоративные ✦-искры (стиль MiMo), редко разбросаны, приглушённый лавовый тон.
    band варьирует разброс/яркость по строкам. Пусто если выкл / ASCII / нет цвета."""
    if not _SPARK_ON or not _UTF or not _ON or width < 14:
        return ""
    rows = _rows()
    dim = rows[-1]                                   # приглушённый тон схемы
    mid = rows[len(rows) // 2]
    # позиции-«искры» относительно ширины; band сдвигает узор (не ровный ряд)
    spec = [(0.06, "✦", mid), (0.22, "·", dim), (0.44, "✧", dim),
            (0.63, "✦", dim), (0.80, "·", mid), (0.93, "✧", dim)]
    row = [" "] * width
    for i, (frac, g, sh) in enumerate(spec):
        if (i + band) % 2:                           # прореживаем — «россыпь», не ряд
            continue
        c = int(width * frac) + (band % 3)
        if 0 <= c < width:
            row[c] = "\033[38;5;%dm%s\033[0m" % (sh, g)
    return "".join(row).rstrip()


def _wordmark(hot=None):
    """Лавовый wordmark «SuperPromt» — название закрашено лавой (ЖИРНОЕ); влезает везде.
    hot=None — статичный градиент; hot=x — световой блик для перелива."""
    txt = _WORDMARK
    if not _ON or not _UTF:
        return txt
    if hot is None:
        return _paint_grad(txt, bold_it=True)
    out = []
    rows = _rows()
    for x, ch in enumerate(txt):
        d = abs(x - hot)
        shade = hot_shade() if d == 0 else rows[min(len(rows) - 1, d)]
        out.append("\033[1;38;5;%dm%s" % (shade, ch))
    return "".join(out) + "\033[0m"


def _drip_line(phase, width):
    """Строка капающей лавы под логотипом: капля формируется (. :) и срывается (') — «капает».
    Капли равномерно распределены по ширине логотипа."""
    cyc = [" ", ".", ":", "'", " ", " "]
    row = [" "] * width
    ndrops = max(3, width // 8)
    cols = [int(width * (k + 0.5) / ndrops) for k in range(ndrops)]
    for k, c in enumerate(cols):
        if not 0 <= c < width:
            continue
        ch = cyc[(phase + k * 2) % len(cyc)]
        if ch == " ":
            continue
        rows = _rows()
        shade = hot_shade() if ch == "'" else rows[min(len(rows) - 1, 3)]  # тип капли
        row[c] = ("\033[38;5;%dm%s\033[0m" % (shade, ch)) if _ON else ch
    return "".join(row)


_WAVE = "▁▂▃▄▅▆▇█▇▆▅▄▃▂"          # фирменная волна лавы (UTF)
_WAVE_ASCII = "._.-~-"             # ASCII-подобие волны (деградация)


def molten_bar(width, phase=0):
    """ФИРМЕННАЯ ЛАВОВАЯ ПОЛОСА: волна ▁▂▃▄▅▆▇█▇▆▅▄▃▂, залитая ГОРИЗОНТАЛЬНЫМ градиентом
    (оранжевый слева → красный справа), гребни █ раскалены. phase сдвигает волну — «поток
    течёт». Разделяет слова логотипа и подчёркивает его. Деградация: UTF без цвета — голая
    волна; ASCII — ._.-~- (с градиентом при цвете, голое при ч/б)."""
    if width <= 0:
        return ""
    if not _UTF:
        pat = _WAVE_ASCII
        line = "".join(pat[(x + phase) % len(pat)] for x in range(width))
        return _paint_grad(line) if _ON else line
    glyphs = [_WAVE[(x + phase) % len(_WAVE)] for x in range(width)]
    if not _ON:
        return "".join(glyphs)
    rows = _rows()
    out = []
    for x, g in enumerate(glyphs):
        shade = hot_shade() if g == "█" else rows[min(len(rows) - 1, x * len(rows) // max(1, width))]
        out.append("\033[38;5;%dm%s" % (shade, g))
    return "".join(out) + "\033[0m"


def _logo_lines(segs, w, hot=None, phase=0, freeze=False):
    """Собрать строки логотипа: сегменты-слова (вертикальный жар / бегущий блик) + лавовые
    полосы (разделитель между словами и подчёркивание) + капли. hot=None → статичный жар."""
    total = sum(len(s) for s in segs)
    lines, ri = [], 0
    for si, seg in enumerate(segs):
        for r in seg:
            sh = _shade_at(ri, total)
            lines.append(_paint_row(r, sh) if hot is None else _paint_col(r, hot, sh))
            ri += 1
        if si < len(segs) - 1:                     # лавовая полоса-РАЗДЕЛИТЕЛЬ между словами
            lines.append(molten_bar(w, phase))
    lines.append(molten_bar(w, phase))             # лавовое ПОДЧЁРКИВАНИЕ под логотипом
    lines.append(_drip_line(3 if freeze else phase, w))   # капли
    return lines


def logo(lang="ru"):
    """Статичный логотип (Молтен-слэб): БОЛЬШИЕ блочные буквы + фирменная лавовая полоса
    (разделяет SUPER/PROMT и подчёркивает) + застывшие капли — виден на скриншоте без анимации."""
    from .ansi import term_cols
    segs = _logo_segments(term_cols())
    if segs is None:                               # очень узко (<31) → мелкий wordmark + полоса
        wm = len(_WORDMARK)
        return _wordmark() + "\n" + molten_bar(wm) + "\n" + _drip_line(3, wm)
    return "\n".join(_logo_lines(segs, len(segs[0][0]), hot=None, freeze=True))


def play_logo(stream=None, waves=2):
    """ПРИВЕТСТВЕННАЯ анимация: каждый ряд букв ЗАГОРАЕТСЯ бегущим лавовым бликом (слева-направо),
    затем лавовая полоса ТЕЧЁТ волной и капли КАПАЮТ. Всё анимируется В ПРЕДЕЛАХ ТЕКУЩЕЙ строки
    (только \\r + стирание + \\n) — БЕЗ курсора-вверх, поэтому богато И безопасно на любом терминале
    (мобильный ssh, игнорящий ESC[A, не плодит строки). Не-TTY / SPT_NO_ANIM → статичный logo()."""
    stream = stream or sys.stdout
    if not _anim_ok(stream):
        stream.write(logo() + "\n"); stream.flush(); return
    cols = shutil.get_terminal_size((80, 24)).columns
    segs = _logo_segments(cols)
    if segs is None:                               # узкий wordmark — печатаем сразу (ревить нечего)
        stream.write(logo() + "\n"); stream.flush(); return
    w = len(segs[0][0])
    total = sum(len(s) for s in segs)

    def flow(make, frames, dt, hold):
        """Проиграть ОДНУ строку на месте (кадры make(0..frames-1), только \\r), затем зафиксировать
        make(hold) и перейти ВНИЗ (\\n). Никакого вертикального движения курсора."""
        for f in range(frames):
            stream.write("\r\033[K" + make(f)); stream.flush(); time.sleep(dt)
        stream.write("\r\033[K" + make(hold) + "\n"); stream.flush()

    ri = 0
    step = max(3, w // 10)
    for si, seg in enumerate(segs):
        for r in seg:                              # ряд букв: бегущий блик слева-направо → застыл
            sh = _shade_at(ri, total)
            for hot in range(-2, w + 3, step):
                stream.write("\r\033[K" + _paint_col(r, hot, sh)); stream.flush()
                time.sleep(0.005)
            stream.write("\r\033[K" + _paint_row(r, sh) + "\n"); stream.flush()
            ri += 1
        if si < len(segs) - 1:                     # полоса-разделитель: волна течёт
            flow(lambda f: molten_bar(w, f), 10, 0.028, 0)
    flow(lambda f: molten_bar(w, f), 18, 0.03, 0)  # подчёркивание: лава ТЕЧЁТ волной
    flow(lambda f: _drip_line(f, w), 8, 0.045, 3)  # капли КАПАЮТ и застывают


def play_verdict(stream, verdict, alive, total):
    """Разгорание полоски доверия + вспышка PASS (зелёная) / горящее ВЕТО (красная).
    Возвращает финальную строку полоски (для статичного вывода на не-TTY)."""
    from .ansi import G, brand, green, red, trust_bar, yellow
    final = trust_bar(alive, total)
    mark = brand() or G["ok"]
    if not _anim_ok(stream):
        return final
    # 1) разгорание слева-направо: ведущая ячейка 226, за ней финальный цвет
    if total > 0:
        w = 10
        filled = round(w * alive / total)
        base_col = (green if alive == total else (yellow if alive > 0 else red))
        for k in range(filled + 1):
            lead = _lava(G["bar_on"], hot_shade()) if k < filled else ""
            bar = base_col(G["bar_on"] * max(0, k - 1)) + lead + \
                grey(G["bar_off"] * (w - k))
            stream.write("\r " + bar)
            stream.flush()
            time.sleep(0.05)
        stream.write("\r\033[K")
    # 2) вспышка по вердикту
    if verdict == "PASS":
        for sh in (46, 82, 40):  # зелёный расцвет
            stream.write("\r %s %s" % (_lava(G["ok"], sh), _lava(mark, hot_shade())))
            stream.flush()
            time.sleep(0.09)
    elif verdict == "VETO":
        for sh in (196, 210, 160):  # красная пульсация
            stream.write("\r %s ВЕТО" % _lava(G["fail"], sh))
            stream.flush()
            time.sleep(0.1)
    stream.write("\r\033[K")
    stream.flush()
    return final


class Spinner:
    """Спиннер ожидания в фоне: «⠋ думаю… ⣀ (12s)». Меняет слово по set_status().
    На не-TTY — не рисует ничего (тихо). Контекст-менеджер."""

    def __init__(self, key="think", lang="ru", stream=None):
        self.stream = stream or sys.stderr
        self.lang = lang
        self.key = key
        self._stop = threading.Event()
        self._paused = False
        self._lock = threading.Lock()
        self._t = None
        self._t0 = 0.0
        self.active = (_ON and hasattr(self.stream, "isatty")
                       and self.stream.isatty()
                       and not os.environ.get("SPT_NO_ANIM"))  # #7: уважать флаг

    def set_status(self, key):
        self.key = key

    def pause(self):
        """Приостановить отрисовку (на время диалога подтверждения — #2). Чистит строку."""
        self._paused = True
        if self.active:
            with self._lock:
                self.stream.write("\r\033[K")
                self.stream.flush()

    def resume(self):
        self._paused = False

    def log(self, line):
        """Напечатать постоянную строку НАД спиннером (дерево ⏺/⎿ скроллится вверх,
        спиннер остаётся внизу — как в Claude Code)."""
        if not self.active:
            # #11: при неактивном спиннере дерево — в тот же поток (обычно stderr),
            # чтобы не смешивать диагностику с ответом при редиректе stdout в файл
            print(line, file=self.stream)
            return
        with self._lock:
            self.stream.write("\r\033[K")   # стереть строку спиннера
            self.stream.flush()
            print(line)                      # постоянная строка (stdout)
            sys.stdout.flush()

    def _run(self):
        spin = itertools.cycle(_spin_frames())
        while not self._stop.is_set():
            if self._paused:              # #2: молчим во время диалога подтверждения
                time.sleep(0.05)
                continue
            with self._lock:
                el = int(time.monotonic() - self._t0)
                frame = next(spin)
                shade = _heat(el)  # индикатор накаляется со временем
                word = status_word(self.key, self.lang)   # слово-статус на ЯЗЫКЕ интерфейса
                line = "\r %s %s%s %s" % (
                    _render_spin(frame, shade), word,
                    "…" if _UTF else "...", grey("(%ds · Ctrl-C)" % el))
                self.stream.write(line + "\033[K")
                self.stream.flush()
            time.sleep(0.16)
        with self._lock:
            self.stream.write("\r\033[K")  # очистить строку
            self.stream.flush()

    def __enter__(self):
        if self.active:
            self._t0 = time.monotonic()
            self._t = threading.Thread(target=self._run, daemon=True)
            self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        if self._t:
            self._t.join(timeout=0.3)
        return False
