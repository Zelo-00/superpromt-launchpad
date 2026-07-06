---
name: fastapi-backend
description: Бэкенд на FastAPI (Python): Pydantic-схемы, dependency injection, async, обработка ошибок, структура проекта. Для Python-сервисов и API.
user-invocable: true
---

## Когда использовать
Строишь Python-бэкенд/API на FastAPI.
## Структура
`app/{main.py, api/(routers), core/(config,security), models/, schemas/(pydantic), services/, db/}` — разделяй роутеры, бизнес-логику (services) и доступ к данным.
## Ключевые практики
- Схемы ввода/вывода — Pydantic v2 (`BaseModel`), отдельные `*Create`/`*Read`/`*Update`; response_model на эндпоинте.
- Зависимости через `Depends()` (сессия БД, текущий пользователь) — тестируемо и переиспользуемо.
- Async endpoints + async драйвер БД (asyncpg/SQLAlchemy 2.0 async) для I/O.
- Ошибки — `HTTPException` или кастомный exception handler → единый JSON.
- Конфиг — `pydantic-settings` из `.env` (не хардкод).
## Анти-паттерны
- Логика в роутере, синхронный I/O в async, секреты в коде, `dict` вместо Pydantic на границе.
## Чеклист
[ ] Pydantic-схемы in/out [ ] Depends для БД/аутентификации [ ] exception handler [ ] settings из env [ ] uvicorn+тесты
