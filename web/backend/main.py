import os
import sys
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

# Добавляем корень проекта в sys.path для импорта superprompt_cli
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from superprompt_cli import psq, router, webskills

class Settings(BaseSettings):
    app_name: str = "SuperPromt API"
    debug: bool = False
    judge_model: str = "gpt-4o"  # Дефолтная модель для судьи
    repair_model: str = "gpt-4o"
    
    class Config:
        env_file = ".env"

settings = Settings()
app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Static Files ---
frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../frontend"))

# Эндпоинты API должны быть объявлены ДО монтирования статики на корень

# --- Models ---

class PSQRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="Сырой текст задачи")

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

class RepairRequest(BaseModel):
    prompt: str = Field(..., min_length=1)

class RepairResponse(BaseModel):
    improved_text: str

# --- Endpoints ---

@app.post("/api/repair", response_model=RepairResponse)
async def repair_prompt(req: RepairRequest):
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
        # 1. Детерминированный пре-скрининг (не требует LLM)
        res = psq.prescreen(req.prompt)
        if res:
            # Преобразуем флаги из кортежей в объекты
            res["flags"] = [{"name": f[0], "count": f[1]} for f in res["flags"]]
            return res

        # 2. Если пре-скрининг не дал результата, нужен судья
        try:
            res = psq.score(req.prompt, settings.judge_model)
            # Преобразуем флаги
            res["flags"] = [{"name": f[0], "count": f[1]} for f in res["flags"]]
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
