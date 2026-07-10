---
name: composing-docker-services
description: >
  Compose multi-container applications with Docker Compose using production-grade
  patterns — healthchecks, network isolation, resource limits, dev/prod overrides,
  worker queues, and log rotation. Covers common failure modes and troubleshooting.
  Use when: writing or reviewing a docker-compose.yml, adding a new service to an
  existing stack, debugging container startup failures, or hardening a dev-only compose
  file for production use.
  Do not use for: Kubernetes / Helm deployments, single-container Dockerfiles, or cloud
  provider managed services (ECS, Cloud Run).
---

## When to use

- Writing a new `docker-compose.yml` for a web app, worker, or data pipeline
- Reviewing an existing compose file for production readiness (missing healthchecks, open ports, no limits)
- Separating dev and prod configurations without duplicating the entire file
- Adding a background worker, scheduler, or message queue to an existing stack
- Debugging `depends_on` ordering, OOM kills, or network connectivity issues

## When NOT to use

- Deploying to Kubernetes, Nomad, or a cloud-managed container service
- Writing or optimizing Dockerfiles (separate concern)
- Networking across multiple Docker hosts (use Swarm or k8s instead)
- The stack is a single container — plain `docker run` is simpler

## Quick start

```yaml
# Minimal production-safe web + db stack
services:
  app:
    build: .
    ports: ["3000:3000"]
    env_file: .env
    depends_on:
      db:
        condition: service_healthy   # waits for healthcheck, not just container start
    restart: unless-stopped
    mem_limit: 512m

  db:
    image: postgres:16-alpine
    volumes: [pgdata:/var/lib/postgresql/data]
    env_file: .env.db
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped
    mem_limit: 256m

volumes:
  pgdata:
```

## Workflow

### 1. Choose network topology

```yaml
networks:
  frontend:           # nginx + app — external traffic
  backend:
    internal: true    # db + redis — no external access

# nginx: frontend only
# app: frontend + backend
# db, redis: backend only
```

**Rule:** every service joins only the networks it needs. `internal: true` means the network has no external routing — containers inside cannot reach the internet and outside cannot reach them.

### 2. Add healthchecks to every service

```yaml
# PostgreSQL
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U postgres"]
  interval: 10s
  timeout: 5s
  retries: 5

# Redis
healthcheck:
  test: ["CMD", "redis-cli", "ping"]
  interval: 10s
  timeout: 3s
  retries: 3

# HTTP service
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
  interval: 30s
  timeout: 3s
  retries: 3
  start_period: 10s   # grace period before retries count

# Without healthcheck, depends_on only waits for the container to START, not be ready
```

### 3. Separate dev and prod with override files

```yaml
# docker-compose.yml (base — production-like, no secrets in plain text)
services:
  app:
    build: .
    ports: ["3000:3000"]
    restart: unless-stopped
```

```yaml
# docker-compose.override.yml (dev — auto-loaded when present)
services:
  app:
    build:
      target: development       # multi-stage Dockerfile target
    volumes:
      - .:/app                  # bind mount for hot reload
      - /app/node_modules       # preserve container node_modules
    environment:
      - NODE_ENV=development
    ports:
      - "9229:9229"             # debugger
    restart: "no"
```

```bash
docker compose up                        # dev (loads override automatically)
docker compose -f docker-compose.yml up  # prod (skips override)
```

### 4. Worker + queue pattern

```yaml
services:
  api:
    command: uvicorn main:app --host 0.0.0.0 --port 8000
    depends_on:
      rabbitmq: {condition: service_healthy}

  worker:
    build: {context: ., target: runtime}
    command: celery -A tasks worker --loglevel=info
    depends_on:
      rabbitmq: {condition: service_healthy}

  scheduler:
    build: {context: ., target: runtime}
    command: celery -A tasks beat --loglevel=info
    depends_on:
      rabbitmq: {condition: service_healthy}

  rabbitmq:
    image: rabbitmq:3.13-management-alpine
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "check_running"]
      interval: 10s
      retries: 5
```

### 5. Configure log rotation

```yaml
services:
  app:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"   # keeps last 3 files = max 30 MB per service
```

Default Docker logging has **no size limit** — production servers fill disks silently.

### 6. Environment variable hygiene

```yaml
# Committed to repo (no secrets)
# .env.example
DATABASE_URL=postgres://user:changeme@db:5432/appname
SECRET_KEY=changeme

# compose file uses substitution with defaults
services:
  app:
    image: myapp:${APP_VERSION:-latest}
    environment:
      - LOG_LEVEL=${LOG_LEVEL:-info}
```

**Never put actual secrets in the compose file itself.** Use `env_file:` pointing to `.env` (gitignored).

### Checklist before deploying

- [ ] Every service has a `healthcheck`
- [ ] `depends_on` uses `condition: service_healthy` (not default)
- [ ] `mem_limit` set on every service
- [ ] Database / cache on an `internal: true` network
- [ ] No secrets in compose file — only in gitignored `.env` files
- [ ] Log rotation configured (`max-size`, `max-file`)
- [ ] Named volumes (not bind mounts) for persistent data
- [ ] `restart: unless-stopped` on production services

## Verification (exit criterion)

```bash
# Validate compose file syntax
docker compose config --quiet && echo "PASS syntax OK" || echo "FAIL syntax error"

# Confirm every service has a healthcheck
docker compose config | python3 -c "
import sys, yaml
cfg = yaml.safe_load(sys.stdin)
missing = [s for s, v in cfg.get('services', {}).items() if 'healthcheck' not in v]
print('FAIL missing healthcheck:', missing) if missing else print('PASS all services have healthcheck')
"

# Check for services without mem_limit
docker compose config | grep -c "mem_limit" | xargs -I{} bash -c \
  'echo "Services: $(docker compose config | grep -c "^  [a-z]"), mem_limits: {}"'

# Confirm no plaintext secrets in compose file
grep -Ei "(password|secret|token|api_key)\s*[:=]\s*[^$\"\{]" docker-compose.yml \
  && echo "FAIL potential plaintext secret" || echo "PASS no plaintext secrets detected"

# End-to-end: bring up and check all services healthy
docker compose up -d
sleep 15
docker compose ps --format json | python3 -c "
import sys, json
services = [json.loads(l) for l in sys.stdin if l.strip()]
unhealthy = [s['Name'] for s in services if s.get('Health','') not in ('healthy','')]
print('FAIL unhealthy:', unhealthy) if unhealthy else print('PASS all healthy')
"
```

## Examples

### Example 1: Review — missing healthcheck + open database port

**Before:**
```yaml
services:
  app:
    depends_on: [db]    # waits for start, not ready
  db:
    image: postgres:16-alpine
    ports: ["5432:5432"]   # database exposed to host
```

**After:**
```yaml
services:
  app:
    depends_on:
      db: {condition: service_healthy}
  db:
    image: postgres:16-alpine
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      retries: 5
    networks: [backend]    # removed host port; internal only
```

### Example 2: Add Redis cache to existing web + db stack

```yaml
  redis:
    image: redis:7-alpine
    command: redis-server --maxmemory 64mb --maxmemory-policy allkeys-lru
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      retries: 3
    restart: unless-stopped
    networks: [backend]
    mem_limit: 128m
```

Then update `app` to add `redis: {condition: service_healthy}` under `depends_on`.

## Anti-patterns / Known gotchas

| Anti-pattern | Rebuttal |
|---|---|
| **`depends_on: [db]` without healthcheck** | Container "started" ≠ "ready to accept connections". App crashes on startup if DB is still initializing. Always pair `condition: service_healthy` with a working healthcheck. |
| **Database port exposed to host in production** | `5432:5432` lets anyone on the host (or network) connect directly. Remove the ports mapping; services talk via the internal network by service name. |
| **No `mem_limit`** | A runaway container can OOM the host, killing everything. Set conservative limits and tune up from metrics rather than leaving them absent. |
| **Secrets in compose file** | `docker compose config` dumps them to stdout. Use `env_file:` pointing to gitignored `.env`. |
| **Bind mount for production data** | `- ./data:/var/lib/postgresql/data` breaks on user UID mismatches and is tied to the host path. Use named volumes for persistence. |
| **No log rotation** | Default `json-file` driver grows unbounded. A busy app can fill a 50 GB disk in days. Always set `max-size` and `max-file`. |

## Boundaries / Scope

**In scope:**
- `docker-compose.yml` and `docker-compose.override.yml` authoring and review
- Healthcheck, networking, resource limit, and log rotation patterns
- Dev/prod overlay strategy
- Worker + queue topology
- Troubleshooting common startup and networking failures

**Out of scope:**
- Dockerfile authoring and layer optimization
- Kubernetes, Helm, or cloud-managed container services
- Container registry push/pull and image tagging pipelines
- Secrets management systems (Vault, AWS Secrets Manager)
- Swarm mode or multi-host networking
