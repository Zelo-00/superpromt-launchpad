---
name: migrating-databases-2
description: >
  ORM-specific migration workflows for Prisma, Drizzle, Django, and golang-migrate.
  Covers schema syntax, CLI commands, custom SQL migrations for operations ORMs cannot
  express, and data migration patterns per framework.
  Use when generating, applying, or debugging migrations in a project that uses one of
  these ORMs. Do not use for raw SQL / psql-only workflows or non-relational stores.
---

## When to use

- Generating or applying migrations via Prisma, Drizzle, Django, or golang-migrate
- Writing a custom SQL migration for operations the ORM cannot express (CONCURRENTLY, triggers, backfills)
- Debugging dirty migration state or version conflicts
- Setting up a migration workflow in a new project

## When NOT to use

- Raw psql / manual SQL workflows (see `migrating-databases`)
- Zero-downtime multi-phase strategies (see `migrating-databases-3`)
- Non-relational databases
- Schema review or query optimization (see `reviewing-postgres-databases-3`)

## Quick start

```bash
# Prisma — most common commands
npx prisma migrate dev --name add_user_avatar   # dev: generate + apply
npx prisma migrate deploy                        # prod: apply pending
npx prisma generate                              # regenerate client

# Drizzle
npx drizzle-kit generate                         # generate migration from schema
npx drizzle-kit migrate                          # apply migrations
npx drizzle-kit push                             # dev-only: push without migration file

# Django
python manage.py makemigrations                  # generate from model changes
python manage.py migrate                         # apply
python manage.py showmigrations                  # inspect state

# golang-migrate
migrate create -ext sql -dir migrations -seq add_user_avatar
migrate -path migrations -database "$DATABASE_URL" up
migrate -path migrations -database "$DATABASE_URL" down 1
migrate -path migrations -database "$DATABASE_URL" force VERSION  # fix dirty state
```

## Workflow

### Prisma (TypeScript/Node.js)

**Schema example with best-practice types:**
```prisma
model User {
  id        String    @id @default(cuid())
  email     String    @unique
  name      String?
  avatarUrl String?   @map("avatar_url")
  createdAt DateTime  @default(now()) @map("created_at")
  updatedAt DateTime  @updatedAt @map("updated_at")
  orders    Order[]

  @@map("users")
  @@index([email])
}
```

**Custom SQL for operations Prisma cannot express:**
```bash
# Step 1: create empty migration
npx prisma migrate dev --create-only --name add_email_index_concurrent
# Step 2: edit generated file
```
```sql
-- prisma/migrations/20250101_add_email_index_concurrent/migration.sql
-- Prisma cannot generate CONCURRENTLY — write manually
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_email ON users (email);
```

**Checklist for Prisma projects:**
- [ ] `prisma generate` runs after every `migrate deploy` in CI
- [ ] `--create-only` used for indexes that need `CONCURRENTLY`
- [ ] `migrate reset` only used in dev, never in production
- [ ] Migration files committed to version control

### Drizzle (TypeScript/Node.js)

**Schema example:**
```typescript
import { pgTable, text, boolean, timestamp, uuid } from "drizzle-orm/pg-core";

export const users = pgTable("users", {
  id:        uuid("id").primaryKey().defaultRandom(),
  email:     text("email").notNull().unique(),
  name:      text("name"),
  isActive:  boolean("is_active").notNull().default(true),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});
```

**Checklist for Drizzle projects:**
- [ ] `drizzle-kit push` only used in dev — never in production
- [ ] `drizzle-kit generate` + `drizzle-kit migrate` for production deployments
- [ ] Custom SQL added via raw `sql` template in migration files for CONCURRENTLY

### Django (Python)

**Standard migration workflow:**
```bash
python manage.py makemigrations app_name -n describe_change
python manage.py migrate --check      # dry-run: exits non-zero if unapplied
python manage.py migrate
python manage.py showmigrations       # verify applied state
```

**Data migration (backfill):**
```python
# accounts/migrations/0016_backfill_display_names.py
from django.db import migrations

def backfill_display_names(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    batch_size = 5000
    qs = User.objects.filter(display_name="")
    while qs.exists():
        batch = list(qs[:batch_size])
        for user in batch:
            user.display_name = user.username
        User.objects.bulk_update(batch, ["display_name"], batch_size=batch_size)

class Migration(migrations.Migration):
    dependencies = [("accounts", "0015_add_display_name")]
    operations = [
        migrations.RunPython(backfill_display_names, migrations.RunPython.noop),
    ]
```

**Decouple model from DB drop (safe column removal):**
```python
# Step 1: remove from model state, NOT from DB
class Migration(migrations.Migration):
    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(model_name="user", name="legacy_field"),
            ],
            database_operations=[],   # DB not touched yet
        ),
    ]
# Step 2 (next deploy): drop column in a separate migration
```

**Checklist for Django projects:**
- [ ] Data migrations are separate from schema migrations
- [ ] `RunPython.noop` used for irreversible data migrations (not `reverse_code=None` which raises)
- [ ] `SeparateDatabaseAndState` for safe column removal
- [ ] `migrate --check` in CI before deploy

### golang-migrate (Go)

**Migration file pair:**
```sql
-- migrations/000003_add_user_avatar.up.sql
ALTER TABLE users ADD COLUMN avatar_url TEXT;
CREATE INDEX CONCURRENTLY idx_users_avatar_url ON users (avatar_url)
  WHERE avatar_url IS NOT NULL;

-- migrations/000003_add_user_avatar.down.sql
DROP INDEX IF EXISTS idx_users_avatar_url;
ALTER TABLE users DROP COLUMN IF EXISTS avatar_url;
```

**Fix dirty state after a failed migration:**
```bash
# 1. Inspect what failed
migrate -path migrations -database "$DATABASE_URL" version

# 2. Manually fix the DB to a consistent state via psql
psql $DATABASE_URL -c "-- reverse the partial change manually"

# 3. Force the version to the last clean state
migrate -path migrations -database "$DATABASE_URL" force 2
```

**Checklist for golang-migrate projects:**
- [ ] Sequential numbering (`-seq` flag) to avoid ordering conflicts
- [ ] Both `.up.sql` and `.down.sql` files committed together
- [ ] `IF EXISTS` / `IF NOT EXISTS` guards in down migrations
- [ ] CI runs `migrate up` then validates with `migrate version`

## Verification (exit criteria)

```bash
# 1. No pending unapplied migrations
# Prisma:
npx prisma migrate status 2>&1 | grep -c "unapplied"  # → 0 expected

# Django:
python manage.py migrate --check  # → exits 0 if all applied

# golang-migrate:
migrate -path migrations -database "$DATABASE_URL" version 2>&1 | grep "dirty"
# → "dirty: false" expected

# 2. Generated client matches schema (Prisma)
npx prisma validate  # → "The schema at prisma/schema.prisma is valid"

# 3. Migration files are committed
git status migrations/  # → nothing unstaged
```

## Examples

**Input:** "Add a required `avatar_url` column to users in a Prisma project"
```bash
# 1. Update schema.prisma:  avatarUrl String? @map("avatar_url")
# 2. Generate: npx prisma migrate dev --name add_user_avatar_url
# 3. If you need an index: npx prisma migrate dev --create-only --name add_avatar_index
#    Then edit SQL: CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_avatar ON users(avatar_url);
# 4. Deploy: npx prisma migrate deploy
```

**Input:** "golang-migrate failed halfway through migration 5, state is dirty"
```bash
migrate -path migrations -database "$DATABASE_URL" version   # shows "5 (dirty)"
psql $DATABASE_URL -c "-- manually undo partial changes from migration 5"
migrate -path migrations -database "$DATABASE_URL" force 4   # reset to last clean
migrate -path migrations -database "$DATABASE_URL" up        # retry from 5
```

## Anti-patterns / Known gotchas

| Anti-pattern | Rebuttal |
|---|---|
| `drizzle-kit push` in production | Skips migration files — no audit trail, no rollback. Use `generate` + `migrate` in prod. |
| Prisma inline index without `--create-only` | Prisma generates `CREATE INDEX` (not CONCURRENTLY), blocking writes on large tables. Use `--create-only` for concurrent indexes. |
| Django `RunPython` with no reverse | `migrations.RunPython.noop` is explicit intent; omitting `reverse_code` raises `NotImplementedError` on reverse. |
| Editing an applied migration file | Other environments already ran the old version. Create a new migration instead. |
| Skipping `migrate --check` in CI | Deploy ships with unapplied migrations — schema mismatch at runtime. |
| golang-migrate `force` without manual DB fix | Marks version as clean without actually fixing the DB state. Fix the DB first, then force. |

## Boundaries / Scope

**In scope:** Prisma, Drizzle, Django, golang-migrate CLI commands; ORM schema syntax; custom SQL migrations; data migration patterns per framework.

**Out of scope:** Raw SQL safety patterns (see `migrating-databases`), zero-downtime multi-phase strategies (see `migrating-databases-3`), query optimization (see `reviewing-postgres-databases-3`).
