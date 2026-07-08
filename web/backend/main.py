import os
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
    # Формат ядра: "провайдер/модель" (см. superprompt_cli/providers.py)
    judge_model: str = "openai/gpt-4o"
    repair_model: str = "openai/gpt-4o"
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
        
    return await call_next(request)

# --- Security Headers ---
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    # CSP: разрешаем инлайновые скрипты/стили для совместимости с фронтом
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:;"
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
        has_llm = any(os.environ.get(k) for k in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"])
        if not has_llm:
            raise HTTPException(
                status_code=503,
                detail="Улучшение промта недоступно: LLM-провайдер не настроен."
            )
        
        res = psq.repair(req.prompt, settings.repair_model)
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
    has_llm = any(os.environ.get(k) for k in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"])
    return {
        "mode": "deep" if has_llm else "fast",
        "llm_configured": has_llm
    }

@app.post("/api/psq", response_model=PSQResponse)
async def calculate_psq(req: PSQRequest):
    try:
        # Проверяем режим (для истории)
        has_llm = any(os.environ.get(k) for k in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"])
        mode = "deep" if has_llm else "fast"

        # 1. Детерминированный пре-скрининг (не требует LLM)
        res = psq.prescreen(req.prompt)
        if res:
            # Преобразуем флаги из кортежей в объекты
            flags_raw = res["flags"]
            res["flags"] = [{"name": f[0], "count": f[1]} for f in res["flags"]]
            storage.add_entry(req.prompt, res["psq"], res["gaming"], res["prescreen"], mode, res["flags"])
            return res

        # 2. Если пре-скрининг не дал результата, нужен судья
        try:
            res = psq.score(req.prompt, settings.judge_model)
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
        
        # LLM-based ranking with fallback to TF-IDF
        try:
            from superprompt_cli import config as spt_config
            cfg = spt_config.load()
            skills_data = webskills.rank(task, k=10, model=settings.judge_model, cfg=cfg)
        except Exception:
            skills_data = webskills.rank(task, k=10)
        
        # Добавляем lean-code если нужно, как это делает router.pick_skills
        skills = []
        if domain in ("code", "mixed"):
            skills.append(SkillItem(name="lean-code(builtin)", text=router.PONYTAIL_RULES))
        
        for s in skills_data:
            skills.append(SkillItem(name=s["name"], text=s["text"]))
            
        return {
            "domain": domain,
            "confidence": confidence,
            "skills": skills[:4]
        }
    except Exception:
        raise HTTPException(status_code=500, detail="Внутренняя ошибка при подборе скиллов.")

@app.post("/api/generate", response_model=GenerateResponse)
async def generate_code(req: GenerateRequest):
    """Полный pipeline: PSQ → ремонт → скиллы → генерация кода LLM → архив."""
    try:
        model = req.model or settings.judge_model
        tier = req.tier
        work_dir = tempfile.mkdtemp(prefix="spt_gen_")

        try:
            # 1. Router + skills
            from superprompt_cli import config as spt_config
            cfg = spt_config.load()
            domain, conf, _ = router.classify_conf(req.prompt)
            skills = webskills.rank(req.prompt, k=5)

            # 2. PSQ gate (3 cycles to ensure PSQ >= 0.8)
            from superprompt_cli import psq as spt_psq
            final_prompt, psq_before, psq_after = spt_psq.gate(
                req.prompt, settings.judge_model, model,
                max_cycles=3, cfg=cfg, log=lambda m: None)

            # 3. Build system prompt with skills
            skills_text = "\n".join(f"### {s['name']}\n{s['text'][:500]}" for s in skills)
            system = f"""Ты — expert full-stack developer. СОЗДАЙ ПОЛНЫЙ ВЕБ-ПРОЕКТ.

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
- НЕ пиши markdown-описания — только код"""

            # 4. Generate code via LLM
            r = providers.chat(model, [
                {"role": "system", "content": system},
                {"role": "user", "content": final_prompt}
            ], max_tokens=16000, temperature=0.3, cfg=cfg, timeout=300)

            answer = r["text"]

            # 5. Extract code blocks from answer
            import re
            
            # Pattern 1: FILE: marker in code blocks
            file_blocks = re.findall(r'```(?:html|css|javascript|js|python)?\s*\n<!--\s*FILE:\s*(\S+)\s*-->|/\*\s*FILE:\s*(\S+)\s*\*/|//\s*FILE:\s*(\S+)', answer, re.I)
            
            # Pattern 2: Standard code blocks
            code_blocks = re.findall(r'```(?:html|css|javascript|js|python)?\s*\n(.*?)```', answer, re.S)
            
            files_created = []
            
            if file_blocks:
                # Extract files with FILE: markers
                for match in re.finditer(r'```(?:html|css|javascript|js|python)?\s*\n(?:<!--\s*FILE:\s*(\S+)\s*-->|/\*\s*FILE:\s*(\S+)\s*\*/|//\s*FILE:\s*(\S+))\s*\n(.*?)```', answer, re.S | re.I):
                    fname = match.group(1) or match.group(2) or match.group(3)
                    content = match.group(4).strip()
                    if fname and content:
                        # Create directory structure
                        fpath = os.path.join(work_dir, fname)
                        os.makedirs(os.path.dirname(fpath), exist_ok=True)
                        with open(fpath, 'w', encoding='utf-8') as f:
                            f.write(content)
                        files_created.append({"path": fname, "size": len(content), "kind": "text"})
            
            if not files_created and code_blocks:
                # Fallback: extract standard code blocks
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
                # Last resort: save entire answer
                fpath = os.path.join(work_dir, "index.html")
                with open(fpath, 'w', encoding='utf-8') as f:
                    f.write(answer)
                files_created.append({"path": "index.html", "size": len(answer), "kind": "text"})

            # 6. Create ZIP archive
            archive_name = f"superpromt_{uuid.uuid4().hex[:8]}.zip"
            archive_path = os.path.join(UPLOAD_DIR, archive_name)
            with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, fnames in os.walk(work_dir):
                    dirs[:] = [d for d in dirs if not d.startswith('.')]
                    for fname in fnames:
                        fpath = os.path.join(root, fname)
                        arcname = os.path.relpath(fpath, work_dir)
                        zf.write(fpath, arcname)

            psq_b = psq_before["psq"] if psq_before else None
            psq_a = psq_after["psq"] if psq_after else None

            # Record to memory (daily log)
            tokens_used = r.get("usage", {}).get("total_tokens", 0)
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
        return FileResponse(os.path.join(frontend_path, "index.html"))

if __name__ == "__main__":
    import uvicorn
    # proxy_headers=False: не доверять клиентскому X-Forwarded-For
    # (иначе rate-limit обходится ротацией заголовка)
    uvicorn.run(app, host="0.0.0.0", port=8000, proxy_headers=False)
