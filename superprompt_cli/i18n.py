"""Локализация spt: язык интерфейса (ui_lang) и язык ответа LLM (answer_lang).
По умолчанию оба — русский. Язык ОТВЕТА работает для любого языка (название идёт
в промт). Язык ИНТЕРФЕЙСА локализован для ключевых экранов; для непокрытых языков —
fallback на английский, затем русский."""

# код → (родное название, английское название для промта LLM)
LANGS = {
    "ru": ("Русский", "Russian"),
    "en": ("English", "English"),
    "zh": ("中文", "Chinese"),
    "kk": ("Қазақша", "Kazakh"),
    "fr": ("Français", "French"),
    "ja": ("日本語", "Japanese"),
    "es": ("Español", "Spanish"),
    "de": ("Deutsch", "German"),
    "pt": ("Português", "Portuguese"),
    "it": ("Italiano", "Italian"),
    "ko": ("한국어", "Korean"),
    "tr": ("Türkçe", "Turkish"),
    "ar": ("العربية", "Arabic"),
    "hi": ("हिन्दी", "Hindi"),
    "uk": ("Українська", "Ukrainian"),
}
DEFAULT = "ru"

# ключевые строки интерфейса. Ключ → {код языка: перевод}. Непокрытое → en → ru.
STR = {
    "slogan": {
        "ru": "Проверено, а не выдумано.", "en": "Verified, not vibes.",
        "zh": "经过验证，而非编造。", "kk": "Тексерілген, ойдан шығарылмаған.",
        "fr": "Vérifié, pas inventé.", "ja": "検証済み、でっち上げではない。",
    },
    "just_type": {
        "ru": "Просто напишите задачу. /help — команды.",
        "en": "Just type your task. /help for commands.",
        "zh": "直接输入任务。/help 查看命令。",
        "kk": "Тапсырманы жазыңыз. /help — командалар.",
        "fr": "Écrivez votre tâche. /help pour les commandes.",
        "ja": "タスクを入力してください。/help でコマンド一覧。",
    },
    "verified": {"ru": "ПРОВЕРЕНО", "en": "VERIFIED", "zh": "已验证",
                 "kk": "ТЕКСЕРІЛДІ", "fr": "VÉRIFIÉ", "ja": "検証済み"},
    "partial": {"ru": "ЧАСТИЧНО", "en": "PARTIAL", "zh": "部分",
                "kk": "ІШІНАРА", "fr": "PARTIEL", "ja": "部分的"},
    "failed": {"ru": "НЕ ПРОШЛО", "en": "NOT PASSED", "zh": "未通过",
               "kk": "ӨТПЕДІ", "fr": "ÉCHOUÉ", "ja": "不合格"},
    "no_external": {"ru": "БЕЗ ВНЕШНИХ ФАКТОВ", "en": "NO EXTERNAL FACTS",
                    "zh": "无外部事实", "kk": "СЫРТҚЫ ДЕРЕКТЕРСІЗ",
                    "fr": "SANS FAITS EXTERNES", "ja": "外部事実なし"},
    "no_external_short": {"ru": "— без внешних фактов —", "en": "— no external facts —",
                          "zh": "— 无外部事实 —", "kk": "— сыртқы деректерсіз —",
                          "fr": "— sans faits externes —", "ja": "— 外部事実なし —"},
    "insurance_on": {"ru": "страховка on", "en": "guard on", "zh": "护栏 开",
                     "kk": "қорғаныс on", "fr": "garde on", "ja": "ガード on"},
    "insurance_off": {"ru": "без страховки", "en": "no guard", "zh": "无护栏",
                      "kk": "қорғанышсыз", "fr": "sans garde", "ja": "ガードなし"},
    "welcome_title": {"ru": "Добро пожаловать в SuperPromt",
                      "en": "Welcome to SuperPromt", "zh": "欢迎使用 SuperPromt",
                      "kk": "SuperPromt-қа қош келдіңіз", "fr": "Bienvenue dans SuperPromt",
                      "ja": "SuperPromt へようこそ"},
    "welcome_desc": {
        "ru": "Терминал, который проверяет каждый ответ ИИ на выдумки.",
        "en": "A terminal that checks every AI answer for fabrication.",
        "zh": "一个检查每个 AI 回答是否编造的终端。",
        "kk": "ЖИ жауабын ойдан шығаруға тексеретін терминал.",
        "fr": "Un terminal qui vérifie chaque réponse IA contre l'invention.",
        "ja": "AIの回答の捏造をチェックするターミナル。",
    },
    "lang_ui_set": {"ru": "язык интерфейса", "en": "interface language",
                    "zh": "界面语言", "kk": "интерфейс тілі",
                    "fr": "langue de l'interface", "ja": "インターフェース言語"},
    "lang_answer_set": {"ru": "язык ответа", "en": "answer language",
                        "zh": "回答语言", "kk": "жауап тілі",
                        "fr": "langue de réponse", "ja": "回答言語"},
    "passport": {"ru": "ПАСПОРТ", "en": "PASSPORT", "zh": "护照",
                 "kk": "ПАСПОРТ", "fr": "PASSEPORT", "ja": "パスポート"},
    "k_domain": {"ru": "домен", "en": "domain", "zh": "领域", "kk": "домен",
                 "fr": "domaine", "ja": "領域"},
    "k_tier": {"ru": "тир", "en": "tier", "zh": "档位", "kk": "деңгей",
               "fr": "niveau", "ja": "ティア"},
    "k_prompt": {"ru": "промт", "en": "prompt", "zh": "提示", "kk": "сұраныс",
                 "fr": "invite", "ja": "プロンプト"},
    "k_model": {"ru": "модель", "en": "model", "zh": "模型", "kk": "модель",
                "fr": "modèle", "ja": "モデル"},
    "veto": {"ru": "ВЕТО", "en": "VETO", "zh": "否决", "kk": "ВЕТО",
             "fr": "VETO", "ja": "拒否"},
    "now": {"ru": "сейчас", "en": "now", "zh": "当前", "kk": "қазір",
            "fr": "en cours", "ja": "現在"},
    "steps": {"ru": "шагов", "en": "steps", "zh": "步", "kk": "қадам",
              "fr": "étapes", "ja": "ステップ"},
    "plan": {"ru": "План", "en": "Plan", "zh": "计划", "kk": "Жоспар",
             "fr": "Plan", "ja": "計画"},
    # ярлыки баннера — ВСЁ через i18n (при смене языка меняется весь интерфейс)
    "k_cwd": {"ru": "папка", "en": "cwd", "zh": "目录", "kk": "қалта",
              "fr": "dossier", "ja": "フォルダ"},
    "k_mode": {"ru": "режим", "en": "mode", "zh": "模式", "kk": "режим",
               "fr": "mode", "ja": "モード"},
    "k_memory": {"ru": "память", "en": "memory", "zh": "记忆", "kk": "жад",
                 "fr": "mémoire", "ja": "メモリ"},
    "k_answers": {"ru": "ответы", "en": "answers", "zh": "回答", "kk": "жауап",
                  "fr": "réponses", "ja": "回答"},
    "perm_auto": {"ru": "авто", "en": "auto", "zh": "авто", "kk": "авто",
                  "fr": "auto", "ja": "自動"},
    "perm_yolo": {"ru": "автономный", "en": "autonomous", "zh": "自主",
                  "kk": "автономды", "fr": "autonome", "ja": "自律"},
    "blackbox": {"ru": "чёрный ящик", "en": "black box", "zh": "黑盒",
                 "kk": "қара жәшік", "fr": "boîte noire", "ja": "ブラックボックス"},
    "role_owner": {"ru": "владелец", "en": "owner", "zh": "所有者", "kk": "иесі",
                   "fr": "propriétaire", "ja": "オーナー"},
    "role_trusted": {"ru": "доверенный", "en": "trusted", "zh": "受信任",
                     "kk": "сенімді", "fr": "de confiance", "ja": "信頼済み"},
    "role_subscriber": {"ru": "подписка", "en": "subscriber", "zh": "订阅",
                        "kk": "жазылым", "fr": "abonné", "ja": "購読"},
    "w_tasks": {"ru": "задач", "en": "tasks", "zh": "задач", "kk": "тапсырма",
                "fr": "tâches", "ja": "タスク"},
    "w_days_clean": {"ru": "дн без выдумок", "en": "days clean", "zh": "天无编造",
                     "kk": "күн таза", "fr": "jours sans invention", "ja": "日間クリーン"},
    "w_held": {"ru": "фабрикаций удержано ВЕТО", "en": "fabrications held by VETO",
               "zh": "编造被否决", "kk": "фабрикация ВЕТО-мен ұсталды",
               "fr": "fabrications bloquées par VETO", "ja": "捏造をVETOで阻止"},
    "mem_core": {"ru": "ядро", "en": "core", "zh": "核心", "kk": "ядро",
                 "fr": "noyau", "ja": "コア"},
    "mem_empty": {"ru": "пусто", "en": "empty", "zh": "空", "kk": "бос",
                  "fr": "vide", "ja": "空"},
    "no_models": {"ru": "нет моделей: /keys add или Ollama",
                  "en": "no models: /keys add or Ollama",
                  "zh": "无模型: /keys add 或 Ollama", "kk": "модель жоқ: /keys add",
                  "fr": "aucun modèle : /keys add ou Ollama",
                  "ja": "モデルなし: /keys add または Ollama"},
    "week": {"ru": "неделя", "en": "week", "zh": "本周", "kk": "апта",
             "fr": "semaine", "ja": "今週"},
    "hint_files": {"ru": "@ файл", "en": "@ file", "zh": "@ 文件", "kk": "@ файл",
                   "fr": "@ fichier", "ja": "@ ファイル"},
    "hint_cmds": {"ru": "/ команды", "en": "/ commands", "zh": "/ 命令",
                  "kk": "/ командалар", "fr": "/ commandes", "ja": "/ コマンド"},
    "hint_interrupt": {"ru": "Ctrl-C прервать", "en": "Ctrl-C interrupt",
                       "zh": "Ctrl-C 中断", "kk": "Ctrl-C үзу",
                       "fr": "Ctrl-C interrompre", "ja": "Ctrl-C 中断"},
    "hint_tab": {"ru": "Tab дополнить", "en": "Tab complete", "zh": "Tab 补全",
                 "kk": "Tab толықтыру", "fr": "Tab compléter", "ja": "Tab 補完"},
    # нумерованные быстрые действия после результата
    "next": {"ru": "дальше", "en": "next", "zh": "接下来", "kk": "келесі",
             "fr": "ensuite", "ja": "次に"},
    "a_retry": {"ru": "повтор", "en": "retry", "zh": "重试", "kk": "қайта",
                "fr": "refaire", "ja": "再試行"},
    "a_why": {"ru": "разбор", "en": "why", "zh": "解析", "kk": "талдау",
              "fr": "détail", "ja": "解析"},
    "a_links": {"ru": "ссылки md", "en": "links md", "zh": "链接 md",
                "kk": "сілтемелер md", "fr": "liens md", "ja": "リンク md"},
    "a_strict": {"ru": "строже", "en": "stricter", "zh": "更严", "kk": "қатаңырақ",
                 "fr": "plus strict", "ja": "厳格に"},
    "a_gate_on": {"ru": "включить гейт", "en": "enable gate", "zh": "启用门",
                  "kk": "гейтті қосу", "fr": "activer le gate", "ja": "ゲート有効"},
    "tip": {"ru": "подсказка", "en": "tip", "zh": "提示", "kk": "кеңес",
            "fr": "astuce", "ja": "ヒント"},
    "tip_start": {"ru": "наберите задачу или /help для команд",
                  "en": "type a task or /help for commands",
                  "zh": "输入任务或 /help 查看命令", "kk": "тапсырма немесе /help",
                  "fr": "tapez une tâche ou /help", "ja": "タスクか /help を入力"},
    "k1000": {"ru": "К", "en": "K", "zh": "千", "kk": "К", "fr": "k", "ja": "K"},
    "input_ph": {"ru": "напишите задачу · / команды", "en": "type a task · / commands",
                 "zh": "输入任务 · / 命令", "kk": "тапсырма · / командалар",
                 "fr": "tapez une tâche · / commandes", "ja": "タスク · / コマンド"},
}


# РОТАЦИЯ подсказок (tip) — как у MiMo, разная при каждом запуске
TIPS = {
    "ru": ["/theme меняет цветовую схему (7 палитр)",
           "жмите 1 / 2 / 3 — быстрые действия после результата",
           "@файл вкладывает файл в задачу",
           "/max — N кандидатов + судья + гейт выхода",
           "/gates strict — режим скептика: неопределённое = вето",
           "/lang меняет язык интерфейса и ответов",
           "русские алиасы: /повтор · /почему · /цвет · /настройки",
           "Tab дополняет слэш-команды",
           "/goal <цель> :: <задача> — цикл до достижения цели"],
    "en": ["/theme switches the color scheme (7 palettes)",
           "press 1 / 2 / 3 for quick actions after a result",
           "@file attaches a file to your task",
           "/max — N candidates + judge + гейт выхода gate",
           "/gates strict — skeptic mode: uncertain = veto",
           "/lang switches interface and answer language",
           "Tab completes slash commands",
           "/goal <goal> :: <task> — loop until the goal is met"],
}


def random_tip(lang="ru"):
    import random
    tips = TIPS.get(norm(lang)) or TIPS["en"]
    return random.choice(tips)


def norm(code):
    code = (code or DEFAULT).lower().split("-")[0].split("_")[0]
    return code if code in LANGS else DEFAULT


def t(key, lang=DEFAULT):
    """Строка интерфейса. Fallback: язык → en → ru → сам ключ."""
    d = STR.get(key, {})
    lang = norm(lang)
    return d.get(lang) or d.get("en") or d.get("ru") or key


def native_name(code):
    return LANGS.get(norm(code), LANGS[DEFAULT])[0]


def english_name(code):
    return LANGS.get(norm(code), LANGS[DEFAULT])[1]


def answer_instruction(code):
    """Инструкция языка ответа для системного промта LLM (работает для любого языка)."""
    code = norm(code)
    if code == "ru":
        return "Отвечай на русском языке."
    en = english_name(code)
    nat = native_name(code)
    return "Answer STRICTLY in %s (%s), regardless of the task's language." % (en, nat)


def list_langs():
    return [(c, LANGS[c][0]) for c in LANGS]
