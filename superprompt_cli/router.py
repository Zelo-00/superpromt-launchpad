"""Capability-Router: домен задачи + подбор скиллов.
Скиллы: встроенные (ponytail для кода) + библиотека PromtMaster (если есть на машине,
ранкинг по релевантности через router_rank.py; improved/ приоритетнее unified/)."""
import os
import re
import sys

PM_DIR = os.environ.get("SPT_PROMTMASTER",
                        os.path.expanduser(os.path.join("~", "metodika", "PromtMaster")))

DOMAINS = {
    "code": r"код|функци|скрипт|баг|тест|рефактор|api|python|javascript|sql|деплой|"
            r"code|debug|refactor|implement|compile|сайт|сайта|лендинг|лендинга|страниц|"
            r"вебсайт|web|website|html|css|компонент|frontend|backend|приложен|сервер|"
            r"дашборд|панел|интерфейс|REST|GraphQL|эндпоинт|портфолио|галерея|"
            r"магазин|блог|чат|форма|навигация|модалка|слайдер",
    "design": r"дизайн|ux|ui|макет|прототип|типографик|цвет|интерфейс|design|figma|"
              r"визуал|красив|стиль|макет|layout|тема|палитра|шрифт",
    "research": r"исследуй|источник|стать[ьяи]|литератур|обзор|найди информац|research|"
                r"paper|survey|факт|ссылк",
    "data": r"данн|csv|таблиц|датасет|график|статистик|анализ данных|pandas|data",
    "writing": r"напиши (текст|статью|пост|письмо|эссе)|документаци|writing|перевод",
}

# АНТИ-паттерны (harness-eng: negatives дали routing 73%→85%): слова, которые НЕ должны тянуть
# домен при явном сигнале другого (напр. «факт/источник» в КОД-задаче ≠ research).
NEG = {
    "research": r"код|функци|assert|python|скрипт|рефактор|деплой|компил",
    "writing": r"код|функци|тест|api|sql|python|датасет|дизайн",
    "data": r"дизайн|ux|макет|прототип|эссе|письмо",
    "design": r"\bsql\b|датасет|pandas|assert",
}

PONYTAIL_RULES = """Дисциплина минимального кода lean-code (адаптация Ponytail, full): лестница —
(1) YAGNI: нужно ли это вообще; (2) уже есть в кодбазе — grep по доменным словам задачи,
глянуть utils/shared, тайм-бокс 2-3 мин; (3) stdlib; (4) нативная возможность платформы;
(5) уже установленная зависимость; (6) одна строка; (7) только затем — минимальный код.
Багфикс = root cause (grep всех вызовов), не симптом. Без незапрошенных абстракций.
Нетривиальная логика оставляет ОДИН запускаемый чек (assert/test) — и он ПРОГОНЯЕТСЯ
(KSCR-гейт исполнит). Осознанный шорткат помечай:
# ponytail: <что упрощено> | ceiling: <предел> | upgrade: <когда апгрейдить>
НЕ упрощать: валидацию границ доверия, обработку ошибок, безопасность, доступность;
TDD/coverage-требования конвейера = explicitly requested. В автономном прогоне не
дескоупить зафиксированное в идеальном промте — оспаривать можно только вопросом человеку."""


def _scores(task):
    """Балл домена = позитив, ДАМПИРОВАННЫЙ анти-паттернами (не линейное вычитание в ноль).
    Находка анализа: `max(0, pos-neg)` обнулял ПРАВИЛЬНЫЙ домен от одного побочного слова чужого
    домена (research-задача с мимолётным «код» → 0). Пропорц. дампинг pos/(1+0.6·neg) сохраняет
    сильный домен живым, но штрафует при явном сигнале другого — исходный интент NEG сохранён."""
    sc = {}
    for d, pat in DOMAINS.items():
        pos = len(re.findall(pat, task, re.I))
        neg = len(re.findall(NEG[d], task, re.I)) if d in NEG else 0
        sc[d] = pos / (1.0 + 0.6 * neg)
    return sc


def classify_conf(task):
    """-> (домен, уверенность 0..1, scores). Слабый/неоднозначный сигнал → 'mixed'
    (низкая уверенность → расширенный тул-набор). knowledge-work — дефолт при нуле."""
    sc = _scores(task)
    ordered = sorted(sc.values(), reverse=True)
    top = ordered[0]
    if top == 0:
        return "knowledge-work", 0.0, sc
    second = ordered[1] if len(ordered) > 1 else 0
    margin = (top - second) / (top + 1)                 # отрыв лидера (0..1)
    tied = [d for d, s in sc.items() if s == top]
    if len(tied) > 1 or margin < 0.34:                  # неоднозначно → mixed
        return "mixed", round(margin, 2), sc
    return max(sc, key=sc.get), round(0.5 + 0.5 * margin, 2), sc


def classify(task):
    """Домен задачи (строка) — обратно-совместимо. Уверенность — через classify_conf."""
    return classify_conf(task)[0]


def trim_skill(text, cap=1500):
    """Умная обрезка скилла: без frontmatter, по границе абзаца (system-промт
    пересылается КАЖДЫЙ шаг цикла — каждый лишний знак умножается на шаги)."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4:]
    text = text.strip()
    if len(text) <= cap:
        return text
    cut = text.rfind("\n\n", 0, cap)
    return text[:cut if cut > cap // 2 else cap].rstrip() + "\n[…обрезано spt]"


def pick_skills(task, domain, k=3, cfg=None):
    """-> [(имя, текст-фрагмент <=1500)] по релевантности задаче. Источник — курированный
    web/backend скилл-пак skills/*/SKILL.md (офлайн TF-IDF) + встроенное правило lean-code.
    Те же скиллы публикуются на маркетплейс Kodik (формат SKILL.md совместим)."""
    out = []
    if domain in ("code", "mixed"):
        out.append(("lean-code(builtin)", PONYTAIL_RULES))
    try:
        from . import webskills
        for it in webskills.rank(task, k):
            out.append((it["name"], trim_skill(it["text"])))
    except Exception:  # noqa: BLE001 — пак опционален, не роняем конвейер
        pass
    return out[:k + 1]