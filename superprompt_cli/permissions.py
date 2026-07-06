"""Режимы разрешений spt (как в Claude Code, три уровня):

  ask  — с подтверждением: спрашивать перед каждым опасным инструментом
         (bash / write_file / edit_file). Дефолт.
  auto — без подтверждения на рутинные, НО вопрос на КРИТИЧЕСКИЕ ситуации
         (rm -rf, sudo, запись вне рабочей папки, curl|bash, диск, права и т.п.).
  yolo — автономный без ограничений: не спрашивать никогда.

Критическое ловится детерминированным списком паттернов (перестраховка: лучше
лишний вопрос, чем тихий вред). В blackbox запись вне workdir и так заблокирована
sandbox'ом — здесь дополнительный слой намерения."""
import re

MODES = ("ask", "auto", "yolo")
DEFAULT = "ask"

DANGEROUS = {"bash", "write_file", "edit_file"}

# критические паттерны команд bash — вопрос ДАЖЕ в auto-режиме.
# ВАЖНО (security-аудит): это DENYLIST — он структурно НЕ полон (shell обходится
# кавычками/переменными/glob). auto НЕ безопасен при недоверенном вводе (web/@-файлы) —
# для такого используйте ask или blackbox. Ниже — перекрытие частых каналов вреда.
_CRITICAL = re.compile(
    r"\brm\s+-[a-z]*[rf]|"                      # rm -rf / -fr
    r"\bfind\b[^|;&]*-delete|"                  # find … -delete (обходит rm)
    r"\bsudo\b|\bsu\b|\bdoas\b|"               # эскалация прав
    r"\bmkfs|\bfdisk|\bparted|\bdd\s+.*of=|"   # диск/разметка
    r">\s*/dev/(sd|nvme|disk|mapper)|"          # запись в диск-устройства (не /dev/null|zero)
    r":\(\)\s*\{|\bfork\b.*bomb|"              # fork-бомба
    r"\bchmod\s+-R|\bchmod\s+[0-7]*777|\bchown\s+-R|"  # массовые права
    r"\bcurl\b[^|]*\|\s*(ba)?sh|\bwget\b[^|]*\|\s*(ba)?sh|"  # curl|bash
    # эксфильтрация: сеть + чтение локального файла/секрета
    r"\b(curl|wget)\b[^|;&]*(--data|--upload-file|-d\s|-T\s|@)|"
    r"\b(nc|ncat|netcat|socat)\b|\bscp\b|\bsftp\b|\brsync\b[^|;&]*::|"
    r"\b(base64|xxd|openssl\s+enc)\b[^|;&]*(id_rsa|id_ed25519|\.env|\.pem|secret|key)|"
    r"\bshutdown\b|\breboot\b|\bhalt\b|\bpoweroff\b|\binit\s+0|"
    r"\bkill\s+-9\s+1\b|\bkillall\b|\bpkill\s+-9|"
    r"\bgit\s+push\b.*(--force|-f)\b|\bgit\s+reset\s+--hard|"
    r"\biptables|\bufw\b|\bsystemctl\b\s+(stop|disable|mask)|"
    r"\bcrontab\b|\bat\s+now|\bsystemd-run\b|"  # закрепление (cron/at/systemd)
    r"\btee\s+-a?\b[^|;&]*(authorized_keys|\.bashrc|\.profile|cron|rc\.local)|"
    r"\bcrontab\s+-r|"                          # снос cron
    r">>?\s*~?/?[^|;&]*(authorized_keys|\.bashrc|\.profile|\.ssh|\.aws|\.env)|"  # дозапись в конфиги/секреты
    r"\bnpm\s+publish|\bpip\s+.*--index-url|"   # supply-chain
    r"\btruncate\b|\bshred\b|\bwipe\b",
    re.I)

# критические пути для write/edit (вне рабочей папки, системное) — вопрос в auto
_CRITICAL_PATH = re.compile(
    r"^/(etc|bin|sbin|usr|boot|lib|lib64|sys|proc|dev)/|"
    r"\.ssh/|\.aws/|\.env$|/\.bashrc|/\.profile|"
    r"authorized_keys|id_rsa|id_ed25519|\.pem$|\.key$",
    re.I)


def is_critical(name, args):
    """-> причина (строка) если критично, иначе None."""
    if name == "bash":
        cmd = args.get("command", "")
        m = _CRITICAL.search(cmd)
        if m:
            return "критичная команда: %s" % m.group(0)[:40]
    elif name in ("write_file", "edit_file"):
        path = args.get("path", "")
        if _CRITICAL_PATH.search(path):
            return "запись в критичный путь: %s" % path[:50]
    return None


def normalize(mode):
    return mode if mode in MODES else DEFAULT


def needs_confirm(name, args, mode):
    """-> (нужно_спросить: bool, причина|None). Логика трёх режимов."""
    mode = normalize(mode)
    if name not in DANGEROUS:
        return False, None
    if mode == "yolo":
        return False, None                      # автономный: не спрашиваем
    if mode == "auto":
        reason = is_critical(name, args)
        return (bool(reason), reason)           # только критическое
    return True, None                           # ask: всё опасное
