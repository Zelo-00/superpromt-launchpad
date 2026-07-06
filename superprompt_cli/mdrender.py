"""Рендер markdown-ответа модели в ANSI.

Сценарий B (выбор пользователя): если установлен **rich** — используется он (полный CommonMark
+ подсветка кода pygments); если rich НЕТ — тихая деградация на СВОЙ лёгкий stdlib-рендерер
(ноль зависимостей). Ширина/цвет(_ON)/ASCII(_UTF) — как весь UI spt. Применяется ТОЛЬКО к телу
ответа (не к паспорту/карточкам и не в -q, где контракт — сырой текст)."""
import io
import re

from . import ansi
from .ansi import G, blue, bold, cyan, grey


def render(text, width=None):
    """markdown → строка с ANSI под ширину терминала. Пусто/ч-б → минимально-чисто."""
    if not text:
        return text or ""
    width = max(20, width or ansi.term_cols())
    if not ansi._ON:                         # ч/б: без цвета украшать нечем — снять разметку
        return _basic(text, width, color=False)
    if ansi._UTF:                            # цвет+UTF: пробуем rich (если установлен)
        r = _rich(text, width)
        if r is not None:
            return r
    return _basic(text, width, color=True)   # свой stdlib-рендерер (fallback)


def _rich(text, width):
    """rich.Markdown → строка. None, если rich не установлен или упал (→ fallback на stdlib)."""
    try:
        from rich.console import Console
        from rich.markdown import Markdown
    except ImportError:
        return None
    try:
        sio = io.StringIO()
        console = Console(file=sio, force_terminal=True, width=width,
                          color_system="256", highlight=False)
        console.print(Markdown(text, code_theme="monokai", inline_code_lexer="text"))
        return sio.getvalue().rstrip("\n")
    except Exception:                        # noqa: BLE001 — любой сбой rich → stdlib-fallback
        return None


# ---------- свой лёгкий stdlib-рендерер (ноль зависимостей) ----------
_H = re.compile(r"^(#{1,6})\s+(.*)$")
_FENCE = re.compile(r"^\s*```(\w*)\s*$")
_FENCE_END = re.compile(r"^\s*```\s*$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUM = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_HR = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")


def _inline(s, color):
    """Инлайн-разметка: `код`, **жирный**, *курсив*. Без цвета — просто снять маркеры."""
    if not color:
        s = re.sub(r"`([^`]+)`", r"\1", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
        s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", s)
        return s
    s = re.sub(r"`([^`]+)`", lambda m: cyan(m.group(1)), s)
    s = re.sub(r"\*\*([^*]+)\*\*", lambda m: bold(m.group(1)), s)
    s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)",
               lambda m: "\033[3m%s\033[0m" % m.group(1), s)
    return s


def _code(code, lang, color):
    """Блок кода: левый рельс │ у каждой строки (без обрезки — терминал переносит длинное)."""
    bar = grey(G["box_v"]) if color else "|"
    out = []
    if lang:
        out.append(grey("  " + lang))
    for c in code:
        out.append("%s %s" % (bar, (cyan(c) if color else c)))
    return out


def _basic(text, width, color=True):
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        ln = lines[i]
        mf = _FENCE.match(ln)
        if mf:                                # ```lang … ```
            lang, code = mf.group(1), []
            i += 1
            while i < len(lines) and not _FENCE_END.match(lines[i]):
                code.append(lines[i]); i += 1
            i += 1                            # пропустить закрывающий ```
            out += _code(code, lang, color)
            continue
        if _HR.match(ln):                     # --- горизонтальная черта
            out.append(grey(G["box_h"] * min(width, 40)) if color else "-" * min(width, 40))
            i += 1; continue
        mh = _H.match(ln)
        if mh:                                # # заголовок
            lvl, txt = len(mh.group(1)), _inline(mh.group(2), color)
            mark = (blue(G["pick"]) + " ") if color else ""
            out.append((mark + bold(txt)) if color else txt.upper())
            i += 1; continue
        mb = _BULLET.match(ln)
        if mb:                                # - список
            dot = blue(G["dot"]) if color else "-"
            out.append("%s%s %s" % (mb.group(1), dot, _inline(mb.group(2), color)))
            i += 1; continue
        mn = _NUM.match(ln)
        if mn:                                # 1. нумерованный список
            num = bold(mn.group(2) + ".") if color else mn.group(2) + "."
            out.append("%s%s %s" % (mn.group(1), num, _inline(mn.group(3), color)))
            i += 1; continue
        mq = _QUOTE.match(ln)
        if mq:                                # > цитата
            barq = grey(G["box_v"]) if color else "|"
            out.append("%s %s" % (barq, grey(_inline(mq.group(1), color)) if color
                                  else _inline(mq.group(1), color)))
            i += 1; continue
        out.append(_inline(ln, color))        # обычный абзац
        i += 1
    return "\n".join(out)
