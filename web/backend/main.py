import os
import sys
import time
from collections import defaultdict, deque
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

# Добавляем корень проекта в sys.path для импорта superprompt_cli
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, root_path)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # каталог бэкенда — для локальных модулей (storage)

import superprompt_cli.psq as psq
import superprompt_cli.router as router
import superprompt_cli.webskills as webskills
from storage import HistoryStorage

class Settings(BaseSettings):
    app_name: str = "SuperPromt API"
    debug: bool = False
    judge_model: str = "gpt-4o"  # Дефолтная модель для судьи
    repair_model: str = "gpt-4o"
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
        client_ip = request.client.host
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

class RepairRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=MAX_PROMPT_LENGTH)

class RepairResponse(BaseModel):
    improved_text: str

# --- Endpoints ---

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
             raise HTTPException(status_code=503, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))

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
            res["flags"] = [{"name": f[0], "count": f[1]} for f in res["flags"]]
            storage.add_entry(req.prompt, res["psq"], res["gaming"], res["prescreen"], mode)
            return res

        # 2. Если пре-скрининг не дал результата, нужен судья
        try:
            res = psq.score(req.prompt, settings.judge_model)
            # Преобразуем флаги
            res["flags"] = [{"name": f[0], "count": f[1]} for f in res["flags"]]
            storage.add_entry(req.prompt, res["psq"], res["gaming"], res.get("prescreen"), mode)
            return res
        except Exception as e:
            # Любая ошибка судьи (нет ключа/сети, неизвестный или ненастроенный провайдер) →
            # честный 503 «глубокая оценка недоступна», а не 500. Детерминированный
            # pre-скрининг при этом всегда работает без провайдера.
            raise HTTPException(
                status_code=503,
                detail="LLM-судья недоступен (провайдер не настроен, нет ключа или сети): "
                       + str(e)[:200]
                       + ". Детерминированный pre-скрининг работает без провайдера.",
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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

@app.delete("/api/history")
async def clear_history():
    storage.clear_history()
    return {"status": "ok"}

@app.get("/api/skills", response_model=SkillsResponse)
async def get_skills(task: str):
    try:
        domain, confidence, _ = router.classify_conf(task)
        skills_data = webskills.rank(task, k=3)
        
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Монтируем статику в самом конце
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

    @app.get("/")
    async def read_index():
        return FileResponse(os.path.join(frontend_path, "index.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
