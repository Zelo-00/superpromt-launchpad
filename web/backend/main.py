import asyncio
import os
import re
import sys
import time
import uuid
import json
from collections import defaultdict, deque
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import io
import zipfile
import tempfile
import shutil
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from launchers import make_launchers
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

# Добавляем корень проекта в sys.path для импорта superprompt_cli
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, root_path)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # каталог бэкенда — для локальных модулей (storage)

import superprompt_cli.psq as psq
import superprompt_cli.psq_with_skills as psq_skills
import superprompt_cli.router as router
import superprompt_cli.webskills as webskills
import superprompt_cli.agentloop as agentloop
import superprompt_cli.providers as providers
import superprompt_cli.memory as memory
import superprompt_cli.sessions as sessions
from storage import HistoryStorage

class Settings(BaseSettings):
    app_name: str = "SuperPromt API"
    debug: bool = False
    # Формат ядра: "провайдер/модель" (см. superprompt_cli/providers.py).
    # Дефолты — доступные на шлюзе модели (gpt-4o на этом шлюзе нет → пустой ответ у repair).
    # Переопределяются env JUDGE_MODEL / REPAIR_MODEL.
    judge_model: str = "openai/grok-4.1-fast-non-reasoning"
    repair_model: str = "openai/grok-4.1-fast-non-reasoning"
    db_path: str = "history.db"
    rate_limit_requests: int = 60
    rate_limit_window: int = 60
    allowed_origins: str = "http://localhost:8000,http://127.0.0.1:8000"

    class Config:
        env_file = ".env"

settings = Settings()
storage = HistoryStorage(settings.db_path)
app = FastAPI(title=settings.app_name)

# --- Rate Limiting ---
# Простая реализация скользящего окна на словаре IP -> deque меток времени
client_requests: Dict[str, deque] = defaultdict(deque)

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Ограничиваем только API
    if request.url.path.startswith("/api"):
        # Ключ лимита: CF-Connecting-IP ставится краем Cloudflare (клиент подменить не может),
        # иначе — реальный peer. Клиентский X-Forwarded-For не использовать: тривиальный обход.
        client_ip = request.headers.get("cf-connecting-ip") or request.client.host
        now = time.time()
        window_start = now - settings.rate_limit_window
        
        # Очищаем старые метки
        while client_requests[client_ip] and client_requests[client_ip][0] < window_start:
            client_requests[client_ip].popleft()

        if len(client_requests[client_ip]) >= settings.rate_limit_requests:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again later."}
            )

        client_requests[client_ip].append(now)
        # анти-утечка: периодически выметаем IP, у которых окно опустело (иначе dict растёт вечно)
        if len(client_requests) > 1000:
            for ip in [k for k, dq in client_requests.items()
                       if not dq or dq[-1] < window_start]:
                client_requests.pop(ip, None)

    return await call_next(request)

# --- Security Headers ---
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    # Превью сгенерированного проекта грузится в НАШ same-origin iframe — DENY его ломает
    # (находка ревью). SAMEORIGIN разрешает фрейминг только своим origin. Остальное — DENY.
    if request.url.path.startswith("/api/preview/"):
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        # у превью своя CSP не навязывается — это чужой (сгенерированный) документ
    else:
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "frame-src 'self'; "                    # разрешить свой preview-iframe
            "frame-ancestors 'self';"               # современный аналог X-Frame-Options
        )
    return response

# --- CORS ---
origins = [o.strip() for o in settings.allowed_origins.split(",")]
allow_all = "*" in origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=not allow_all,  # НЕ отдаем credentials при wildcard
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Static Files ---
frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../frontend"))

# Эндпоинты API должны быть объявлены ДО монтирования статики на корень

# --- Models ---

MAX_PROMPT_LENGTH = 5000
GEN_MAX_TOKENS = 32000           # общий лимит токенов генерации (поднят против обрыва)
PER_FILE_MAX_TOKENS = 16000      # бюджет НА КАЖДЫЙ файл при многопроходной генерации (HTML/CSS/JS)
MULTIPASS_PROMPT_CHARS = 900     # промт длиннее → сложный сайт → генерировать по частям (по файлам)
REVIEW_MAX_TOKENS = 700          # лимит токенов агента-ревьюера
MAX_BUILD_CYCLES = 3             # ремонт-цикл: максимум проходов до PASS
PREVIEW_TTL_SEC = 6 * 3600       # сколько живут served-превью до сборки мусора
LLM_ENV_KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")


def _has_llm() -> bool:
    """Настроен ли LLM-провайдер (ключ в окружении). Единый источник для всех эндпоинтов."""
    return any(os.environ.get(k) for k in LLM_ENV_KEYS)

class PSQRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=MAX_PROMPT_LENGTH, description="Сырой текст задачи")

class FlagItem(BaseModel):
    name: str
    count: int

class PSQResponse(BaseModel):
    psq: float
    raw_psq: Optional[float]
    c: List[int]
    a: float
    gaming: float
    flags: List[FlagItem]
    prescreen: Optional[str] = None

class SkillItem(BaseModel):
    name: str
    text: str
    desc: str = ""      # чистое описание из frontmatter — превью карточки (не сырой markdown)

class SkillsResponse(BaseModel):
    domain: str
    confidence: float
    skills: List[SkillItem]

class HistoryEntry(BaseModel):
    id: int
    timestamp: str
    prompt: str
    psq: float
    gaming: float
    prescreen: Optional[str]
    mode: str

class StatsResponse(BaseModel):
    total_count: int
    avg_psq: float
    low_psq_ratio: float
    modes: Dict[str, int]
    recent_points: List[Dict[str, Any]]
    flags_distribution: Dict[str, int]

class RepairRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=MAX_PROMPT_LENGTH)

class RepairResponse(BaseModel):
    improved_text: str

class DemoResponse(BaseModel):
    mode: str = "demo"

class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=MAX_PROMPT_LENGTH)
    tier: str = Field(default="mid", description="min|mid|max")
    model: Optional[str] = Field(default=None, description="LLM model (provider/model)")

class GenerateResponse(BaseModel):
    answer: str
    passport: Dict[str, Any]
    journal: str
    psq_before: Optional[float] = None
    psq_after: Optional[float] = None
    domain: str = ""
    skills_used: List[str] = []
    files: List[Dict[str, Any]] = []
    archive_url: Optional[str] = None
    preview_url: Optional[str] = None    # /api/preview/<id>/index.html — живое превью сайта в iframe
    verification: Optional[Dict[str, Any]] = None  # агентная проверка кода/результата (вместо KSCR)
    tokens: Optional[int] = None                   # суммарно токенов за прогон
    cost_usd: Optional[float] = None               # ≈ оценка стоимости по live-ценам OpenRouter

class MemoryEvent(BaseModel):
    ts: str
    event: str
    task: Optional[str] = None
    domain: Optional[str] = None
    psq: Optional[str] = None
    steps: Optional[int] = None
    tokens: Optional[int] = None

class MemoryResponse(BaseModel):
    core: str
    core_size: int
    daily_events: List[MemoryEvent]
    sessions_count: int
    total_events: int

class DistillResponse(BaseModel):
    status: str
    core_size: int
    message: str

# --- Endpoints ---

@app.get("/api/prescreen")
async def get_prescreen(prompt: str):
    """
    Детерминированная оценка промта без использования LLM.
    """
    # Используем существующую логику prescreen из superprompt_cli
    res = psq.prescreen(prompt)
    if not res:
        # Если штатный prescreen не сработал (например, промт слишком короткий или сложный),
        # реализуем базовую эвристику здесь
        flags = []
        score = 0.5
        
        if len(prompt) < 20:
            flags.append({"name": "too_short", "count": 1})
            score -= 0.2
        if "лучший" in prompt.lower() or "идеальный" in prompt.lower():
            flags.append({"name": "self_praise", "count": 1})
            score -= 0.1
        if "{placeholder}" in prompt or "[...]" in prompt:
            flags.append({"name": "placeholders", "count": 1})
            score -= 0.2
            
        res = {
            "psq": max(0.0, min(1.0, score)),
            "flags": flags
        }
    else:
        # Приводим формат флагов к единому виду
        # В superprompt_cli.psq.prescreen флаги могут быть пустым списком []
        # Если это короткий промт (<40 символов), добавляем флаг too_short вручную для теста
        flags_raw = res.get("flags", [])
        res["flags"] = [{"name": f[0], "count": f[1]} for f in flags_raw]
        
        if res.get("prescreen") == "short" and not any(f["name"] == "too_short" for f in res["flags"]):
            res["flags"].append({"name": "too_short", "count": 1})
        
    return res

@app.post("/api/demo")
async def post_demo():
    """
    Возвращает заранее собранный ZIP-архив с демо-сайтом и лаунчерами.
    """
    demo_assets_path = os.path.join(os.path.dirname(__file__), "demo_assets")
    
    # Создаем временную директорию для сборки
    with tempfile.TemporaryDirectory() as tmpdir:
        # Копируем ассеты
        if os.path.exists(demo_assets_path):
            for item in os.listdir(demo_assets_path):
                shutil.copy(os.path.join(demo_assets_path, item), tmpdir)
        
        # Генерируем лаунчеры
        make_launchers(tmpdir)
        
        # Создаем ZIP в памяти
        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(tmpdir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, tmpdir)
                    zf.write(file_path, arcname)
        
        memory_file.seek(0)
        
        # Возвращаем файл с кастомным заголовком для пометки demo режима
        headers = {
            "X-Mode": "demo",
            "Access-Control-Expose-Headers": "X-Mode",
            "Content-Disposition": "attachment; filename=demo_site.zip"
        }
        return StreamingResponse(memory_file, media_type="application/zip", headers=headers)

@app.post("/api/repair", response_model=RepairResponse)
async def repair_prompt(req: RepairRequest):
    if len(req.prompt) > MAX_PROMPT_LENGTH:
        raise HTTPException(status_code=422, detail="Prompt too long")
    try:
        # Проверяем наличие ключа для repair
        has_llm = _has_llm()
        if not has_llm:
            raise HTTPException(
                status_code=503,
                detail="Улучшение промта недоступно: LLM-провайдер не настроен."
            )
        
        # sync-вызов LLM в поток — не блокировать event loop (находка ревью)
        res = await asyncio.to_thread(psq.repair, req.prompt, settings.repair_model)
        return {"improved_text": res}
    except HTTPException:
        raise
    except Exception as e:
        # Если psq.repair упал из-за отсутствия конфигурации провайдера внутри
        if "no provider" in str(e).lower() or "not configured" in str(e).lower():
             raise HTTPException(status_code=503, detail="Улучшение недоступно: провайдер не настроен (BYOK).")
        raise HTTPException(status_code=500, detail="Внутренняя ошибка при улучшении промта.")

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}

@app.get("/api/status")
async def get_status():
    # Проверяем наличие ключа (упрощенно, так как superprompt_cli сам управляет провайдерами)
    # В реальности мы можем проверить наличие OPENAI_API_KEY или аналогичных переменных
    has_llm = _has_llm()
    return {
        "mode": "deep" if has_llm else "fast",
        "llm_configured": has_llm
    }

# ── Живой каталог цен OpenRouter (публичный /models, без ключа) + оценка стоимости ──
_OR_CACHE = {"ts": 0.0, "models": []}
_OR_TTL = 3600
# усреднённая доля prompt/completion токенов для оценки стоимости генерации кода
_OR_PROMPT_SHARE = 0.3
_OR_COMPLETION_SHARE = 0.7


def _or_fetch_models():
    import urllib.request as _u
    now = time.time()
    if _OR_CACHE["models"] and now - _OR_CACHE["ts"] < _OR_TTL:
        return _OR_CACHE["models"]
    try:
        req = _u.Request("https://openrouter.ai/api/v1/models",
                         headers={"User-Agent": "SuperPromt/1.0"})
        with _u.urlopen(req, timeout=15) as r:
            data = json.load(r)
        out = []
        for m in data.get("data", []):
            pr = m.get("pricing") or {}
            def _f(v):
                try:
                    return float(v) if v is not None else None
                except (TypeError, ValueError):
                    return None
            out.append({"id": m.get("id", ""), "name": m.get("name", m.get("id", "")),
                        "ctx": m.get("context_length"),
                        "prompt_price": _f(pr.get("prompt")),
                        "completion_price": _f(pr.get("completion"))})
        if out:
            _OR_CACHE["models"] = out
            _OR_CACHE["ts"] = now
        return out
    except Exception:
        return _OR_CACHE["models"]  # при сбое сети — отдаём кэш (возможно пустой)


def _or_price(model_spec):
    """-> (prompt_price, completion_price) $/токен для 'openrouter/<id>' или '<id>'."""
    mid = model_spec.split("/", 1)[1] if model_spec.startswith("openrouter/") else model_spec
    for m in _or_fetch_models():
        if m["id"] == mid:
            return m["prompt_price"], m["completion_price"]
    return None, None


def _estimate_cost(model_spec, total_tokens):
    pp, pc = _or_price(model_spec or "")
    if not total_tokens or pp is None or pc is None:
        return None
    blended = _OR_PROMPT_SHARE * pp + _OR_COMPLETION_SHARE * pc
    return round(total_tokens * blended, 6)


@app.get("/api/or-models")
async def or_models(coding: bool = True, limit: int = 30):
    """Живой каталог моделей OpenRouter с ценами (публичный API, без ключа)."""
    models = _or_fetch_models()

    def _key(m):
        pc = m["completion_price"]
        return (pc is None, pc if pc is not None else 1e9)

    if coding:
        allow = ("coder", "code", "qwen", "deepseek", "gpt-oss", "gpt-4o", "gpt-5",
                 "gemini", "grok", "llama", "mistral", "glm", "kimi", "mimo")
        models = [m for m in models if any(a in m["id"].lower() for a in allow)]
    # отбрасываем модели-роутеры с плавающей ценой (-1) и без цены
    models = [m for m in models
              if m["prompt_price"] is not None and m["prompt_price"] >= 0
              and m["completion_price"] is not None and m["completion_price"] >= 0]
    models = sorted(models, key=_key)[:limit]
    return {"models": models, "count": len(models)}


@app.get("/api/models")
async def get_models():
    """Список доступных моделей для BYOK"""
    import superprompt_cli.providers as prov
    try:
        cfg = prov.config.load()
        models = []
        for prov_name, prov_cfg in cfg.get("providers", {}).items():
            if prov_cfg.get("local"):
                continue
            # Добавляем базовые модели для каждого провайдера
            if prov_name == "openrouter":
                models.extend([
                    {"id": "openrouter/qwen/qwen3-coder-next", "name": "Qwen3 Coder Next", "provider": "openrouter", "price": "mid"},
                    {"id": "openrouter/qwen/qwen3-coder-plus", "name": "Qwen3 Coder Plus", "provider": "openrouter", "price": "high"},
                    {"id": "openrouter/deepseek/deepseek-v4-flash", "name": "DeepSeek V4 Flash", "provider": "openrouter", "price": "low"},
                ])
            elif prov_name == "openai":
                models.append({"id": "openai/gpt-4o", "name": "GPT-4o", "provider": "openai", "price": "high"})
            elif prov_name == "anthropic":
                models.append({"id": "anthropic/claude-sonnet-4-5", "name": "Claude Sonnet 4.5", "provider": "anthropic", "price": "high"})
        return {"models": models}
    except Exception as e:
        return {"models": [], "error": str(e)}

@app.post("/api/verify")
async def verify_key(request: Request):
    """Проверка API-ключа"""
    try:
        body = await request.json()
        key = body.get("key", "")
        provider = body.get("provider", "openrouter")
        
        if not key:
            return {"valid": False, "error": "Ключ не указан"}
        
        # Проверяем ключ через OpenRouter API
        import urllib.request
        import json
        
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {key}"}
        )
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        
        if "data" in data and len(data["data"]) > 0:
            return {"valid": True, "provider": provider, "models_count": len(data["data"])}
        else:
            return {"valid": False, "error": "Неверный ключ"}
    except Exception as e:
        return {"valid": False, "error": str(e)}

@app.post("/api/psq", response_model=PSQResponse)
async def calculate_psq(req: PSQRequest):
    try:
        # Проверяем режим (для истории)
        has_llm = _has_llm()
        mode = "deep" if has_llm else "fast"

        # 1. Детерминированный пре-скрининг (не требует LLM)
        res = psq.prescreen(req.prompt)
        if res:
            # Преобразуем флаги из кортежей в объекты
            flags_raw = res["flags"]
            res["flags"] = [{"name": f[0], "count": f[1]} for f in res["flags"]]
            storage.add_entry(req.prompt, res["psq"], res["gaming"], res["prescreen"], mode, res["flags"])
            return res

        # 2. Если пре-скрининг не дал результата, нужен судья (LLM → в поток)
        try:
            res = await asyncio.to_thread(psq.score, req.prompt, settings.judge_model)
            # Преобразуем флаги
            res["flags"] = [{"name": f[0], "count": f[1]} for f in res["flags"]]
            storage.add_entry(req.prompt, res["psq"], res["gaming"], res.get("prescreen"), mode, res["flags"])
            return res
        except Exception as e:
            # Любая ошибка судьи (нет ключа/сети, неизвестный или ненастроенный провайдер) →
            # честный 503 «глубокая оценка недоступна», а не 500. Детерминированный
            # pre-скрининг при этом всегда работает без провайдера.
            raise HTTPException(
                status_code=503,
                detail="LLM-судья недоступен (провайдер не настроен, нет ключа или сети). "
                       "Детерминированный pre-скрининг работает без провайдера.",
            )

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Внутренняя ошибка при оценке промта.")

@app.get("/api/history", response_model=List[HistoryEntry])
async def get_history(n: int = 10):
    if n <= 0:
        raise HTTPException(status_code=400, detail="N must be positive")
    return storage.get_history(limit=n)

@app.get("/api/history/{entry_id}", response_model=HistoryEntry)
async def get_history_entry(entry_id: int):
    entry = storage.get_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry

@app.get("/api/stats", response_model=StatsResponse)
async def get_stats():
    return storage.get_stats()

@app.delete("/api/history")
async def clear_history():
    storage.clear_history()
    return {"status": "ok"}

@app.get("/api/skills", response_model=SkillsResponse)
async def get_skills(task: str):
    try:
        domain, confidence, _ = router.classify_conf(task)
        
        # LLM-based ranking with fallback to TF-IDF (LLM-путь → в поток, не блокировать loop)
        try:
            from superprompt_cli import config as spt_config
            cfg = spt_config.load()
            skills_data = await asyncio.to_thread(webskills.rank, task, 10, settings.judge_model, cfg)
        except Exception:
            skills_data = await asyncio.to_thread(webskills.rank, task, 10)
        
        # Добавляем lean-code если нужно, как это делает router.pick_skills
        skills = []
        if domain in ("code", "mixed"):
            skills.append(SkillItem(name="lean-code(builtin)", text=router.PONYTAIL_RULES,
                                    desc="Дисциплина минимального кода: YAGNI, переиспользование, "
                                         "root-cause багфиксов, один запускаемый чек."))

        for s in skills_data:
            skills.append(SkillItem(name=s["name"], text=s["text"], desc=s.get("desc", "")))
            
        return {
            "domain": domain,
            "confidence": confidence,
            # политика владельца: минимум 5 скиллов на задачу, по нисходящей релевантности
            # (+builtin lean-code для code/mixed сверх лимита)
            "skills": skills[:7]
        }
    except Exception:
        raise HTTPException(status_code=500, detail="Внутренняя ошибка при подборе скиллов.")

def _verify_result(work_dir, files_created, prompt, model, cfg):
    """АГЕНТНАЯ ПРОВЕРКА результата (вместо метрики KSCR): детерминированные чеки кода +
    LLM-агент-ревьюер. -> {verdict, checks:[{name,ok,note}], review, issues:[...]}."""
    import re
    checks = []

    def chk(name, ok, note=""):
        checks.append({"name": name, "ok": bool(ok), "note": note})

    idx = os.path.join(work_dir, "index.html")
    html = ""
    if os.path.isfile(idx):
        html = open(idx, encoding="utf-8", errors="replace").read()
    chk("index.html присутствует", os.path.isfile(idx), "точка входа проекта")
    chk("валидный HTML-каркас", "<!doctype" in html.lower() and "<html" in html.lower()
        and "</html>" in html.lower(), "doctype + html + закрытие")
    chk("есть <title>", "<title>" in html.lower(), "заголовок вкладки")
    # ссылки на локальные css/js разрешаются в созданные файлы
    made = {f["path"].replace("\\", "/") for f in files_created}
    refs = re.findall(r'(?:href|src)="([^"]+)"', html, re.I)
    local = [r for r in refs if not r.startswith(("http", "//", "#", "data:", "mailto:"))]
    broken = [r for r in local if r.lstrip("./") not in made
              and os.path.normpath(r) not in {os.path.normpath(m) for m in made}]
    chk("локальные ссылки разрешаются", not broken,
        ("битые: " + ", ".join(broken[:3])) if broken else "css/js/картинки на месте")
    chk("нет пустых файлов", all(f["size"] > 0 for f in files_created), "у всех файлов есть содержимое")
    non_ascii_ok = True
    chk("несколько файлов (html+css/js)", len(made) >= 2, "проект разложен по файлам")

    det_ok = sum(1 for c in checks if c["ok"])
    review, issues, verdict = "", [], "PASS"
    # LLM-агент-ревьюер: смотрит реальный код и соответствие запросу
    try:
        code_snip = ""
        for f in files_created:
            p = os.path.join(work_dir, f["path"])
            if os.path.isfile(p) and f["path"].rsplit(".", 1)[-1] in ("html", "css", "js"):
                code_snip += f"\n===== {f['path']} =====\n" + \
                    open(p, encoding="utf-8", errors="replace").read()[:4000]
        rev_prompt = (
            "Ты — придирчивый ревьюер-агент. Проверь, что сгенерированный проект РЕАЛЬНО "
            "выполняет запрос пользователя и не содержит грубых дефектов.\n\n"
            f"ЗАПРОС ПОЛЬЗОВАТЕЛЯ:\n{prompt}\n\nКОД ПРОЕКТА:\n{code_snip[:12000]}\n\n"
            "Верни СТРОГО JSON: {\"verdict\":\"PASS\"|\"WARN\"|\"FAIL\", "
            "\"issues\":[\"кратко дефект 1\", ...], \"summary\":\"одно предложение\"}. "
            "PASS — запрос выполнен, критичных дефектов нет. WARN — работает, но есть недочёты. "
            "FAIL — запрос не выполнен или код нерабочий. Не выдумывай — суди по коду.")
        r = providers.chat(model, [{"role": "user", "content": rev_prompt}],
                           max_tokens=REVIEW_MAX_TOKENS, temperature=0.0, cfg=cfg, timeout=60)
        m = re.search(r'\{.*\}', r["text"], re.S)
        if m:
            data = json.loads(m.group(0))
            verdict = data.get("verdict", "PASS") if data.get("verdict") in ("PASS", "WARN", "FAIL") else "PASS"
            issues = [str(x)[:200] for x in (data.get("issues") or [])][:6]
            review = str(data.get("summary", ""))[:400]
    except Exception:  # noqa: BLE001 — ревьюер опционален, детерминированные чеки уже есть
        review = "агент-ревьюер недоступен — вердикт по детерминированным проверкам"
    # финальный вердикт: детерминированные провалы жёстче мнения агента
    if det_ok < len(checks) - 1 or broken:
        verdict = "FAIL" if verdict == "PASS" else verdict
    return {"verdict": verdict, "checks": checks, "review": review, "issues": issues,
            "passed": det_ok, "total": len(checks)}


def _answer_to_files(answer, work_dir):
    """Разложить ответ LLM (блоки кода) в файлы проекта в work_dir: FILE-маркеры → стандартные
    блоки → last-resort; авто-сплит инлайн CSS/JS из index.html; гарантия <link>/<script src>;
    дедуп по пути. -> files_created:[{path,size,kind}]. Чистая функция для repair-цикла."""
    import re
    file_blocks = re.findall(r'```(?:html|css|javascript|js|python)?\s*\n<!--\s*FILE:\s*(\S+)\s*-->|/\*\s*FILE:\s*(\S+)\s*\*/|//\s*FILE:\s*(\S+)', answer, re.I)
    code_blocks = re.findall(r'```(?:html|css|javascript|js|python)?\s*\n(.*?)```', answer, re.S)
    files_created = []
    if file_blocks:
        for match in re.finditer(r'```(?:html|css|javascript|js|python)?\s*\n(?:<!--\s*FILE:\s*(\S+)\s*-->|/\*\s*FILE:\s*(\S+)\s*\*/|//\s*FILE:\s*(\S+))\s*\n(.*?)```', answer, re.S | re.I):
            fname = match.group(1) or match.group(2) or match.group(3)
            content = match.group(4).strip()
            if fname and content:
                fpath = os.path.join(work_dir, fname)
                os.makedirs(os.path.dirname(fpath), exist_ok=True)
                with open(fpath, 'w', encoding='utf-8') as f:
                    f.write(content)
                files_created.append({"path": fname, "size": len(content), "kind": "text"})
    if not files_created and code_blocks:
        html_blocks = [b for b in code_blocks if '<html' in b.lower() or '<!doctype' in b.lower()]
        css_blocks = [b for b in code_blocks if 'body' in b.lower() and '{' in b and '<' not in b]
        js_blocks = [b for b in code_blocks if 'function' in b or 'const' in b or '=>' in b]
        if html_blocks:
            with open(os.path.join(work_dir, "index.html"), 'w', encoding='utf-8') as f:
                f.write(html_blocks[0].strip())
            files_created.append({"path": "index.html", "size": len(html_blocks[0]), "kind": "text"})
        if css_blocks:
            os.makedirs(os.path.join(work_dir, "css"), exist_ok=True)
            with open(os.path.join(work_dir, "css", "style.css"), 'w', encoding='utf-8') as f:
                f.write(css_blocks[0].strip())
            files_created.append({"path": "css/style.css", "size": len(css_blocks[0]), "kind": "text"})
        if js_blocks:
            os.makedirs(os.path.join(work_dir, "js"), exist_ok=True)
            with open(os.path.join(work_dir, "js", "app.js"), 'w', encoding='utf-8') as f:
                f.write(js_blocks[0].strip())
            files_created.append({"path": "js/app.js", "size": len(js_blocks[0]), "kind": "text"})
    if not files_created:
        with open(os.path.join(work_dir, "index.html"), 'w', encoding='utf-8') as f:
            f.write(answer)
        files_created.append({"path": "index.html", "size": len(answer), "kind": "text"})

    index_path = os.path.join(work_dir, "index.html")
    if os.path.exists(index_path):
        html_content = open(index_path, encoding='utf-8').read()
        css_matches = re.findall(r'<style[^>]*>(.*?)</style>', html_content, re.S | re.I)
        if css_matches:
            css_content = '\n'.join(css_matches)
            os.makedirs(os.path.join(work_dir, "css"), exist_ok=True)
            with open(os.path.join(work_dir, "css", "style.css"), 'w', encoding='utf-8') as f:
                f.write(css_content)
            files_created.append({"path": "css/style.css", "size": len(css_content), "kind": "text"})
            html_content = re.sub(r'<style[^>]*>.*?</style>', '<link rel="stylesheet" href="css/style.css">', html_content, flags=re.S | re.I)
        js_matches = re.findall(r'<script[^>]*>(.*?)</script>', html_content, re.S | re.I)
        js_matches = [m for m in js_matches if m.strip() and not m.strip().startswith('{')]
        if js_matches:
            js_content = '\n'.join(js_matches)
            os.makedirs(os.path.join(work_dir, "js"), exist_ok=True)
            with open(os.path.join(work_dir, "js", "app.js"), 'w', encoding='utf-8') as f:
                f.write(js_content)
            files_created.append({"path": "js/app.js", "size": len(js_content), "kind": "text"})

            def _strip_inline_script(m):
                attrs, body = m.group(1) or "", m.group(2) or ""
                if "src=" in attrs.lower() or body.strip().startswith('{'):
                    return m.group(0)
                return ""
            html_content = re.sub(r'<script([^>]*)>(.*?)</script>', _strip_inline_script,
                                  html_content, flags=re.S | re.I)

        has_css = os.path.isfile(os.path.join(work_dir, "css", "style.css"))
        has_js = os.path.isfile(os.path.join(work_dir, "js", "app.js"))
        if has_css and "css/style.css" not in html_content:
            link = '<link rel="stylesheet" href="css/style.css">'
            html_content = html_content.replace("</head>", link + "\n</head>", 1) \
                if "</head>" in html_content else link + "\n" + html_content
        if has_js and "js/app.js" not in html_content:
            tag = '<script src="js/app.js"></script>'
            html_content = html_content.replace("</body>", tag + "\n</body>", 1) \
                if "</body>" in html_content else html_content + "\n" + tag

        # схлопнуть ДУБЛИ подключений (модель иногда пишет <link>/<script> на один файл дважды)
        def _dedup_tag(html, pattern):
            seen_one = [False]

            def keep_first(m):
                if seen_one[0]:
                    return ""
                seen_one[0] = True
                return m.group(0)
            return re.sub(pattern, keep_first, html, flags=re.I)
        html_content = _dedup_tag(html_content, r'<link[^>]+href=["\']css/style\.css["\'][^>]*>\s*')
        html_content = _dedup_tag(html_content, r'<script[^>]+src=["\']js/app\.js["\'][^>]*>\s*</script>\s*')

        with open(index_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        for fc in files_created:
            if fc['path'] == 'index.html':
                fc['size'] = len(html_content)

    seen_paths, uniq = set(), []
    for fc in files_created:
        if fc['path'] not in seen_paths:
            seen_paths.add(fc['path'])
            fp = os.path.join(work_dir, fc['path'])
            if os.path.isfile(fp):
                fc['size'] = os.path.getsize(fp)
            uniq.append(fc)
    return uniq


def _extract_block(text, langs=("html", "css", "javascript", "js")):
    """Достать первый fenced-блок нужного языка; иначе снять любые ``` ; иначе вернуть как есть."""
    import re
    m = re.search(r"```(?:%s)?\s*\n(.*?)```" % "|".join(langs), text or "", re.S | re.I)
    if m:
        return m.group(1).strip()
    return re.sub(r"^```[a-z]*\s*|\s*```$", "", (text or "").strip(), flags=re.I).strip()


def _gen_multipass(final_prompt, domain, skills_text, model, cfg, feedback="", is_game=False):
    """МНОГОПРОХОДНАЯ генерация ПО ФАЙЛАМ: index.html → css/style.css → js/app.js, каждый со СВОИМ
    полным бюджетом токенов (против обрыва). HTML передаётся контекстом в CSS/JS для связности.
    is_game=True → JS-проход получает ИГРОВОЙ системный промпт (полная рабочая механика).
    Возвращает (answer-блоб в FILE-формате для _answer_to_files, tokens)."""
    fb = ("\n\nОБЯЗАТЕЛЬНО исправь замечания ревьюера предыдущей версии: " + feedback) if feedback else ""
    tokens = 0

    def call(system, user, max_tok):
        nonlocal tokens
        r = providers.chat(model, [{"role": "system", "content": system},
                                   {"role": "user", "content": user}],
                           max_tokens=max_tok, temperature=0.3, cfg=cfg, timeout=300)
        tokens += (r.get("usage", {}) or {}).get("total_tokens", 0)
        return r["text"]

    # Проход 1 — ПОЛНЫЙ index.html
    if is_game:
        html_sys = (f"Ты — expert game developer. Домен: игра.\n"
                    "СГЕНЕРИРУЙ ТОЛЬКО index.html для браузерной игры: разметка игрового поля/канваса, "
                    "табло счёта, кнопка рестарта, подсказка управления. Осмысленные id (#board/#canvas, "
                    "#score, #restart) — на них завяжется JS. Подключи <link href=\"css/style.css\"> и "
                    "<script src=\"js/app.js\"></script> перед </body>. Верни ОДИН блок ```html```.")
    else:
        html_sys = (f"Ты — expert front-end developer. Домен: {domain}.\n"
                    f"Релевантные навыки:\n{skills_text}\n\n"
                    "СГЕНЕРИРУЙ ТОЛЬКО ФАЙЛ index.html — полностью, до конца, со ВСЕМИ заявленными секциями.\n"
                    "Правила: семантический HTML5; для КАЖДОЙ секции/элемента осмысленные class/id (их будут "
                    "стилизовать и оживлять); подключи <link rel=stylesheet href=\"css/style.css\"> в <head> и "
                    "<script src=\"js/app.js\"></script> перед </body>; внешние либы — через CDN. НЕ пиши CSS/JS "
                    "инлайн (кроме мелких SVG). НЕ добавляй незапрошенных секций. Верни ОДИН блок ```html``` и всё.")
    html = _extract_block(call(html_sys, final_prompt + fb, PER_FILE_MAX_TOKENS), ("html",))

    # Проход 2 — ПОЛНЫЙ CSS под этот HTML
    css_sys = ("Ты — expert CSS-разработчик. Дан HTML-файл. Сгенерируй ТОЛЬКО css/style.css — полностью, "
               "покрывая КАЖДУЮ секцию и класс из HTML (никаких пропущенных секций). CSS-переменные, "
               "flexbox/grid, адаптивность (@media), hover/переходы, аккуратная типографика и отступы. "
               "Верни ОДИН блок ```css``` и всё, без пояснений.")
    css = _extract_block(call(css_sys, "HTML проекта:\n" + html[:16000], PER_FILE_MAX_TOKENS), ("css",))

    # Проход 3 — JS
    if is_game:
        js_sys = (
            "Ты — expert game developer. Дан HTML игры. Сгенерируй ТОЛЬКО js/app.js — ПОЛНОСТЬЮ РАБОЧУЮ игру.\n"
            "ОБЯЗАТЕЛЬНО:\n"
            "1) Инициализация СРАЗУ при загрузке (DOMContentLoaded): создать НАЧАЛЬНОЕ состояние игры "
            "(поле/плитки/герой видны сразу, а не пустой экран).\n"
            "2) ПОЛНАЯ игровая механика по правилам игры: ходы, слияния/столкновения, спавн, подсчёт очков.\n"
            "3) Управление: обработчики клавиш (keydown стрелки/WASD) и/или мыши; кнопка рестарта сбрасывает игру.\n"
            "4) Условия конца игры (победа/поражение) и корректный рендер каждого хода.\n"
            "5) Ссылайся ТОЛЬКО на существующие в HTML id. Никаких фреймворков, чистый JS. Код ЗАВЕРШЁН, без «...».\n"
            "Верни ОДИН блок ```javascript``` — вся логика целиком.")
    else:
        js_sys = ("Ты — expert JS-разработчик. Дан HTML-файл. Сгенерируй ТОЛЬКО js/app.js для нужной "
                  "интерактивности (обработчики, простое состояние, никаких фреймворков). Ссылайся ТОЛЬКО на "
                  "существующие в HTML id/class. Если интерактив не нужен — верни пустой блок. "
                  "Верни ОДИН блок ```javascript``` и всё.")
    js = _extract_block(call(js_sys, "HTML проекта:\n" + html[:16000], PER_FILE_MAX_TOKENS), ("javascript", "js"))

    parts = ["```html\n<!-- FILE: index.html -->\n%s\n```" % html,
             "```css\n/* FILE: css/style.css */\n%s\n```" % css]
    if js and len(js.strip()) > 10:
        parts.append("```javascript\n// FILE: js/app.js\n%s\n```" % js)
    return "\n\n".join(parts), tokens


def _single_shot_system(domain, skills_text):
    """Системный промпт для ОДНОШОТА (простые задачи): все файлы в одном ответе с FILE-маркерами."""
    return f"""Ты — expert full-stack developer. СОЗДАЙ ПОЛНЫЙ ВЕБ-ПРОЕКТ.

Домен: {domain}. Скиллы:\n{skills_text}

КРИТИЧЕСКИ ВАЖНО — СТРУКТУРА ПРОЕКТА:
Обязательные файлы:
1. index.html — ГЛАВНЫЙ ФАЙЛ (без него проект не работает!)
2. css/style.css — стили
3. js/app.js — логика

Для каждого файла используй отдельный блок кода:
```html
<!-- FILE: index.html -->
<!DOCTYPE html>...
```

```css
/* FILE: css/style.css */
body {{...}}
```

```javascript
// FILE: js/app.js
const app = {{...}}
```

ТРЕБОВАНИЯ:
- index.html ОБЯЗАТЕЛЕН — это точка входа проекта
- CSS: переменные, flexbox/grid, адаптивность
- JS: модульная структура, обработка событий
- Для графиков: Chart.js CDN в index.html
- Минимум 3 файла (html + css + js)
- Код должен быть ЧИТАЕМЫМ и ПОДДЕРЖИВАЕМЫМ
- НЕ пиши markdown-описания — только код

ЖЁСТКИЕ ПРАВИЛА КАЧЕСТВА (иначе результат забракует агент-ревьюер):
- ЗАВЕРШЁННОСТЬ: выдай ПОЛНЫЙ код каждого файла до конца. НЕ обрывай на середине, без «...».
- РОВНО то, что просили: НЕ добавляй незапрошенные фичи (корзину, лишние модалки, страницы).
- ЦЕЛОСТНОСТЬ: каждый id/класс, на который ссылается JS или CSS, ДОЛЖЕН существовать в HTML,
  и наоборот — не ссылайся на несуществующие элементы.
- СВЯЗНОСТЬ: index.html подключает css/style.css (<link>) и js/app.js (<script src>) — обязательно.
- Каждая заявленная в задаче секция/форма/кнопка РЕАЛЬНО присутствует и рабочая."""


def _produce_files(final_prompt, domain, skills_text, single_system, model, cfg, work_dir,
                   feedback, complex_site, is_game):
    """ОДИН проход генерации → файлы в work_dir. Диспетчер режимов:
    сложный сайт/игра → многопроход по файлам (полный бюджет на каждый);
    простая задача → одношот (все файлы в одном ответе). -> (files_created, tokens, answer)."""
    if complex_site:
        answer, tok = _gen_multipass(final_prompt, domain, skills_text, model, cfg,
                                     feedback, is_game=is_game)
    else:
        msgs = [{"role": "system", "content": single_system},
                {"role": "user", "content": final_prompt}]
        if feedback:
            msgs.append({"role": "user", "content":
                "Предыдущая версия ЗАБРАКОВАНА агентом-ревьюером. Исправь ВСЕ замечания и "
                "верни ПОЛНЫЙ код проекта заново (все файлы целиком):\n" + feedback})
        r = providers.chat(model, msgs, max_tokens=GEN_MAX_TOKENS, temperature=0.3, cfg=cfg, timeout=300)
        answer, tok = r["text"], (r.get("usage", {}) or {}).get("total_tokens", 0)
    return _answer_to_files(answer, work_dir), tok, answer


@app.post("/api/generate", response_model=GenerateResponse)
async def generate_code(req: GenerateRequest):
    """Async-обёртка: тяжёлый синхронный конвейер выносится в поток, чтобы НЕ блокировать
    event loop на 30–300 с (находка ревью). Параллельные запросы больше не стоят в очереди."""
    return await asyncio.to_thread(_generate_sync, req)


def _generate_sync(req: GenerateRequest):
    """Полный pipeline: PSQ → скиллы → генерация кода LLM → АГЕНТНАЯ ПРОВЕРКА → (ремонт-цикл до
    результата) → архив. Веб-версия PSQ: без метрики KSCR — результат проверяют агенты."""
    try:
        _gc_previews()                       # сборка мусора старых превью/архивов (анти-утечка диска)
        # Генерацию ведёт code-специалист qwen3-coder-480b — идеальный для кода, стабильный
        # PASS 6/6 за 1 цикл (~30с). Дешёвая gpt-oss-20b периодически недоступна на шлюзе (503),
        # средние qwen3-next-80b/deepseek-v3.2 нестабильны — поэтому дефолт на надёжного кодера.
        # Конвейер PSQ+скиллы+ревьюер+ремонт-цикл делает результат воспроизводимым на разных
        # моделях (независимость от модели). Переопределяется req.model или env SPT_GEN_MODEL.
        model = req.model or os.environ.get("SPT_GEN_MODEL") or "openai/qwen3-coder-480b-a35b-instruct-maas"
        tier = req.tier
        work_dir = tempfile.mkdtemp(prefix="spt_gen_")

        try:
            # 1. Router + skills (LLM-based ranking)
            from superprompt_cli import config as spt_config
            cfg = spt_config.load()
            domain, conf, _ = router.classify_conf(req.prompt)
            
            # Используем LLM-based ранжирование для выбора скиллов
            skills = webskills.rank(req.prompt, k=5, model=settings.judge_model, cfg=cfg)

            # 2. PSQ gate с интеграцией скиллов (3 cycles to ensure PSQ >= 0.8)
            from superprompt_cli import psq as spt_psq
            final_prompt, psq_before, psq_after = spt_psq.gate(
                req.prompt, settings.judge_model, model,
                max_cycles=3, cfg=cfg, log=lambda m: None)

            # 3. Системный промпт одношота (для простых задач); сложное/игра идут многопроходом
            skills_text = "\n".join(f"### {s['name']}\n{s['text'][:500]}" for s in skills)
            system = _single_shot_system(domain, skills_text)

            # 4-6. РЕМОНТ-ЦИКЛ ДО РЕЗУЛЬТАТА: генерация → сборка файлов → агентная проверка.
            #      FAIL → регенерация с замечаниями ревьюера (планка: до PASS, максимум 3 прохода).
            #      Сложный сайт (длинный промт / много секций) → МНОГОПРОХОДНАЯ генерация по файлам
            #      (каждый со своим бюджетом токенов — не обрезается); простой → быстрый одношот.
            base_user = final_prompt
            # игра → всегда многопроход с ИГРОВЫМ JS-промптом (полная рабочая механика)
            is_game = bool(re.search(r"\bигр\w*|\bgame\b|змейк|тетрис|арканоид|платформер|пинг-понг|"
                                     r"пинпонг|2048|судоку|викторин|крестики|сапёр|snake|tetris|arkanoid|"
                                     r"puzzle|канвас-игр|игровое поле", final_prompt, re.I))
            complex_site = (is_game or len(final_prompt) > MULTIPASS_PROMPT_CHARS or
                            len(re.findall(r"секц|блок|hero|тариф|отзыв|футер|прайс|галере|раздел|"
                                           r"section|pricing|testimonial|footer|feature",
                                           final_prompt, re.I)) >= 3)
            build_feedback = ""
            answer, files_created, verification, tokens_used = "", [], None, 0
            for _cycle in range(MAX_BUILD_CYCLES):
                if _cycle > 0:
                    work_dir = tempfile.mkdtemp(prefix="spt_gen_")   # свежая папка на повтор
                files_created, tok, answer = _produce_files(
                    base_user, domain, skills_text, system, model, cfg, work_dir,
                    build_feedback, complex_site, is_game)
                tokens_used += tok
                verification = _verify_result(work_dir, files_created, req.prompt, model, cfg)
                verification["cycles"] = _cycle + 1
                if verification.get("verdict") == "PASS":
                    break
                build_feedback = "; ".join(verification.get("issues") or []) or verification.get("review", "")

            # 5.6 Generate launch.bat for Windows
            has_index = any(f['path'] == 'index.html' for f in files_created)
            if has_index:
                bat_content = """@echo off
title SuperPromt Project
REM === Auto-generated by SuperPromt ===
REM Double-click this file to open the site

REM Try to find and open index.html
if exist "%~dp0index.html" (
    start "" "%~dp0index.html"
    goto :end
)
if exist "%~dp0frontend\\index.html" (
    start "" "%~dp0frontend\\index.html"
    goto :end
)

echo ERROR: index.html not found!
echo Make sure all files are in the same folder.
pause
:end
"""
                bat_path = os.path.join(work_dir, "launch.bat")
                with open(bat_path, 'w', encoding='utf-8') as f:
                    f.write(bat_content)
                files_created.append({"path": "launch.bat", "size": len(bat_content), "kind": "text"})

            # 5.6 Generate README.md with instructions
            readme_content = f"""# SuperPromt Project

Generated by SuperPromt Pipeline (PSQ: {psq_before['psq'] if psq_before else '?'} → {psq_after['psq'] if psq_after else '?'})

## Quick Start
1. Extract ZIP archive
2. Double-click `launch.bat` (Windows)
3. Or open `index.html` in browser

## Structure
"""
            for f in files_created:
                if f['path'] != 'launch.bat':
                    readme_content += f"- `{f['path']}` ({f['size']} bytes)\n"
            
            readme_path = os.path.join(work_dir, "README.md")
            with open(readme_path, 'w', encoding='utf-8') as f:
                f.write(readme_content)
            files_created.append({"path": "README.md", "size": len(readme_content), "kind": "text"})

            # 6. Create ZIP archive
            gen_id = uuid.uuid4().hex[:8]
            archive_name = f"superpromt_{gen_id}.zip"
            archive_path = os.path.join(UPLOAD_DIR, archive_name)
            with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, fnames in os.walk(work_dir):
                    dirs[:] = [d for d in dirs if not d.startswith('.')]
                    for fname in fnames:
                        fpath = os.path.join(root, fname)
                        arcname = os.path.relpath(fpath, work_dir)
                        zf.write(fpath, arcname)

            # 6.1 Копия файлов в served-каталог для ЖИВОГО ПРЕВЬЮ в iframe (не только скачивание zip)
            preview_url = None
            if any(f["path"] == "index.html" for f in files_created):
                pdir = os.path.join(PREVIEW_DIR, gen_id)
                shutil.copytree(work_dir, pdir, dirs_exist_ok=True)
                preview_url = f"/api/preview/{gen_id}/index.html"

            # (агентная проверка уже выполнена в ремонт-цикле выше; verification/tokens_used готовы)
            psq_b = psq_before["psq"] if psq_before else None
            psq_a = psq_after["psq"] if psq_after else None

            # Record to memory (daily log)
            memory.record("task", {
                "task": req.prompt[:200],
                "domain": domain,
                "tier": tier,
                "model": model,
                "psq": f"{psq_b:.2f} → {psq_a:.2f}" if psq_b and psq_a else None,
                "steps": 1,
                "tool_errors": 0,
                "tool_calls": 0,
                "tokens": tokens_used,
                "files": len(files_created),
            })

            cost_est = _estimate_cost(model, tokens_used)
            return GenerateResponse(
                answer=answer,
                passport={
                    "домен": domain, "тир": tier, "модель": model,
                    "PSQ": f"{psq_b:.2f} → {psq_a:.2f}" if psq_b and psq_a else None,
                    "токены": tokens_used,
                },
                journal=f"PSQ: {psq_b} → {psq_a}\nSkills: {', '.join(s['name'] for s in skills)}\nFiles: {len(files_created)}",
                psq_before=psq_b,
                psq_after=psq_a,
                domain=domain,
                skills_used=[s['name'] for s in skills],
                files=files_created,
                archive_url=f"/api/download/{archive_name}",
                preview_url=preview_url,
                verification=verification,
                tokens=tokens_used,
                cost_usd=cost_est,
            )
        finally:
            pass

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Ошибка генерации: {str(e)[:300]}")

@app.get("/api/download/{filename}")
async def download_archive(filename: str):
    """Скачать ZIP-архив с результатом генерации."""
    safe_name = os.path.basename(filename)
    path = os.path.join(UPLOAD_DIR, safe_name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Архив не найден")
    return FileResponse(path, filename=safe_name, media_type="application/zip")

@app.get("/api/preview/{gen_id}/{path:path}")
async def preview_generated(gen_id: str, path: str):
    """Живое превью сгенерированного проекта в iframe. Отдаёт файлы из preview/<gen_id>/
    ТОЛЬКО внутри этого каталога (анти path-traversal)."""
    gen_id = os.path.basename(gen_id)                 # без './..'
    base = os.path.realpath(os.path.join(PREVIEW_DIR, gen_id))
    full = os.path.realpath(os.path.join(base, path or "index.html"))
    if not (full == base or full.startswith(base + os.sep)) or not os.path.isfile(full):
        raise HTTPException(status_code=404, detail="not_found")
    resp = FileResponse(full)
    resp.headers["Cache-Control"] = "no-store"        # правки видны сразу при перезагрузке iframe
    return resp


def _preview_base(gen_id):
    gen_id = os.path.basename(gen_id or "")
    base = os.path.realpath(os.path.join(PREVIEW_DIR, gen_id))
    return gen_id, base


@app.get("/api/edit/{gen_id}")
async def edit_files(gen_id: str):
    """Вернуть редактируемые текстовые файлы проекта (html/css/js) для правки в UI."""
    gen_id, base = _preview_base(gen_id)
    if not os.path.isdir(base):
        raise HTTPException(status_code=404, detail="not_found")
    out = []
    for root, _dirs, fnames in os.walk(base):
        for fn in sorted(fnames):
            ext = fn.rsplit(".", 1)[-1].lower()
            if ext not in ("html", "css", "js"):
                continue
            fp = os.path.join(root, fn)
            rel = os.path.relpath(fp, base).replace(os.sep, "/")
            try:
                out.append({"path": rel, "content": open(fp, encoding="utf-8").read()})
            except OSError:
                pass
    out.sort(key=lambda f: (0 if f["path"] == "index.html" else 1, f["path"]))
    return {"gen_id": gen_id, "files": out}


class EditSaveRequest(BaseModel):
    files: Dict[str, str] = {}       # {относительный_путь: новое_содержимое}


@app.post("/api/edit/{gen_id}")
async def save_edits(gen_id: str, req: EditSaveRequest):
    """Сохранить правки пользователя в preview/<gen_id>/ (внутри каталога) и пересобрать ZIP.
    -> {ok, archive_url}. Позволяет 'посмотреть и подправить результат' прямо в браузере."""
    gen_id, base = _preview_base(gen_id)
    if not os.path.isdir(base):
        raise HTTPException(status_code=404, detail="not_found")
    saved = 0
    for rel, content in (req.files or {}).items():
        ext = rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
        if ext not in ("html", "css", "js"):
            continue                                  # править можно только текстовые исходники
        full = os.path.realpath(os.path.join(base, rel))
        if not (full.startswith(base + os.sep)) or "\0" in rel:
            continue                                  # анти path-traversal
        try:
            with open(full, "w", encoding="utf-8") as f:
                f.write(content)
            saved += 1
        except OSError:
            pass
    # пересобрать ZIP архива, чтобы скачивание отдавало правленую версию
    archive_name = f"superpromt_{gen_id}.zip"
    archive_path = os.path.join(UPLOAD_DIR, archive_name)
    try:
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, fnames in os.walk(base):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for fn in fnames:
                    fp = os.path.join(root, fn)
                    zf.write(fp, os.path.relpath(fp, base))
    except OSError:
        pass
    return {"ok": True, "saved": saved, "archive_url": f"/api/download/{archive_name}"}

# --- Конкурсный режим: PSQ + Skills (веб-версия — БЕЗ метрики KSCR) ---

@app.post("/api/evaluate")
async def evaluate_competition(req: GenerateRequest):
    """Async-обёртка: несколько sync-вызовов LLM → в поток (не блокировать event loop).
    Примечание: в текущем фронте не используется; веб работает без метрики KSCR."""
    return await asyncio.to_thread(_evaluate_sync, req)


def _evaluate_sync(req: GenerateRequest):
    """Оценка задачи: PSQ + подбор скиллов. Веб-версия PSQ БЕЗ метрики KSCR
    (правдивость результата проверяют агенты в /api/generate, а не KSCR-гейт)."""
    try:
        model = req.model or settings.judge_model
        from superprompt_cli import config as spt_config
        cfg = spt_config.load()
        
        # 1. Router classification
        domain, conf, _ = router.classify_conf(req.prompt)
        
        # 2. LLM-based skill ranking
        skills = webskills.rank(req.prompt, k=7, model=model, cfg=cfg)
        
        # 3. PSQ evaluation
        from superprompt_cli import psq as spt_psq
        psq_result = spt_psq.score(req.prompt, model, cfg=cfg)
        
        # 4. PSQ gate with repair
        final_prompt, psq_before, psq_after = spt_psq.gate(
            req.prompt, model, model,
            max_cycles=3, cfg=cfg, log=lambda m: None)
        
        # 5. Combined evaluation
        combined = psq_skills.score_with_skills(
            final_prompt, req.prompt, model, skills=skills, cfg=cfg)
        
        return {
            "task": req.prompt,
            "final_prompt": final_prompt,
            "domain": domain,
            "confidence": conf,
            "psq_before": psq_before["psq"] if psq_before else None,
            "psq_after": psq_after["psq"] if psq_after else None,
            "psq_details": psq_after,
            "skills": [{"name": s["name"], "description": s["text"][:200]} for s in skills],
            "skills_count": len(skills),
            "combined_score": combined,
            "model": model,
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Ошибка оценки: {str(e)[:300]}")

@app.get("/api/skills/rank")
async def rank_skills(task: str, k: int = 5):
    """LLM-based ранжирование скиллов для задачи."""
    try:
        from superprompt_cli import config as spt_config
        cfg = spt_config.load()
        skills = await asyncio.to_thread(webskills.rank, task, k, settings.judge_model, cfg)
        return {
            "task": task,
            "skills": [{"name": s["name"], "description": s["text"][:200]} for s in skills],
            "count": len(skills),
            "model": settings.judge_model,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка ранжирования: {str(e)[:200]}")

# --- Memory System (3 уровня памяти) ---

@app.get("/api/memory", response_model=MemoryResponse)
async def get_memory():
    """Получить состояние памяти: ядро + дневные события + сессии."""
    try:
        # Core memory (persistent)
        core = memory.load_core()
        
        # Daily events (short-term → long-term)
        events_text = memory.recent_events(days=7, limit_chars=50000)
        events = []
        for line in events_text.strip().split("\n"):
            if line.strip():
                try:
                    ev = json.loads(line)
                    events.append(MemoryEvent(
                        ts=ev.get("ts", ""),
                        event=ev.get("event", ""),
                        task=ev.get("task"),
                        domain=ev.get("domain"),
                        psq=ev.get("psq"),
                        steps=ev.get("steps"),
                        tokens=ev.get("tokens"),
                    ))
                except (json.JSONDecodeError, Exception):
                    pass
        
        # Sessions count
        try:
            session_list = memory.recent_events(days=30)
            sessions_count = len(set(
                line.split('"event":')[0] for line in session_list.split("\n")
                if '"event":' in line
            ))
        except Exception:
            sessions_count = 0
        
        return MemoryResponse(
            core=core,
            core_size=len(core),
            daily_events=events[-50:],  # последние 50 событий
            sessions_count=sessions_count,
            total_events=len(events),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка чтения памяти: {str(e)[:200]}")

@app.post("/api/distill", response_model=DistillResponse)
async def distill_memory():
    """Deep Dream: консолидация дневных логов в ядро памяти."""
    try:
        model = settings.judge_model
        cfg = None
        try:
            from superprompt_cli import config as spt_config
            cfg = spt_config.load()
        except Exception:
            pass
        
        result = memory.distill(model, cfg=cfg, days=7)
        
        if result:
            core = memory.load_core()
            return DistillResponse(
                status="ok",
                core_size=len(core),
                message=f"Ядро обновлено ({len(core)} символов). Дневные логи сконсолидированы."
            )
        else:
            return DistillResponse(
                status="empty",
                core_size=0,
                message="Нет событий для дистилляции. Сначала выполните несколько задач."
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка дистилляции: {str(e)[:200]}")

@app.get("/api/memory/core")
async def get_core_memory():
    """Получить только ядро памяти (для отладки)."""
    return {"core": memory.load_core(), "size": len(memory.load_core())}

@app.delete("/api/memory")
async def clear_memory():
    """Очистить дневную память (ядро не трогаем)."""
    try:
        daily_dir = os.path.join(memory.MEM_DIR, "daily")
        if os.path.isdir(daily_dir):
            for f in os.listdir(daily_dir):
                if f.endswith(".jsonl"):
                    os.remove(os.path.join(daily_dir, f))
        return {"status": "ok", "message": "Дневная память очищена"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)[:200]}")

# --- Загрузка файлов (прикрепление к задаче) ---
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
PREVIEW_DIR = os.path.join(UPLOAD_DIR, "preview")   # served-копии сгенерированных проектов (iframe-превью)
os.makedirs(PREVIEW_DIR, exist_ok=True)


def _gc_previews():
    """Сборка мусора: удалить served-превью и архивы старше PREVIEW_TTL_SEC.
    Иначе PREVIEW_DIR/UPLOAD_DIR растут без границ (находка ревью). Зовётся при генерации."""
    cutoff = time.time() - PREVIEW_TTL_SEC
    try:
        for name in os.listdir(PREVIEW_DIR):
            p = os.path.join(PREVIEW_DIR, name)
            try:
                if os.path.isdir(p) and os.path.getmtime(p) < cutoff:
                    shutil.rmtree(p, ignore_errors=True)
            except OSError:
                pass
        for name in os.listdir(UPLOAD_DIR):
            if name.startswith("superpromt_") and name.endswith(".zip"):
                p = os.path.join(UPLOAD_DIR, name)
                try:
                    if os.path.getmtime(p) < cutoff:
                        os.remove(p)
                except OSError:
                    pass
    except OSError:
        pass
MAX_FILE_SIZE = 10 * 1024 * 1024   # 10 МБ на файл
MAX_FILES = 10

ALLOWED_UPLOAD_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".txt", ".md",
                      ".pdf", ".json", ".csv", ".py", ".js", ".html", ".docx"}

@app.post("/api/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    """Приём прикреплённых файлов/фото. Сохраняет с безопасными uuid-именами, возвращает метаданные."""
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=422, detail="Слишком много файлов (максимум %d)" % MAX_FILES)
    saved = []
    for f in files:
        ext = os.path.splitext(f.filename or "")[1].lower()[:12]
        if ext not in ALLOWED_UPLOAD_EXT:
            raise HTTPException(status_code=422, detail="Недопустимый тип файла '%s'" % ext)
        # читаем чанками с ранней отсечкой — не держим >10 МБ в памяти
        chunks, total = [], 0
        while True:
            chunk = await f.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_FILE_SIZE:
                raise HTTPException(status_code=422, detail="Файл '%s' превышает 10 МБ" % (f.filename or ""))
            chunks.append(chunk)
        fid = uuid.uuid4().hex
        with open(os.path.join(UPLOAD_DIR, fid + ext), "wb") as out:
            out.write(b"".join(chunks))
        saved.append({"id": fid, "name": os.path.basename(f.filename or (fid + ext)),
                      "size": total, "content_type": f.content_type or "application/octet-stream"})
    return {"files": saved}

# Монтируем статику в самом конце
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

    @app.get("/")
    async def read_index():
        # no-store: браузер НЕ кеширует HTML → после деплоя пользователь сразу видит новую версию
        # (иначе стойкий кеш отдаёт старую страницу — «тоже самое» после исправлений)
        return FileResponse(os.path.join(frontend_path, "index.html"),
                            headers={"Cache-Control": "no-store, must-revalidate"})

if __name__ == "__main__":
    import uvicorn
    # proxy_headers=False: не доверять клиентскому X-Forwarded-For
    # (иначе rate-limit обходится ротацией заголовка)
    # SPT_HOST/SPT_PORT: ufw блокирует прямой 8000 — в проде слушаем 127.0.0.1:8001,
    # наружу порт 8000 публикует docker-socat (обходит ufw, как остальные docker-порты)
    uvicorn.run(app, host=os.environ.get("SPT_HOST", "0.0.0.0"),
                port=int(os.environ.get("SPT_PORT", "8000")), proxy_headers=False)
