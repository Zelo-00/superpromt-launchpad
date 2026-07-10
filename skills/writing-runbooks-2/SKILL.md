---
name: writing-runbooks-2
description: >
  Produces structured, machine-executable runbooks for deployment, incident response,
  database maintenance, and other recurring ops procedures. Each runbook includes
  explicit pre-conditions, step-by-step commands with expected output, verification
  checks, rollback triggers, and a staleness detection contract. Use when creating a
  new operational procedure, updating a runbook after infra changes, or onboarding
  on-call engineers. Do not use for one-off debugging sessions — runbooks are for
  repeatable, documented procedures only.
---

## When to use

- New service going to production (needs deployment runbook)
- Post-incident (create or update incident response runbook)
- Scheduled database maintenance window
- Onboarding on-call engineers to an unfamiliar system
- Quarterly runbook validation pass
- After infrastructure change that invalidates existing steps

## When NOT to use

- Ad-hoc debugging (no repeated procedure exists yet)
- One-time migrations that will never run again
- Automated pipeline steps that have no human decision point

---

## Quick start

Pick a template from the four below. Fill all `[PLACEHOLDER]` fields before using.
A runbook is valid only when it passes the quarterly validation checklist (Step 5).

```
Templates available:
  1. Deployment Runbook
  2. Incident Response Runbook
  3. Database Maintenance Runbook
  4. Staleness Detection Contract
```

---

## Workflow

### Step 1 — Deployment Runbook

```markdown
# Deployment Runbook: [SERVICE NAME] v[VERSION]
Last verified: [YYYY-MM-DD] by [NAME]
Config tracked: [vercel.json | Helm chart | terraform/main.tf]

## Pre-deployment checklist
- [ ] CI pipeline green on commit [SHA]
- [ ] Staging smoke tests passed (link: [URL])
- [ ] Database migrations backwards-compatible
- [ ] Rollback plan reviewed and executable < 10 min
- [ ] On-call engineer available for 30 min post-deploy
- [ ] Change window approved: [YYYY-MM-DD HH:MM UTC]

## Deploy steps
1. Merge PR [#NUMBER] to main
   Expected: CI starts within 60s

2. Monitor deployment pipeline
   ```
   [TOOL] deploy status --env production
   ```
   Expected output: "Deployment succeeded" or equivalent
   Time limit: [X] minutes. If exceeded → TRIGGER ROLLBACK

3. Run smoke tests
   ```
   curl -sf https://[DOMAIN]/health | jq .
   ```
   Expected: `{"status":"ok","version":"[VERSION]"}`

4. Verify key metrics (first 15 min post-deploy)
   - Error rate: < [X]%  (current baseline: [X]%)
   - p95 latency: < [X] ms (current baseline: [X] ms)
   - Dashboard: [URL]

## Rollback triggers
Trigger rollback if ANY of:
- Smoke test fails
- Error rate > [THRESHOLD]% for 5 consecutive minutes
- p95 latency > [THRESHOLD] ms for 5 consecutive minutes
- Any Critical alert fires

## Rollback procedure
```
git revert [SHA] && git push origin main
[TOOL] deploy --env production --rollback
```
Expected: previous version live within [X] minutes

## Post-deploy
- [ ] Update status page if applicable
- [ ] Notify [CHANNEL] with: "Deployed [VERSION] ✅ — [BRIEF CHANGE SUMMARY]"
- [ ] Update `Last verified` date above
```

### Step 2 — Incident Response Runbook

```markdown
# Incident Response: [INCIDENT TYPE / SYSTEM]
Severity definitions: P1=complete outage | P2=degraded | P3=minor impact
Escalation: [PagerDuty rotation / contact]

## Phase 1 — Triage (first 5 minutes)
- [ ] Confirm impact scope: which users/features affected?
- [ ] Assign incident commander (first responder = IC until handed off)
- [ ] Open incident channel: #incident-[DATE]-[SHORT-DESC]
- [ ] Set severity (P1/P2/P3) and update status page

First checks (run in order):
```bash
# 1. Is the service responding?
curl -sf https://[DOMAIN]/health || echo "HEALTH CHECK FAILED"

# 2. Recent deploys in the last 2 hours?
git log --oneline --since="2 hours ago" origin/main

# 3. Recent infrastructure changes?
[TOOL] changes list --since 2h

# 4. Error spike in logs?
[LOGGING_TOOL] query 'level=error AND service=[NAME]' --since 30m --count
```

## Phase 2 — Diagnosis (first 30 minutes)
- [ ] Check [dashboard URL] for anomalies
- [ ] Identify error type distribution (timeout / 5xx / crash / data)
- [ ] Correlate with recent deploys, config changes, traffic spikes

Decision tree:
```
Error type?
  → 5xx from upstream dependency → check [DEPENDENCY] status page → if degraded: MITIGATION A
  → OOM / crash loop             → check resource metrics → if CPU/mem spike: MITIGATION B
  → Elevated latency             → check DB slow queries → if found: MITIGATION C
  → Auth failures                → check auth service health → MITIGATION D
```

## Phase 3 — Mitigation
Common mitigations (fill in service-specific actions):

MITIGATION A (upstream dependency):
```bash
# Enable feature flag to bypass [DEPENDENCY]
[FLAGGING_TOOL] set [FLAG_NAME] false
# OR: route traffic to fallback
[LOAD_BALANCER] route --backend fallback-[SERVICE]
```

MITIGATION B (OOM / crash):
```bash
# Restart pods / dynos
[ORCHESTRATOR] restart [SERVICE] --env production
# Scale up if needed
[ORCHESTRATOR] scale [SERVICE] --replicas [N+2]
```

MITIGATION C (DB slow queries):
```sql
-- Identify blocking queries
SELECT pid, now() - pg_stat_activity.query_start AS duration, query
FROM pg_stat_activity
WHERE state != 'idle' AND query_start < NOW() - INTERVAL '30 seconds'
ORDER BY duration DESC;

-- Kill long-running blocker (confirm before executing)
SELECT pg_terminate_backend([PID]);
```

## Phase 4 — Resolution and postmortem
- [ ] Confirm recovery: smoke test passes, error rate < baseline
- [ ] Update status page to resolved
- [ ] Write 5-line blameless postmortem within 48h:
  - Timeline
  - Root cause
  - Customer impact
  - How we detected
  - Action items with owners and ETAs
```

### Step 3 — Database Maintenance Runbook

```markdown
# DB Maintenance: [DB NAME / OPERATION]
Scheduled window: [DAY] [HH:MM]–[HH:MM] UTC
DB: [HOST:PORT/DBNAME]
Last verified: [YYYY-MM-DD]

## Pre-maintenance
- [ ] Backup completed and restore verified:
  ```bash
  pg_dump [DBNAME] | gzip > backup-$(date +%Y%m%d).sql.gz
  # Verify restore works in staging before proceeding
  ```
- [ ] Replication lag < 1s:
  ```sql
  SELECT * FROM pg_stat_replication;
  ```
- [ ] Read-only replica available for failover
- [ ] Migrations are backwards-compatible (old code can run with new schema)

## Migration sequence
```bash
# Run migration (use transaction where possible)
psql [CONN_STRING] -f migrations/[NUMBER]_[name].sql

# Verify applied
psql [CONN_STRING] -c "SELECT * FROM schema_migrations ORDER BY id DESC LIMIT 5;"
# Expected: migration [NUMBER] appears as latest
```

Lock-risk note: `ALTER TABLE ... ADD COLUMN NOT NULL` on large tables holds ACCESS EXCLUSIVE lock.
Safer alternative:
```sql
ALTER TABLE users ADD COLUMN new_col TEXT;            -- no lock
UPDATE users SET new_col = 'default' WHERE new_col IS NULL;  -- batched
ALTER TABLE users ALTER COLUMN new_col SET NOT NULL;  -- brief lock after backfill
```

## Vacuum / reindex (if applicable)
```sql
VACUUM ANALYZE [TABLE];
REINDEX INDEX CONCURRENTLY [INDEX_NAME];  -- CONCURRENTLY avoids lock
```

## Verification queries
```sql
-- Table row counts look sane?
SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC LIMIT 10;

-- Index size sane after reindex?
SELECT indexname, pg_size_pretty(pg_relation_size(indexrelid))
FROM pg_stat_user_indexes ORDER BY pg_relation_size(indexrelid) DESC LIMIT 10;

-- No long-running queries?
SELECT count(*) FROM pg_stat_activity WHERE state='active' AND query_start < NOW()-INTERVAL '5min';
-- Expected: 0
```

## Rollback
```bash
psql [CONN_STRING] -f migrations/rollback/[NUMBER]_rollback.sql
```
```

### Step 4 — Staleness Detection Contract

Every runbook MUST include this section. Update it when referenced files change.

```markdown
## Staleness contract
This runbook references these files and becomes STALE when they change:

| File | Last checked | Change indicator |
|------|-------------|-----------------|
| vercel.json / helm/values.yaml | [DATE] | deploy steps may change |
| .github/workflows/deploy.yml | [DATE] | CI steps may change |
| migrations/ directory | [DATE] | DB steps may change |
| .env.example | [DATE] | env var names may change |

Auto-detect staleness:
```bash
# Run this to check if tracked files changed since last verification
git log --oneline --since="[LAST_VERIFIED_DATE]" -- vercel.json helm/ .github/workflows/ migrations/ .env.example
# Any output → runbook needs review
```
```

### Step 5 — Quarterly Validation Checklist

Run on first Monday of each quarter:
```bash
# For each runbook:
echo "Runbook: [NAME]"

# 1. Execute commands in staging
bash runbooks/test-steps.sh staging

# 2. Validate expected outputs match
diff <(bash runbooks/[NAME].sh 2>&1) runbooks/expected-outputs/[NAME].txt

# 3. Test rollback path
bash runbooks/test-rollback.sh staging

# 4. Confirm contact / escalation ownership
grep -E "escalation:|contact:|pagerduty:" runbooks/[NAME].md

# 5. Update Last verified date
sed -i '' "s/Last verified: .*/Last verified: $(date +%Y-%m-%d) by $USER/" runbooks/[NAME].md
git commit -m "runbook: quarterly validation [NAME] $(date +%Y-Q%q)"
```

- [ ] All steps executed successfully in staging
- [ ] Expected outputs documented and validated
- [ ] Rollback executed and verified
- [ ] Escalation contacts current (not people who left)
- [ ] `Last verified` date updated

---

## Verification

```bash
# All runbooks have Last verified within 90 days
find runbooks/ -name "*.md" | while read f; do
  date_str=$(grep "Last verified:" "$f" | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}')
  days_old=$(( ($(date +%s) - $(date -d "$date_str" +%s)) / 86400 ))
  [ $days_old -gt 90 ] && echo "STALE ($days_old days): $f"
done

# All runbooks have required sections
for f in runbooks/*.md; do
  for section in "Pre-" "Rollback" "Verification" "Staleness"; do
    grep -q "$section" "$f" || echo "MISSING $section in $f"
  done
done

# Staleness check for a specific runbook
git log --oneline --since="$(grep 'Last verified' runbooks/deploy.md | grep -oE '[0-9-]+')" \
  -- vercel.json .github/workflows/
# Must be empty — otherwise the runbook is stale
```

---

## Examples

**Deployment smoke test passing**:
```
curl -sf https://api.example.com/health | jq .
{"status":"ok","version":"2.4.1","db":"connected","cache":"connected"}
→ Deploy complete ✅
```

**Incident triage decision**:
```
Error rate spiked to 18% at 14:23 UTC
Recent deploy: 14:15 UTC (PR #847 — payment service update)
Correlation: spike started 8 minutes after deploy → TRIGGER ROLLBACK
Rollback executed 14:31 UTC → error rate returned to 0.4% by 14:35 UTC
```

---

## Anti-patterns / Known gotchas

| Anti-pattern | Rebuttal |
|---|---|
| Runbook without expected command output | Engineers can't tell if a command succeeded or failed without knowing what "success" looks like |
| No rollback trigger definition | "Roll back if things look bad" is not actionable under stress; name exact thresholds and metrics |
| Runbook that references config files but has no staleness contract | Config changes invisibly invalidate steps; every config dependency must be tracked |
| Skipping staging execution during quarterly validation | A runbook that has never been tested is a theory, not a procedure |
| Escalation list with ex-employees or rotated phone numbers | Stale contacts fail exactly when you need them most; validate on every quarterly pass |
| Runbook stored only in someone's head or a chat thread | Undocumented procedures create single points of failure; write it down after the first time |

---

## Boundaries / Scope

**In scope**: deployment, incident response, DB maintenance, staleness detection, quarterly validation  
**Out of scope**: automated runbook execution (use a workflow tool), incident ticketing workflow, post-incident metrics analysis  
**Related skills**: `communicating-technical-debt` (post-incident stakeholder comms), `validating-environment-secrets` (env checks referenced in runbooks)
