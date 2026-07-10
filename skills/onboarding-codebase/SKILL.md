---
name: onboarding-codebase
description: Systematically analyze an unfamiliar codebase and produce a structured onboarding guide plus an initial CLAUDE.md. Use when joining a new project, opening an existing repo for the first time with Claude Code, or when a user says "help me understand this codebase", "give me a tour", or "generate a CLAUDE.md". Do not use for repos you already have deep context on — use grep/read directly instead.
---

## When to use
- First time opening a project with Claude Code
- Joining a new team or repo
- User asks: "help me understand this codebase", "give me a tour", "generate CLAUDE.md"
- Preparing to onboard another developer

## When NOT to use
- You already have codebase context from earlier in the session
- The repo is a tiny single-file script
- The user wants a specific feature explanation (use read/grep directly)

## Quick start

```bash
# Run these in parallel for fast reconnaissance
find . -maxdepth 2 -type f -name "package.json" -o -name "go.mod" \
  -o -name "Cargo.toml" -o -name "pyproject.toml" -o -name "pom.xml" | head -10
find . -maxdepth 2 -type d ! -path "*/node_modules/*" ! -path "*/.git/*" \
  ! -path "*/dist/*" ! -path "*/__pycache__/*"
ls -1 *.config.* next.config.* vite.config.* 2>/dev/null
```

## Workflow

### Phase 1 — Reconnaissance (read as little as possible)

Run these checks **in parallel**:

```bash
# 1. Package manifest — reveals language, framework, key deps
cat package.json | python3 -m json.tool 2>/dev/null || \
  cat go.mod 2>/dev/null || cat pyproject.toml 2>/dev/null

# 2. Directory tree (2 levels, ignore noise)
find . -maxdepth 2 -not -path "*/node_modules/*" -not -path "*/.git/*" \
  -not -path "*/dist/*" -not -path "*/.next/*" -not -path "*/__pycache__/*" \
  -not -path "*/vendor/*" -not -path "*/build/*"

# 3. Framework fingerprint
ls next.config.* nuxt.config.* angular.json vite.config.* \
   django/ settings.py manage.py 2>/dev/null

# 4. Entry points
ls main.* index.* app.* server.* cmd/ src/main/ 2>/dev/null

# 5. Config and tooling
ls .eslintrc* .prettierrc* tsconfig.json Makefile Dockerfile \
   docker-compose* .github/workflows/ .env.example 2>/dev/null

# 6. Test structure
find . -maxdepth 3 -name "*.test.*" -o -name "*.spec.*" \
  -o -name "*_test.go" -o -name "pytest.ini" 2>/dev/null | head -10
```

### Phase 2 — Architecture mapping

From the reconnaissance data, identify:

**Tech stack**
- Language and version constraints
- Framework and key libraries
- Database and ORM
- Build tooling / bundler
- CI/CD platform

**Architecture pattern**
- Monolith / monorepo / microservices / serverless
- Frontend-backend separation or fullstack
- API style: REST, GraphQL, gRPC, tRPC, tRPC

**Directory map** (top-level → purpose):
```
src/components/  → UI components
src/api/         → route handlers
src/services/    → business logic
src/db/          → models and migrations
tests/           → test suite
```

**Request lifecycle** — trace one request from entry to response:
- Where does it enter? (router, handler, controller)
- How is it validated? (middleware, schema, guard)
- Where is business logic? (service, model, use case)
- How is data accessed? (ORM, raw query, repository)

### Phase 3 — Convention detection

**Naming conventions** (read 3–5 representative files):
- File naming: kebab-case / camelCase / PascalCase / snake_case
- Component/class naming pattern
- Test file naming: `*.test.ts` / `*.spec.ts` / `*_test.go`

**Code patterns**:
- Error handling: try/catch / Result type / error codes
- Dependency injection vs. direct imports
- State management approach
- Async patterns: callbacks / Promise / async-await / channels

**Git conventions** (skip if history is shallow):
```bash
git log --oneline -10
git branch -r | head -10
```

### Phase 4 — Generate artifacts

#### Output A — Onboarding guide (printed to conversation)

```markdown
# Getting started: [Project Name]

## What this is
[2–3 sentences: what it does and who it serves]

## Tech stack
| Layer | Technology | Version |
|-------|-----------|---------|
| Language | TypeScript | 5.x |
| Framework | Next.js | 14.x |
| Database | PostgreSQL | 16 |

## Architecture
[Component connection description or ASCII diagram]

## Key entry points
- **API routes**: `src/app/api/` — Next.js route handlers
- **UI pages**: `src/app/(dashboard)/` — authenticated pages
- **Database**: `prisma/schema.prisma` — single source of truth

## Directory structure
[top-level directory → purpose mapping]

## Request lifecycle
[trace one API call start to finish]

## Conventions
- File naming: [detected]
- Error handling: [detected]
- Testing: [detected]
- Git workflow: [detected]

## Common tasks
- Dev server: `npm run dev`
- Tests: `npm test`
- Lint: `npm run lint`
- DB migrate: `npx prisma migrate dev`

## Where to find things
| I want to... | Look in... |
|---|---|
| Add an API endpoint | `src/app/api/` |
| Add a UI page | `src/app/(dashboard)/` |
| Add a DB table | `prisma/schema.prisma` |
```

#### Output B — CLAUDE.md (written to project root)

If `CLAUDE.md` already exists: read it, enhance (keep existing, mark additions).
If it doesn't exist: create it. Keep under 100 lines.

```markdown
# Project instructions

## Tech stack
[detected stack summary]

## Code style
- [detected naming conventions]
- [patterns to follow]

## Testing
- Run tests: `[detected test command]`
- Pattern: [detected test file convention]
- Coverage: `[coverage command if configured]`

## Build and run
- Dev: `[detected dev command]`
- Build: `[detected build command]`
- Lint: `[detected lint command]`

## Project structure
[key directories → purpose]

## Conventions
- [commit style if detectable]
- [PR workflow if detectable]
- [error handling pattern]
```

## Verification

- [ ] Tech stack identified from actual manifests (not guessed)
- [ ] At least one real entry point path confirmed to exist
- [ ] At least one real test file confirmed to exist
- [ ] CLAUDE.md written and readable
- [ ] Guide is under 2 minutes to skim (no exhaustive lists)
- [ ] Unknown conventions labeled "Could not detect" rather than guessed

## Examples

### Example 1 — First time in a new repo
```
User: "Walk me through this codebase"
Action: run all 4 phases → print onboarding guide to chat + write CLAUDE.md
Output: guide in ~40 lines + CLAUDE.md in ~50 lines
```

### Example 2 — Generate CLAUDE.md only
```
User: "Generate a CLAUDE.md for this project"
Action: run phases 1–3, skip guide, write CLAUDE.md only
Output: project-specific CLAUDE.md
```

### Example 3 — Update existing CLAUDE.md
```
User: "Update CLAUDE.md with current conventions"
Action: read existing CLAUDE.md → run phases 1–3 → merge, mark additions
Output: enhanced CLAUDE.md with "## Added [date]:" markers
```

## Anti-patterns / Known gotchas

| Anti-pattern | Fix |
|---|---|
| Reading every source file in Phase 1 | Use glob/grep; read selectively only when a signal is ambiguous |
| Overwriting an existing CLAUDE.md | Always read it first; enhance, never replace |
| Guessing conventions when detection fails | Write "Could not detect" — wrong guidance is worse than none |
| Writing a CLAUDE.md > 100 lines | Keep it focused on decisions that affect coding, not project history |
| Listing all 200 dependencies | Highlight only the ones that change how you write code |
| Describing self-evident directories | `src/` does not need a description |

## Boundaries / Scope

Covers: codebase structure analysis, convention detection, onboarding guide, CLAUDE.md generation.
Does not cover: code quality review, architecture recommendations, refactoring suggestions,
or security auditing — those are separate skills.
