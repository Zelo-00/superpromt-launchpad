---
name: executing-development-workflows
description: Apply the full fullstack development lifecycle — Docker local setup, git workflow (trunk-based development, conventional commits), CI/CD pipelines, testing pyramid (unit/integration/E2E), code review process, deployment strategies (blue-green, canary, feature flags), and structured monitoring. Use when setting up a new project's engineering practices or auditing an existing pipeline for gaps. Do not use for technology stack selection or application architecture design.
---

## When to use

- Setting up a new project's development environment and CI/CD from scratch
- Auditing an existing pipeline for missing practices (pre-commit hooks, integration tests, health checks)
- Adding a deployment strategy (canary, blue-green) to an existing system
- Establishing structured logging and health checks for a service

## When NOT to use

- Choosing the tech stack → see composing-fullstack-tech-stacks
- Architecture design (monolith vs microservices) → see applying-software-architecture-patterns
- Detailed framework configuration (Next.js setup, Prisma config) — those are implementation, not workflow
- Security hardening → see hardening-application-security

---

## Quick start

```bash
# Daily development workflow
git checkout main && git pull
git checkout -b feature/my-feature
docker-compose up -d          # start local services
npm run dev                   # hot reload
npm run test && npm run lint  # before committing
git add src/                  # stage specific files, not .
git commit -m "feat(scope): description"
git push -u origin feature/my-feature
gh pr create
```

---

## Workflow

### 1. Local development environment

**Docker Compose baseline:**
```yaml
# docker-compose.yml
version: "3.8"
services:
  app:
    build: { context: ., target: development }
    volumes: [".:/app", "/app/node_modules"]
    ports: ["3000:3000"]
    environment:
      DATABASE_URL: postgresql://user:pass@db:5432/app
      REDIS_URL: redis://redis:6379
    depends_on: [db, redis]
  db:
    image: postgres:16-alpine
    environment: { POSTGRES_USER: user, POSTGRES_PASSWORD: pass, POSTGRES_DB: app }
    volumes: [postgres_data:/var/lib/postgresql/data]
    ports: ["5432:5432"]
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
volumes:
  postgres_data:
```

**Multistage Dockerfile (development → builder → production):**
```dockerfile
FROM node:20-alpine AS base
WORKDIR /app
RUN apk add --no-cache libc6-compat

FROM base AS development
COPY package*.json ./
RUN npm ci
COPY . .
CMD ["npm", "run", "dev"]

FROM base AS builder
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM base AS production
ENV NODE_ENV=production
COPY --from=builder /app/package*.json ./
RUN npm ci --only=production
COPY --from=builder /app/dist ./dist
USER node
CMD ["node", "dist/index.js"]
```

**Environment validation with Zod:**
```typescript
import { z } from "zod"
const envSchema = z.object({
  NODE_ENV: z.enum(["development", "test", "production"]),
  DATABASE_URL: z.string().url(),
  JWT_SECRET: z.string().min(32),
  PORT: z.coerce.number().default(3000),
})
export const env = envSchema.parse(process.env)
```

### 2. Git workflow (trunk-based development)

```
main (protected)
  ├── feature/user-auth      (1–2 days max → squash merge → main)
  ├── fix/payment-null       (same day → squash merge)
  └── release/v1.2.0         (cut from main for hotfixes only)
```

**Conventional commits format:**
```
<type>(<scope>): <description>    ← subject line, max 72 chars

[optional body explaining WHY]

[optional footer: Closes #123]
```
Types: `feat` | `fix` | `docs` | `style` | `refactor` | `test` | `chore`

**Pre-commit hooks (Husky + lint-staged):**
```json
{
  "lint-staged": {
    "*.{ts,tsx}": ["eslint --fix", "prettier --write"],
    "*.{json,md}": ["prettier --write"]
  }
}
```
```bash
# .husky/pre-commit
npx lint-staged
# .husky/commit-msg
npx commitlint --edit $1
```

### 3. CI/CD pipeline (GitHub Actions)

```yaml
# .github/workflows/ci.yml
name: CI
on:
  push: { branches: [main] }
  pull_request: { branches: [main] }

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 20, cache: npm }
      - run: npm ci && npm run lint && npm run type-check

  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env: { POSTGRES_USER: test, POSTGRES_PASSWORD: test, POSTGRES_DB: test }
        ports: ["5432:5432"]
        options: --health-cmd pg_isready --health-interval 10s --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 20, cache: npm }
      - run: npm ci
      - run: npm run test:unit
      - run: npm run test:integration
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/test
      - uses: codecov/codecov-action@v3

  build:
    needs: [lint, test]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 20, cache: npm }
      - run: npm ci && npm run build
      - uses: actions/upload-artifact@v4
        with: { name: build, path: dist/ }
```

### 4. Testing pyramid

```
     /\
    /E2E\        10% — critical user journeys (Playwright)
   /──────\
  / Integ  \     20% — API endpoints, DB operations
 /──────────\
/ Unit Tests \   70% — components, hooks, utilities
```

**Unit test pattern (Vitest + React Testing Library):**
```typescript
describe('UserForm', () => {
  it('submits valid data', async () => {
    const onSubmit = vi.fn()
    render(<UserForm onSubmit={onSubmit} />)
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'a@b.com' } })
    fireEvent.click(screen.getByRole('button', { name: /submit/i }))
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ email: 'a@b.com' }))
  })
})
```

**Integration test — hit real database, not mocks:**
```typescript
describe('POST /api/users', () => {
  beforeEach(() => db.user.deleteMany())
  it('creates user', async () => {
    const res = await client.post('/api/users', { email: 'new@example.com', name: 'N' })
    expect(res.status).toBe(201)
    expect(await db.user.findUnique({ where: { email: 'new@example.com' } })).toBeTruthy()
  })
})
```

**E2E test (Playwright):**
```typescript
test('user can log in', async ({ page }) => {
  await page.goto('/login')
  await page.fill('[name="email"]', 'user@example.com')
  await page.fill('[name="password"]', 'password123')
  await page.click('button[type="submit"]')
  await expect(page).toHaveURL('/dashboard')
})
```

### 5. Deployment strategies

**Blue-Green:**
```
1. Deploy new version to Green
2. Run smoke tests on Green
3. Switch load balancer → Green (atomic)
4. Blue becomes rollback target (keep for 24h)
```

**Canary:**
```
1. Deploy v1.1.0 with 5% traffic weight
2. Monitor: error rate, p99 latency, business metrics (conversion, etc.)
3. If metrics stable for 30 min → increment 5% → 25% → 50% → 100%
4. If metrics regress → immediately revert to 0%
```

**Feature flags:**
```typescript
function isFeatureEnabled(flag: string, userId: string): boolean {
  const config = flags[flag]
  if (!config?.enabled) return false
  if (config.allowedUsers?.includes(userId)) return true
  return hashUserId(userId) < config.rolloutPercentage
}
```

### 6. Monitoring and observability

**Structured logging:**
```typescript
import pino from 'pino'
const logger = pino({ level: process.env.LOG_LEVEL || 'info' })

app.use((req, res, next) => {
  const start = Date.now()
  res.on('finish', () => logger.info({
    type: 'request', method: req.method, path: req.path,
    statusCode: res.statusCode, duration: Date.now() - start
  }))
  next()
})
logger.error({ err, orderId }, 'Failed to process order')  // structured, not .toString()
```

**Health check endpoint:**
```typescript
app.get('/health', async (req, res) => {
  const checks = {
    database: await checkDb(),
    memory: checkMemory()
  }
  const healthy = Object.values(checks).every(c => c.status === 'healthy')
  res.status(healthy ? 200 : 503).json({ status: healthy ? 'healthy' : 'unhealthy', checks })
})

async function checkDb() {
  try { await db.$queryRaw`SELECT 1`; return { status: 'healthy' } }
  catch (e) { return { status: 'unhealthy', error: e.message } }
}
```

### Checklist before shipping a new service

- [ ] `docker-compose up` works from clean checkout with no manual steps
- [ ] `.env.local` documented and validated with Zod
- [ ] Pre-commit hooks installed and passing (lint, format, commitlint)
- [ ] CI pipeline: lint + type-check + unit + integration on every PR
- [ ] Integration tests hit real database (not mocks)
- [ ] E2E covers the golden path (auth → main user action)
- [ ] `GET /health` returns 200 with database check
- [ ] Structured logging (JSON, not string concat) with request IDs
- [ ] Deployment strategy defined (blue-green or canary, not hard-cutover)
- [ ] Rollback procedure documented

---

## Verification

```bash
# Verify pre-commit hooks are installed
ls .husky/pre-commit .husky/commit-msg
# Both files must exist

# Verify CI pipeline uses real database (not mocked)
grep -n "mock\|Mock\|jest.fn.*db\|vi.fn.*db" tests/integration/
# Must return 0 matches (mocked DB = false confidence)

# Verify health endpoint responds correctly
curl -sf http://localhost:3000/health | jq '.status'
# Must return: "healthy"

# Verify structured logging (JSON output)
curl -s http://localhost:3000/api/ping > /dev/null &
sleep 1; cat app.log | tail -5 | jq '.method'
# Must return valid JSON (not raw string log lines)

# Verify environment validation catches missing vars
NODE_ENV=production DATABASE_URL="" node -e "require('./dist/env')"
# Must throw ZodError, not silently start with empty DB URL
```

---

## Anti-patterns / Known gotchas

| Anti-pattern | Rebuttal |
|---|---|
| Mocking the database in integration tests | Mocked tests pass when production migrations fail. Integration tests must hit a real database — that's the only way to catch schema/query mismatches before prod. |
| `git add -A` or `git add .` in scripts | Accidentally stages `.env`, generated files, or binaries. Always stage specific paths: `git add src/ tests/`. |
| Skipping pre-commit hooks with `--no-verify` | Bypassing hooks trades 10 seconds of linting for hours of debugging a CI failure. Fix the hook failure instead. |
| Hard-cutover deployments (stop v1, start v2) | Creates a downtime window. Use blue-green (zero downtime) or canary (incremental risk). |
| String concatenation in logs (`logger.info("User " + id + " failed")`) | Unstructured strings can't be queried in Loki/Splunk. Always log structured objects: `logger.info({ userId: id }, 'User failed')`. |
| Feature flags with no rollout percentage | Binary on/off flags make it impossible to do incremental rollouts. Always include `rolloutPercentage` and `allowedUsers` escape hatch. |
| Omitting `/health` from containers | Kubernetes/ELB cannot determine if a container is ready. All services must expose `GET /health` returning 200 (healthy) or 503 (degraded). |

---

## Boundaries / Scope

**In scope:**
- Local development environment (Docker Compose, Dockerfile stages, env validation)
- Git workflow (trunk-based, conventional commits, pre-commit hooks)
- CI/CD pipelines (GitHub Actions patterns with real DB services)
- Testing pyramid (unit, integration with real DB, E2E with Playwright)
- Deployment strategies (blue-green, canary, feature flags)
- Monitoring (structured logging, health checks, Prometheus metrics)

**Out of scope:**
- Technology stack selection → see composing-fullstack-tech-stacks
- Application architecture → see applying-software-architecture-patterns
- Security hardening beyond workflow basics → see hardening-application-security
- Kubernetes/Helm deployment configuration in depth → separate skill
- Database migration strategies in depth → see adapting-sql-dialects or Prisma docs
