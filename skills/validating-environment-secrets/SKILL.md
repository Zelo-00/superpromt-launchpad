---
name: validating-environment-secrets
description: >
  Validates required environment variables at startup or in CI, detects secrets leaked
  into source code or git history, and guides credential rotation after a leak is
  confirmed. Use when setting up a new service's env contract, adding a pre-commit
  hook to block secret commits, or responding to a credential leak incident. Do not use
  for secrets-manager provisioning or infrastructure-as-code secrets (use dedicated
  IaC tools for that).
---

## When to use

- New service setup: defining which env vars are required vs optional
- CI/CD pipeline: gate deployment on env completeness
- Pre-commit hook installation: block accidental secret commits
- Post-incident: credential was found in a commit or public repo
- Periodic hygiene: scan git history for previously leaked secrets

## When NOT to use

- Provisioning secrets into Vault/SSM/1Password (use IaC or secrets-manager CLI)
- Runtime secrets rotation without downtime (blue-green or rolling-restart is an infra concern)
- Scanning third-party repos you don't control

---

## Quick start

```bash
# 1. Validate env at app start (exit 1 if missing)
bash scripts/validate-env.sh

# 2. Scan staged files for secrets before commit
bash scripts/scan-secrets.sh

# 3. Install as pre-commit hook
bash scripts/install-hook.sh

# 4. Scan entire git history (post-incident)
bash scripts/scan-history.sh
```

---

## Workflow

### Step 1 — Define the env contract

Create `scripts/validate-env.sh`:
```bash
#!/bin/bash
set -euo pipefail
MISSING=() WARNINGS=()

ALWAYS_REQUIRED=(APP_SECRET APP_URL DATABASE_URL AUTH_JWT_SECRET AUTH_REFRESH_SECRET)
PROD_REQUIRED=(STRIPE_SECRET_KEY STRIPE_WEBHOOK_SECRET SENTRY_DSN)

for var in "${ALWAYS_REQUIRED[@]}"; do
  [ -z "${!var:-}" ] && MISSING+=("$var")
done

if [ "${APP_ENV:-}" = "production" ] || [ "${NODE_ENV:-}" = "production" ]; then
  for var in "${PROD_REQUIRED[@]}"; do
    [ -z "${!var:-}" ] && MISSING+=("$var (required in production)")
  done
fi

# Format/length checks
[ -n "${AUTH_JWT_SECRET:-}" ] && [ ${#AUTH_JWT_SECRET} -lt 32 ] && \
  WARNINGS+=("AUTH_JWT_SECRET < 32 chars — insecure")

[ -n "${DATABASE_URL:-}" ] && \
  ! echo "$DATABASE_URL" | grep -qE "^(postgres|mysql|mongodb|redis)://" && \
  WARNINGS+=("DATABASE_URL format looks wrong")

[ ${#WARNINGS[@]} -gt 0 ] && printf "WARN: %s\n" "${WARNINGS[@]}"

if [ ${#MISSING[@]} -gt 0 ]; then
  printf "FATAL: Missing env vars:\n"; printf "  %s\n" "${MISSING[@]}"
  echo "Copy .env.example → .env and fill values."; exit 1
fi
echo "✅ All required environment variables are set"
```

TypeScript equivalent (embed in app startup):
```typescript
// src/config/validateEnv.ts
const required = ['APP_SECRET','APP_URL','DATABASE_URL','AUTH_JWT_SECRET','AUTH_REFRESH_SECRET']
const missing = required.filter(k => !process.env[k])
if (missing.length) { console.error('FATAL: Missing env vars:', missing); process.exit(1) }
if ((process.env.AUTH_JWT_SECRET?.length ?? 0) < 32) {
  console.error('FATAL: AUTH_JWT_SECRET must be ≥32 chars'); process.exit(1)
}
export const config = {
  appSecret:    process.env.APP_SECRET!,
  appUrl:       process.env.APP_URL!,
  databaseUrl:  process.env.DATABASE_URL!,
  jwtSecret:    process.env.AUTH_JWT_SECRET!,
  refreshSecret:process.env.AUTH_REFRESH_SECRET!,
  stripeKey:    process.env.STRIPE_SECRET_KEY,   // optional
  port:         parseInt(process.env.APP_PORT ?? '3000', 10),
} as const
```

- [ ] List all vars in ALWAYS_REQUIRED
- [ ] List prod-only vars in PROD_REQUIRED
- [ ] Add format/length checks for sensitive vars (JWT secrets, ports, URLs)
- [ ] Mirror ALL vars in `.env.example` with safe placeholder values

### Step 2 — Install pre-commit secret scanner

Create `scripts/scan-secrets.sh` (detects staged additions only):
```bash
#!/bin/bash
FAIL=0
check() {
  local label="$1" pattern="$2"
  local hits; hits=$(git diff --cached -U0 2>/dev/null | grep "^+" | \
    grep -vE "^(\+\+\+|#|//)" | grep -E "$pattern" | \
    grep -v "\.env\.example\|test\|mock\|fixture\|fake" || true)
  [ -n "$hits" ] && { echo "SECRET [$label]:"; echo "$hits" | head -3; FAIL=1; }
}
check "AWS Key"        "AKIA[0-9A-Z]{16}"
check "AWS Secret"     "aws_secret_access_key\s*=\s*['\"]?[A-Za-z0-9/+]{40}"
check "Stripe Live"    "sk_live_[0-9a-zA-Z]{24,}"
check "Stripe Webhook" "whsec_[0-9a-zA-Z]{32,}"
check "JWT Token"      "eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"
check "Generic Secret" "(secret|password|api_key|token)\s*[:=]\s*['\"][^'\"]{12,}['\"]"
check "Private Key"    "-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
check "DB Conn w/ pwd" "(postgres|mysql|mongodb)://[^:]+:[^@]+@"
check "GitHub PAT"     "gh[ps]_[A-Za-z0-9]{36,}\|github_pat_[A-Za-z0-9_]{82}"
check "Slack Token"    "xox[baprs]-[0-9A-Za-z]{10,}"
check "Google API"     "AIza[0-9A-Za-z_-]{35}"
[ $FAIL -eq 1 ] && {
  echo; echo "BLOCKED: Remove secrets and use env vars instead."
  echo "False positive? Add to .secretsignore or use git commit --no-verify only if 100% certain."
  exit 1
}
echo "✅ No secrets detected in staged changes"
```

Install hook:
```bash
# scripts/install-hook.sh
cp scripts/scan-secrets.sh .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
echo "Pre-commit hook installed"
```

Using `pre-commit` framework (recommended for teams):
```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks:
      - id: gitleaks
  - repo: local
    hooks:
      - id: validate-env-example
        name: env-example-up-to-date
        language: script
        entry: bash scripts/check-env-example.sh
        pass_filenames: false
```

- [ ] Hook installed in `.git/hooks/pre-commit` OR via `pre-commit` framework
- [ ] `.env.example` covers every var in `validate-env.sh`
- [ ] `.secretsignore` documents any intentional false-positive exemptions

### Step 3 — Respond to a credential leak (rotation workflow)

```bash
# 3a. Confirm exposure: find first offending commit
git log --all -p --no-color -- "*.env" "*.json" "*.yaml" "*.ts" | \
  grep -B10 "THE_LEAKED_VALUE" | grep "^commit" | tail -1

# 3b. Get exposure window start date
git show --format="%ci" COMMIT_HASH | head -1

# 3c. Check if public (GitHub search — requires gh auth)
gh api search/code -X GET -f q="THE_LEAKED_VALUE" | jq '.total_count'
```

**Rotate per service** (do immediately, before anything else):
```bash
# AWS IAM: revoke old → create new → update everywhere
aws iam delete-access-key --access-key-id AKIA_OLD
aws iam create-access-key --user-name service-user

# Stripe: roll key in dashboard, then:
# Dashboard → Developers → API keys → Roll key

# DB password
psql -c "ALTER USER app_user PASSWORD 'new-strong-password';"

# JWT secret (all sessions invalidated — users re-login)
# Generate: openssl rand -base64 48

# GitHub PAT: Settings → Developer Settings → PAT → Revoke → Create new
```

Update all environments from secrets manager (single source of truth):
```bash
# Vault KV v2
vault kv put secret/myapp/prod STRIPE_SECRET_KEY="sk_live_NEW..." APP_SECRET="new..."

# AWS SSM
aws ssm put-parameter --name "/myapp/prod/STRIPE_SECRET_KEY" \
  --value "sk_live_NEW..." --type SecureString --overwrite

# Doppler
doppler secrets set STRIPE_SECRET_KEY="sk_live_NEW..." --project myapp --config prod
```

Remove from git history (coordinate with team first — rewrites history):
```bash
# WARNING: force-push required after this
git filter-repo --replace-text <(echo "LEAKED_VALUE==>REDACTED")
git push origin --force --all
# All developers must re-clone after this
```

- [ ] Old credential revoked at source service
- [ ] New credential generated and stored in secrets manager
- [ ] All environments redeployed with new value
- [ ] Secret removed from git history (if it was committed)
- [ ] Audit logs checked for unauthorized use of old credential

### Step 4 — Verify
```bash
# Confirm not in git history anymore
git log --all -p | grep "LEAKED_VALUE" | wc -l  # must be 0

# Test new credential works
curl -H "Authorization: Bearer $NEW_TOKEN" https://api.service.com/test

# Confirm validate-env.sh passes in CI
bash scripts/validate-env.sh
```

---

## Verification

Exit criteria:

```bash
# Env validation passes
bash scripts/validate-env.sh && echo "PASS"

# No secrets in staged files
git diff --cached | grep -E "AKIA|sk_live_|-----BEGIN.*PRIVATE KEY" | wc -l  # must be 0

# No secrets anywhere in history
git log --all -p | grep -cE "AKIA[0-9A-Z]{16}" || true  # must be 0

# Hook is executable
test -x .git/hooks/pre-commit && echo "HOOK OK"

# .env.example is not missing any required var
diff <(grep -oE '^[A-Z_]+' .env.example | sort) \
     <(grep -oE '"[A-Z_]+"' scripts/validate-env.sh | tr -d '"' | sort)
```

---

## Examples

**Example: startup crash on missing var**
```
$ NODE_ENV=production node dist/main.js
FATAL: Missing env vars: [ 'STRIPE_SECRET_KEY', 'SENTRY_DSN' ]
→ Add to production secrets manager and redeploy
```

**Example: commit blocked by hook**
```
$ git commit -m "add stripe integration"
SECRET [Stripe Live]: +const key = "sk_live_abc123..."
BLOCKED: Remove secrets and use env vars instead.
→ Remove hardcoded value; read from process.env.STRIPE_SECRET_KEY
```

**Example: post-incident rotation log**
```
Exposure window: 2026-05-01 14:22 UTC → 2026-06-15 09:00 UTC (44 days)
Services affected: Stripe (payment API), GitHub CI (deploy token)
Actions: revoked at 09:05, new creds deployed at 09:47, history cleaned 11:30
Audit: 0 unauthorized Stripe charges, 0 unauthorized GH actions runs found
```

---

## Anti-patterns / Known gotchas

| Anti-pattern | Rebuttal |
|---|---|
| `.env` file committed to git | Even private repos get cloned, forked, or accidentally made public; secrets in history persist after deletion |
| Checking secrets into `.env.example` with real values | The example file's entire job is to show shape, not provide working credentials |
| `--no-verify` to bypass the hook "just this once" | That one bypass is exactly how leaks happen; if the hook false-positives, fix the pattern or `.secretsignore` |
| Rotating only one environment (e.g. staging) | The leaked credential is valid everywhere it was used; rotate in ALL environments atomically |
| Deleting the file but not cleaning history | `git rm` doesn't remove history; use `git filter-repo` |
| Waiting to rotate "until the weekend" | Credential exposure windows compound risk; rotate within the hour of discovery |

---

## Boundaries / Scope

**In scope**: env contract definition, pre-commit scanning, history scanning, rotation runbook  
**Out of scope**: secrets manager provisioning, IaC secrets (Terraform/Pulumi), zero-downtime rotation architecture  
**Related skills**: `writing-runbooks` (incident response), `hardening-application-security` (broader security posture)
