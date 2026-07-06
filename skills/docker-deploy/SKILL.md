---
name: docker-deploy
description: Контейнеризация и деплой: Dockerfile (multi-stage), .dockerignore, env, healthcheck, compose. Для упаковки веб-сервиса.
user-invocable: true
---

## Когда использовать
Готовишь сервис к деплою/хостингу в контейнере.
## Ключевые практики
- Multi-stage Dockerfile: builder (сборка/зависимости) → тонкий runtime-образ (slim/alpine/distroless). Не рут-пользователь.
- `.dockerignore` (node_modules, .git, .env, tests) — меньше образ и нет утечки секретов.
- Порт из `$PORT`, конфиг из env (не хардкод), `HEALTHCHECK`.
- Пин версий базового образа и зависимостей. Кэшируй слои: сначала манифест зависимостей, потом код.
- docker-compose для локального стенда (app+db+redis).
## Анти-паттерны
- `.env` в образе, запуск от root, `latest`-базовый образ, копирование всего контекста без ignore.
## Чеклист
[ ] multi-stage+slim [ ] non-root [ ] .dockerignore без секретов [ ] $PORT+env [ ] healthcheck [ ] пины версий
