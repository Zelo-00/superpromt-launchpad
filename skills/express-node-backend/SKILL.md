---
name: express-node-backend
description: Бэкенд на Node/Express (или Fastify): структура, middleware, async-ошибки, валидация, безопасность. Для JS/TS-сервисов.
user-invocable: true
---

## Когда использовать
Строишь бэкенд на Node.js (Express/Fastify).
## Структура
`src/{app.js, routes/, controllers/, services/, models/, middleware/, config/}` — тонкие контроллеры, логика в services.
## Ключевые практики
- TypeScript где можно; валидация тела через zod/joi на входе.
- Async-ошибки: оборачивай хендлеры (`express-async-errors` или wrapper) → единый error-middleware в конце.
- Middleware: helmet (заголовки), cors (явный whitelist), rate-limit, express.json({limit}).
- Секреты — из `process.env` (dotenv в dev), не в репозитории.
- Логирование — pino/winston, без секретов в логах.
## Анти-паттерны
- `try/catch` в каждом хендлере вручную, `app.use(cors())` без ограничений, синхронные блокирующие вызовы.
## Чеклист
[ ] тонкие контроллеры [ ] zod-валидация [ ] error-middleware [ ] helmet+cors+rate-limit [ ] env-секреты
