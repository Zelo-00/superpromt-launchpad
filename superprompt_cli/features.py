"""Расширенные возможности spt (P1+P2 бэклога): Max Mode и Goal-механизм.
Оба проходят ТОТ ЖЕ KSCR-гейт — уникальная связка spt (у MiMo Max Mode есть, но без
анти-фабрикационного гейта поверх)."""

from . import agentloop, providers
from .ansi import G, blue, bold, cyan, green, grey, red, yellow

GOAL_JUDGE = """Задача имела ЦЕЛЬ (Definition of Done): %s

Ответ:
%s

Выполнена ли ЦЕЛЬ полностью? Ответь строго JSON: {"met": true|false, "why": "1 фраза",
"missing": "что не хватает, если не met"}."""


def check_goal(goal, answer, model, cfg):
    """Goal-механизм ⭐: судья проверяет выполнение NL-условия (DoD). -> (met, why, missing)."""
    r = providers.chat(model, [{"role": "user",
                                "content": GOAL_JUDGE % (goal, answer[:4000])}],
                       max_tokens=300, temperature=0.0, cfg=cfg, json_mode=True)
    d = providers.parse_json(r["text"])   # структурный JSON + устойчивый фолбэк (П.10)
    if not isinstance(d, dict):  # T4: судья не дал оценку → НЕ достигнута (fail-closed:
        return False, "[оценка судьи не получена — цель не подтверждена]", ""  # не выдаём непровер. за провер.)
    # #9: why/missing могут прийти null/числом — приводим к строке
    return bool(d.get("met")), str(d.get("why") or ""), str(d.get("missing") or "")


def run_with_goal(task, goal, cfg, args, run_one, max_rounds=3, log=print):
    """Исполнять задачу, пока Goal-судья не подтвердит выполнение цели (или лимит).
    run_one(task) -> res dict. Возвращает финальный res."""
    model = args.model or cfg["default_model"]
    cur_task = task + "\n\nЦЕЛЬ (обязательно достичь): " + goal
    res = None
    for rnd in range(1, max_rounds + 1):
        res = run_one(cur_task)
        if res is None:
            return None
        met, why, missing = check_goal(goal, res["answer"], model, cfg)
        log(_goal_line(met, why, rnd, max_rounds))
        if met or rnd == max_rounds:
            break
        cur_task = (task + "\n\nЦЕЛЬ: " + goal + "\nПрошлый ответ не достиг цели: "
                    + missing + "\nДоработай, чтобы цель была выполнена полностью.")
    return res


def _goal_line(met, why, rnd, total):
    glyph = green(G["ok"]) if met else yellow(G["repair"])
    word = green("цель достигнута") if met else yellow("цель не достигнута %d/%d" % (rnd, total))
    return " %s %s %s %s" % (glyph, "Goal", word, grey("· " + why[:60]))


def max_mode(task, cfg, args, run_task_fn, n=3, log=print):
    """Max Mode ⭐: N кандидатов (разные температуры) → судья выбирает → KSCR-гейт.
    Уникально: судья + анти-фабрикационный гейт поверх (у MiMo гейта нет).
    run_task_fn — замыкание, принимающее (task, temperature) и возвращающее res."""
    log(_node("Max Mode · %d кандидата" % n, cyan(G["tool"])))
    temps = [0.2, 0.6, 1.0][:n]
    cands = []
    for i, tmp in enumerate(temps, 1):
        res = run_task_fn(task, tmp)
        if res is None:
            continue
        cands.append(res)
        v = res.get("verdict", "?")
        lr = res.get("link_report") or {}
        # ранг: PASS выше, меньше фабрикаций лучше, больше живых ссылок лучше
        rank = ({"PASS": 0, "PASS_WITH_WARNINGS": 1, "NO_CLAIMS": 2,
                 "SKIPPED": 3, "VETO": 4}.get(v, 5),
                lr.get("n_fabricated", 0),
                -(lr.get("n_links", 0) - lr.get("n_fabricated", 0)))
        res["_rank"] = rank
        log(_leaf("кандидат %d (t=%.1f): %s · фабрикаций %d" %
                  (i, tmp, v, lr.get("n_fabricated", 0))))
    if not cands:  # T8: не молчим — иначе выглядит как зависание
        log(_leaf(red("Max Mode: не удалось получить ни одного кандидата "
                      "(ошибки провайдера) — повторите /max позже")))
        return None
    best = min(cands, key=lambda r: r["_rank"])  # лучший по детерминированному рангу
    log(_node("Max Mode · выбран лучший", green(G["ok"] + " " + best.get("verdict", ""))))
    return best


def _node(title, status=""):
    return " %s %s%s" % (blue(G["bullet"]), title, ("  " + status) if status else "")


def _leaf(text):
    return "   %s %s" % (grey(G["branch"]), text)
