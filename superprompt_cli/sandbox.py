"""Чёрный ящик spt: инструменты работают, но не видят «мозги» продукта.

Модель угроз (что закрываем этим модулем):
  T2 — LLM внутри терминала через bash/read/write/edit пытается прочитать и слить
       пользователю интеллектуальную собственность: код метрик (PSQ и гейта выхода), протокол
       SuperPromt, промты судьи/ремонта, библиотеку скиллов, определения агентов,
       а также секреты (~/.spt/.env, ключи).
Что НЕ закрывает (честно, см. BLACKBOX.md): владелец машины, читающий файлы в обход
  терминала (T1), и копирование каталога (T3) — против них нужны байткод-поставка
  (барьер) или серверный режим (настоящий blackbox). Барьер ≠ гарантия.

Разрешено инструментам: рабочая папка задачи (workdir) и /tmp. Всё остальное — deny,
приоритет у deny над allow.
"""
import os
import re
import shutil

# каталоги с «мозгами» и секретами — доступ инструментам запрещён
_PKG = os.path.dirname(os.path.abspath(__file__))          # superprompt_cli/
_PRODUCT = os.path.dirname(_PKG)                             # product/


def bwrap_available():
    """OS-изоляция (bubblewrap) — НАСТОЯЩАЯ граница для bash (не регэксп-барьер).
    Внутри неё защищённых путей просто нет в namespace: cp/symlink/glob/perl/python
    бессильны. Регэксп check_bash — лишь fallback, когда bwrap недоступен."""
    return shutil.which("bwrap") is not None and os.name == "posix"


def _bwrap_base(wd):
    """Общий каркас bwrap: видны только workdir и /tmp; продукт, ~/.spt, ~/metodika,
    ~/.claude, секреты — не примонтированы (невидимы). --unshare-all снимает и сеть."""
    argv = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session",
            "--tmpfs", "/home", "--proc", "/proc", "--dev", "/dev",
            "--tmpfs", "/tmp", "--bind", wd, wd, "--chdir", wd]
    # belt-and-suspenders (находка анализа [high/security]): если workdir ОХВАТЫВАЕТ deny_root
    # (spt запущен с cwd=$HOME или SPT_WORKDIR=~/metodika), bind сделал бы продукт/секреты видимыми
    # rw. Перекрываем каждый такой deny_root пустым tmpfs ПОСЛЕ bind (порядок → tmpfs побеждает).
    wdr = os.path.realpath(wd) + os.sep
    for d in deny_roots():
        dr = os.path.realpath(d)
        if (dr + os.sep).startswith(wdr) and dr + os.sep != wdr and os.path.isdir(dr):
            argv += ["--tmpfs", dr]
    for ro in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc/alternatives"):
        if os.path.exists(ro):
            argv += ["--ro-bind", ro, ro]
    return argv


def bwrap_argv(command, wd):
    """bwrap вокруг bash -c command (инструмент bash в чёрном ящике)."""
    return _bwrap_base(wd) + ["--", "/bin/bash", "-c", command]


_BASE_RO = ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc/alternatives")


def bwrap_exec_argv(exec_argv, wd, ro_extra=()):
    """bwrap вокруг произвольного argv — для запуска ДОВЕРЕННОГО интерпретатора над
    НЕдоверенным кодом (проверка кода в песочнице): без сети/секретов/защищённых путей.
    ro_extra — пути интерпретатора/stdlib, которые нужно ВЕРНУТЬ в namespace поверх
    tmpfs /home (иначе python из venv/conda под /home невидим → ложное ВЕТО). Секреты
    (~/.spt, ~/.ssh) вне этих путей и остаются скрытыми. Бинды идут ПОСЛЕ tmpfs — перекрывают."""
    argv = _bwrap_base(wd)
    for p in ro_extra:
        if not p or not os.path.exists(p):
            continue
        rp = os.path.realpath(p)
        if any(rp == b or rp.startswith(b + os.sep) for b in _BASE_RO):
            continue  # уже примонтирован базой — не дублируем (bwrap запретит)
        argv += ["--ro-bind", rp, rp]
    return argv + ["--"] + list(exec_argv)


def _norm(p):
    return os.path.realpath(os.path.expanduser(os.path.expandvars(p)))


def deny_roots():
    home = os.path.expanduser("~")
    roots = [
        _PRODUCT,                                   # сам терминал (реализация)
        os.path.join(home, ".spt"),                 # секреты: .env, teacher/creative.md
        os.path.join(home, "metodika"),             # метрика, SuperPromt, PromtMaster, agents, redteam
        os.path.join(home, ".claude"),              # конфиг AI-ассистента
        os.path.join(home, ".mimocode"),            # скиллы MiMo
        os.path.join(home, ".ssh"),
        os.path.join(home, ".aws"),
        os.path.join(home, ".config", "gcloud"),
    ]
    extra = os.environ.get("SPT_BLACKBOX_DENY", "")
    roots += [p for p in extra.split(os.pathsep) if p]
    return [_norm(r) for r in roots]


def workdir():
    return _norm(os.environ.get("SPT_WORKDIR", os.getcwd()))


def tmp_allow():
    """Разрешённый scratch-каталог в blackbox — СОБСТВЕННЫЙ подкаталог, а не весь /tmp
    (тот многопользовательский и world-writable: чужие файлы/символлинки — риск, L2)."""
    return _norm(os.environ.get("SPT_TMPDIR") or "/tmp/spt")


def enabled(cfg):
    if os.environ.get("SPT_BLACKBOX") in ("0", "off", "false"):
        return False
    if os.environ.get("SPT_BLACKBOX") in ("1", "on", "true"):
        return True
    return bool((cfg or {}).get("blackbox"))


def _under(path, root):
    return path == root or path.startswith(root + os.sep)


def check_path(path, cfg, write=False):
    """-> None если можно, иначе строка-отказ. Приоритет deny над allow."""
    if not enabled(cfg):
        return None
    p = _norm(path)
    for root in deny_roots():
        if _under(p, root):
            return ("[чёрный ящик] доступ к внутренним файлам продукта запрещён "
                    "(метрика/SuperPromt/скиллы/секреты защищены). Работайте в рабочей папке.")
    wd = workdir()
    tmp = tmp_allow()
    if _under(p, wd) or _under(p, tmp):
        return None
    return ("[чёрный ящик] доступ вне рабочей папки запрещён. Разрешено: %s и %s." % (wd, tmp))


# паттерны команд bash, вскрывающих реализацию/секреты (эвристический барьер)
_BASH_DENY = re.compile(
    r"(inspect\.getsource|\.__code__|dis\.dis|marshal|"           # интроспекция байткода
    r"import\s+(superprompt_cli|linkveto|psq|kscr)|"              # импорт внутренностей
    r"(cat|less|more|head|tail|strings|xxd|od|grep|rg|nl|sed|awk|vi|nano|open)\b[^|;&]*"
    r"(\.spt|/metodika/|superprompt_cli|\.env|SKILL\.md|link_veto|psq\.py|kscr\.py|"
    r"agents?/|PromtMaster|GATE\.md)|"
    r"\b(env|printenv|set)\b\s*$|"                                # дамп переменных (ключи)
    r"(_API_KEY|nvapi-|sk-or-|sk-ant-))",
    re.I)


def check_bash(command, cfg):
    """-> None если можно, иначе отказ. Плюс: запрет путей deny внутри команды."""
    if not enabled(cfg):
        return None
    if _BASH_DENY.search(command):
        return ("[чёрный ящик] команда обращается к внутренним файлам/секретам продукта — "
                "заблокирована. Терминал работает как чёрный ящик.")
    # прямое упоминание deny-корней путём (в т.ч. с ~)
    for root in deny_roots():
        base = os.path.basename(root)
        if root in command or ("~/" + base) in command:
            # разрешаем безобидные упоминания только если это не файловая операция — грубо блокируем
            return ("[чёрный ящик] путь к защищённому каталогу (%s) в команде — заблокирован."
                    % base)
    return None
