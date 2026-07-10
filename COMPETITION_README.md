# SuperPromt — Конкурсный пакет

## Что сдаём

### 1. Продукт
**SuperPromt** — AI-инструмент для оценки и улучшения постановки задач с метрикой PSQ.

- Веб-интерфейс: `http://localhost:8000`
- CLI: `python3 -m superprompt_cli`
- Код: `6_SuperPromt_PSQ_Web/`

### 2. Ключевая фича: PSQ + Skills Integration

**Ранжирование скиллов через LLM-судью** (`webskills.py`):
- 21 скилл в каталоге (improved/ из PromtMaster + базовый пак)
- LLM выбирает 5-7 наиболее релевантных скиллов для задачи
- Приоритет: насыщенные методологии > технические > поддерживающие

**PSQ-гейт с ремонтом** (`psq.py`):
- Оценка промта по CSP-8 (8 критериев)
- Автоматический ремонт до PSQ >= 0.8
- 3 цикла ремонта при необходимости

**Комбинированная оценка** (`psq_with_skills.py`):
- PSQ + Skills = полная оценка задачи
- Skills используются в system prompt для генерации кода

### 3. API эндпоинты

| Эндпоинт | Описание |
|-----------|----------|
| `POST /api/evaluate` | Конкурсный режим: PSQ + Skills |
| `POST /api/generate` | Генерация кода с архивом |
| `POST /api/psq` | Оценка промта |
| `POST /api/repair` | Улучшение промта |
| `GET /api/skills` | Подбор скиллов |
| `GET /api/skills/rank` | LLM-based ранжирование |

### 4. Скиллы (21)

**Универсальные методологии:**
- designer-skills, knowledge-work, math-orchestr, frontend-design

**Топ-12 библиотеки:**
- paper-shaders, frontend-slides, lottie-animation, mermaid-diagrams
- writing-runbooks-2, automating-workspace-workflows
- onboarding-design-system-2, designing-operational-dashboards
- validating-environment-secrets, executing-development-workflows
- managing-git-dag-branches, writing-product-requirements-docs

**Базовый пак:**
- fastapi-backend, rest-api-design, sql-postgres, auth-jwt
- input-validation-security, docker-deploy, api-testing, express-node-backend

### 5. Как запустить

```bash
cd 6_SuperPromt_PSQ_Web/web/backend
export OPENAI_API_KEY=your_key
python3 main.py
# Открыть http://localhost:8000
```

### 6. Пример использования

```python
# Конкурсный режим
POST /api/evaluate
{
  "prompt": "Создай портфолио для фотографа",
  "tier": "mid",
  "model": "openai/grok-4.1-fast-non-reasoning"
}

# Результат
{
  "psq_before": 0.1,
  "psq_after": 0.95,
  "skills": ["frontend-design", "designer-skills", ...],
  "skills_count": 5,
  "domain": "code"
}
```
