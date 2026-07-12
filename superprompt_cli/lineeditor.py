"""Raw-mode редактор строки для spt:
  • живой ЗАМКНУТЫЙ бокс ввода (правая грань держится при печати);
  • ghost-плейсхолдер, исчезающий при вводе;
  • ЖИВЫЕ выпадашки при вводе / (команды) и @ (файлы) — навигация ↑↓, выбор Tab/Enter;
  • история ↑↓ (когда нет выпадашки), курсор ←→, Backspace, Ctrl-C/Ctrl-D.
Кроссплатформенно и БЕЗОПАСНО: без TTY / без termios / Windows / любая ошибка → фолбэк на
readline input(). termios всегда восстанавливается в finally (терминал не залипает)."""
import os
import select
import sys

from . import ansi
from .ansi import G, blue, bold, grey

try:
    import termios
    import tty
    _RAW_OK = True
except ImportError:                       # Windows / нет termios
    _RAW_OK = False


_DISABLED = False


def disable():
    """Выключить raw-mode на сессию (после сбоя) — дальше только readline-фолбэк."""
    global _DISABLED
    _DISABLED = True


def available():
    """Можно ли raw-mode: TTY + termios + не запрещено флагом/сбоем."""
    return (_RAW_OK and not _DISABLED and ansi._ON and sys.stdin.isatty()
            and sys.stdout.isatty() and not os.environ.get("SPT_NO_RAW"))


def _read_paste(fd):
    """Дочитать вставленный текст до маркера конца ⟨ESC⟩[201~ (bracketed paste). -> str."""
    end = b"\033[201~"
    data = b""
    while not data.endswith(end):
        chunk = os.read(fd, 4096)
        if not chunk:
            break
        data += chunk
    if data.endswith(end):
        data = data[:-len(end)]
    return data.decode("utf-8", "replace")


def _read_more(fd, n, timeout=0.06):
    """Дочитать ДО n байт с коротким ожиданием — собирает РАСЩЕПЛЁННЫЕ на лагающем ssh escape-/
    UTF-последовательности (иначе стрелка вставляла бы мусорный символ, а CJK-символ терялся)."""
    buf = b""
    while len(buf) < n:
        r, _, _ = select.select([fd], [], [], timeout)
        if not r:
            break
        chunk = os.read(fd, n - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


def _csi_key(params, fd):
    """CSI-последовательность ⟨ESC⟩[<params> → событие клавиши."""
    return {b"A": ("up", None), b"B": ("down", None), b"C": ("right", None),
            b"D": ("left", None), b"H": ("home", None), b"F": ("end", None),
            }.get(params) or (("paste", _read_paste(fd)) if params == b"200~"
                              else ("other", None))


def _read_key(fd):
    """Прочитать одну клавишу. -> ('char', c) | ('paste', text) | ('enter'|'bs'|'tab'|'up'|
    'down'|'left'|'right'|'ctrl-c'|'ctrl-d'|'esc'|'home'|'end'|'other', None).
    Escape-/UTF-последовательности собираются с таймаутом — устойчиво к расщеплению на мобильном ssh."""
    ch = os.read(fd, 1)
    if not ch:
        return ("ctrl-d", None)
    b = ch[0]
    if b in (13, 10):
        return ("enter", None)
    if b in (127, 8):
        return ("bs", None)
    if b == 9:
        return ("tab", None)
    if b == 3:
        return ("ctrl-c", None)
    if b == 4:
        return ("ctrl-d", None)
    if b == 27:                            # ESC — стрелка/навигация/bracketed-paste
        nxt = _read_more(fd, 1)
        if nxt == b"[":                    # CSI: добираем параметры до финального байта (0x40-0x7e)
            params = b""
            while True:
                nb = _read_more(fd, 1)
                if not nb:
                    break
                params += nb
                if 0x40 <= nb[0] <= 0x7e:
                    break
            return _csi_key(params, fd)
        if nxt == b"O":                    # SS3 (Home/End на части терминалов)
            nb = _read_more(fd, 1)
            return {b"H": ("home", None), b"F": ("end", None)}.get(nb, ("other", None))
        return ("esc", None)               # «голый» ESC
    if b < 32:
        return ("other", None)
    n = 3 if b >= 0xF0 else 2 if b >= 0xE0 else 1 if b >= 0xC0 else 0
    rest = _read_more(fd, n) if n else b""   # добрать продолжение UTF-8 (с таймаутом)
    try:
        return ("char", (ch + rest).decode("utf-8"))
    except UnicodeDecodeError:
        return ("other", None)


# команды для выпадашки / (команда → короткое описание)
_COMMANDS = [
    ("/help", "палитра команд"), ("/retry", "повторить · /повтор"),
    ("/why", "разбор вердикта · /почему"), ("/links md", "библиография · /ссылки"),
    ("/tier", "бюджет-тир min|mid|max"), ("/gates", "гейты on|off|strict"),
    ("/model", "модель · /модель"), ("/max", "N кандидатов+судья+гейт выхода"),
    ("/goal", "цель-DoD"), ("/perm", "режим ask|auto|yolo"),
    ("/theme", "цветовая схема · /цвет"), ("/spinner", "анимация индикатора"),
    ("/brand", "бренд-глиф"), ("/sparkles", "✦ искры on|off"),
    ("/lang", "язык · /язык"), ("/settings", "все настройки · /настройки"),
    ("/continue", "последняя сессия"), ("/resume", "выбрать сессию"),
    ("/compact", "сжать историю · /сжать"), ("/keys", "ключи · /ключи"),
    ("/exit", "выход · exit, q"),
]


def _matches(text):
    """Выпадашка по первому токену: -> (список [(значение, описание)], префикс) | (None, '')."""
    if " " in text or not text:
        return None, ""
    if text[0] == "/":
        hits = [(c, d) for c, d in _COMMANDS if c.startswith(text.lower())]
        return (hits or None), text
    if text[0] == "@":
        frag = text[1:]
        d = os.path.dirname(frag) or "."
        base = os.path.basename(frag)
        try:
            names = sorted(os.listdir(os.path.expanduser(d)))
        except OSError:
            return None, text
        hits = []
        for nm in names:
            if nm.startswith(".") and not base.startswith("."):
                continue
            if nm.lower().startswith(base.lower()):
                full = os.path.join(d, nm) if d != "." else nm
                is_dir = os.path.isdir(os.path.expanduser(full))
                hits.append(("@" + full + ("/" if is_dir else ""),
                             "каталог" if is_dir else "файл"))
        return (hits[:8] or None), text
    return None, ""


def _should_collapse(text, area):
    """Свернуть вставку в пилюлю [вставлено N…]? Да, если она МНОГОСТРОЧНАЯ или НЕ ВЛЕЗАЕТ в
    видимую ширину ввода `area`. Значит: на широком десктопе длинная ОДНОстрочная вставка
    показывается ЦЕЛИКОМ; на телефоне (узкий бокс) / при переносах — сворачивается."""
    return ("\n" in text) or (ansi._dw(text.replace("\r", "")) > max(8, area))


class _Editor:
    def __init__(self, w, gcol, placeholder, history):
        self.w = w                        # горизонтальный прогон рамки
        self.gcol = gcol                  # функция цвета режима (верх/❯)
        self.ph = placeholder
        self.history = list(history or [])
        self.buf = ""
        self.cur = len(self.buf)
        self.hidx = len(self.history)     # позиция в истории
        self.sel = 0                      # выбранный пункт выпадашки
        self.prev_lines = 0               # сколько строк занял прошлый кадр
        self._cur_off = 0                 # где припаркован курсор (offset от верха блока)
        self.pastes = {}                  # плейсхолдер-пилюля → реальный вставленный текст
        self._pcount = 0

    # ---- вставка (paste-collapse: длинный/многострочный текст сворачивается в пилюлю) ----
    def add_paste(self, text):
        """Сохранить вставку и вернуть КОРОТКИЙ плейсхолдер [вставлено N симв.] для показа.
        На сабмите плейсхолдер разворачивается обратно в полный текст (value())."""
        self._pcount += 1
        n, lines = len(text), text.count("\n") + 1
        label = ("[вставлено %d симв., %d стр.]" % (n, lines) if lines > 1
                 else "[вставлено %d симв.]" % n)
        key = label
        while key in self.pastes:                       # уникальность при повторах
            key = label[:-1] + " #%d]" % self._pcount
        self.pastes[key] = text
        return key

    def value(self):
        """Итоговый текст: плейсхолдеры-пилюли → реальные вставки."""
        b = self.buf
        for k, v in self.pastes.items():
            b = b.replace(k, v)
        return b

    # ---- рендер (БЕЗ вертикального движения курсора — работает на терминалах без ESC[A) ----
    def _text_area(self):
        # строка ввода = │(1)+ (1)+❯(1)+ (1) + area + (1)+│(1) = area+6; рамки = w+2.
        # значит area = w-4, иначе строка на 1 кол шире рамок → правая грань переносится.
        return max(4, self.w - 4)         # ширина под текст в строке ввода

    def top_border(self):
        """Верхняя грань (рисуется ОДИН раз). Плейсхолдер-подсказка встроена в грань."""
        ph = " " + (self.ph or "напишите задачу") + " "
        fill = self.w - 1 - ansi._dw(ph)
        if fill >= 2:
            return (self.gcol(G["box_tl"] + G["box_h"]) + grey(ph)
                    + self.gcol(G["box_h"] * fill + G["box_tr"]))
        return self.gcol(G["box_tl"] + G["box_h"] * self.w + G["box_tr"])

    def bottom_border(self):
        return self.gcol(G["box_bl"] + G["box_h"] * self.w + G["box_br"])

    def _ghost(self):
        """Инлайн-подсказка автодополнения: серый «хвост» верхнего совпадения / или @,
        показывается ТОЛЬКО когда курсор в конце и текст влезает без горизонт. скролла."""
        if not self.buf or self.cur != len(self.buf) or ansi._dw(self.buf) >= self._text_area():
            return ""
        hits, _ = _matches(self.buf)
        if not hits:
            return ""
        top = hits[0][0]
        return top[len(self.buf):] if (top.lower().startswith(self.buf.lower())
                                       and len(top) > len(self.buf)) else ""

    @staticmethod
    def _take_cols(s, maxcols):
        """Префикс строки, влезающий в maxcols ДИСПЛЕЙ-колонок (CJK/эмодзи = 2). -> (текст, ширина)."""
        out, w = [], 0
        for ch in s:
            cw = ansi._dw(ch)
            if w + cw > maxcols:
                break
            out.append(ch); w += cw
        return "".join(out), w

    def _scroll_start(self, area):
        """Индекс начала окна (в СИМВОЛАХ) так, чтобы курсор был виден — считаем в колонках."""
        start = 0
        while start < self.cur and ansi._dw(self.buf[start:self.cur]) > area:
            start += 1
        return start

    def _line_and_col(self, ghost=True):
        """Строка ввода '│ ❯ текст… │' + колонка курсора. Горизонт. скролл в ДИСПЛЕЙ-колонках
        (курсор всегда видим, рамка не рвётся на CJK/эмодзи)."""
        area = self._text_area()
        start = self._scroll_start(area)
        vis, viscols = self._take_cols(self.buf[start:], area)
        g = ""
        if ghost and start == 0:
            g, _ = self._take_cols(self._ghost(), area - viscols)
        pad = area - viscols - ansi._dw(g)
        left = blue(G["box_v"]) + " " + self.gcol(G["prompt"]) + " "
        line = (left + vis + (grey(g) if g else "") + " " * max(0, pad)
                + " " + blue(G["box_v"]))
        col = ansi._dw(left) + ansi._dw(self.buf[start:self.cur])   # позиция курсора от края
        return line, col

    def frame(self, ghost=True):
        """Кадр перерисовки строки ввода НА МЕСТЕ: \\r (в начало) · ESC[K (стереть) · строка ·
        \\r · ESC[nC (курсор на позицию ввода). ТОЛЬКО горизонтальные ESC — без ESC[A/B."""
        line, col = self._line_and_col(ghost)
        s = "\r\033[K" + line + "\r"
        if col:
            s += "\033[%dC" % col
        return s


def _accept_ghost(ed):
    """Tab/→ в конце: принять верхнее совпадение (команду — с пробелом, каталог — без)."""
    if not ed._ghost():
        return
    top = _matches(ed.buf)[0][0][0]               # (hits, pref)[0]=hits · [0]=1-е · [0]=значение
    ed.buf = top + (" " if top.startswith("/") and not top.endswith("/") else "")
    ed.cur = len(ed.buf)


def read_line(w, gcol, placeholder="", history=None, out=None):
    """Прочитать строку в raw-mode БЕЗ вертикального движения курсора (совместимо с мобильными
    ssh-терминалами, где ESC[A игнорируется). Верхняя грань — один раз; строка ввода — на месте;
    нижняя грань — при сабмите. Автодополнение / и @ — инлайн серой подсказкой (Tab/→ принять).
    -> текст (может быть ''), None при Ctrl-D на пустой. Ctrl-C → KeyboardInterrupt."""
    out = out or sys.stdout
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    ed = _Editor(w, gcol, placeholder, history)
    try:
        tty.setraw(fd)
        out.write("\033[?2004h")                 # bracketed paste ON — вставку целым куском
        out.write("\r" + ed.top_border() + "\r\n")   # верхняя грань — ОДИН раз, курсор → строка ввода
        out.write(ed.frame())                    # первая отрисовка строки ввода
        out.flush()
        while True:
            kind, val = _read_key(fd)
            if kind == "char":
                ed.buf = ed.buf[:ed.cur] + val + ed.buf[ed.cur:]
                ed.cur += len(val)
            elif kind == "paste":
                if _should_collapse(val, ed._text_area()):   # телефон/многострочно → пилюля
                    pill = ed.add_paste(val)
                    ed.buf = ed.buf[:ed.cur] + pill + ed.buf[ed.cur:]
                    ed.cur += len(pill)
                else:                                         # влезает (десктоп) → целиком
                    clean = val.replace("\r", "")
                    ed.buf = ed.buf[:ed.cur] + clean + ed.buf[ed.cur:]
                    ed.cur += len(clean)
            elif kind == "bs":
                pill = next((k for k in ed.pastes             # Backspace у пилюли — удалить целиком
                             if ed.cur >= len(k) and ed.buf[ed.cur - len(k):ed.cur] == k), None)
                if pill:
                    ed.buf = ed.buf[:ed.cur - len(pill)] + ed.buf[ed.cur:]
                    ed.cur -= len(pill)
                    del ed.pastes[pill]
                elif ed.cur > 0:
                    ed.buf = ed.buf[:ed.cur - 1] + ed.buf[ed.cur:]
                    ed.cur -= 1
            elif kind == "left":
                ed.cur = max(0, ed.cur - 1)
            elif kind == "right":
                if ed.cur < len(ed.buf):
                    ed.cur += 1
                else:
                    _accept_ghost(ed)                 # → в конце принимает подсказку
            elif kind == "home":
                ed.cur = 0
            elif kind == "end":
                ed.cur = len(ed.buf)
            elif kind == "up":
                if ed.history:
                    ed.hidx = max(0, ed.hidx - 1)
                    ed.buf = ed.history[ed.hidx] if ed.hidx < len(ed.history) else ""
                    ed.cur = len(ed.buf)
            elif kind == "down":
                if ed.history:
                    ed.hidx = min(len(ed.history), ed.hidx + 1)
                    ed.buf = ed.history[ed.hidx] if ed.hidx < len(ed.history) else ""
                    ed.cur = len(ed.buf)
            elif kind == "tab":
                _accept_ghost(ed)                     # принять инлайн-подсказку / или @
            elif kind == "enter":
                break
            elif kind == "ctrl-c":
                raise KeyboardInterrupt
            elif kind == "ctrl-d":
                if not ed.buf:
                    ed.buf = None
                    break
            out.write(ed.frame())
            out.flush()
        # финал: строка без подсказки + нижняя грань (курсор уходит НИЖЕ бокса — только \n)
        out.write("\r\033[K" + ed._line_and_col(ghost=False)[0] + "\r\n")
        out.write("\r" + ed.bottom_border() + "\r\n")
        out.flush()
        return None if ed.buf is None else ed.value()   # пилюли → полный текст вставок
    except KeyboardInterrupt:
        out.write("\r\n")                         # уйти на чистую строку (вызывающий рисует низ)
        out.flush()
        raise
    finally:
        try:
            out.write("\033[?2004l")      # bracketed paste OFF (терминал не залипает)
            out.flush()
        except Exception:                 # noqa: BLE001
            pass
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
