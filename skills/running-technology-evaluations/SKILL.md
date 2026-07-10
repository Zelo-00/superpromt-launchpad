---
name: running-technology-evaluations
description: Run structured evaluation workflows to compare technology options across five scenarios: framework comparison, total cost of ownership (TCO) analysis, migration assessment, security evaluation, and cloud provider selection. Use when a team needs a documented, defensible evaluation — not just a gut-feel recommendation. Do not use for quick single-technology decisions (use making-technology-decisions for those).
---

## When to use

- Comparing 3+ technology options with explicit weighting criteria
- Calculating 3–5 year TCO before a major platform commitment
- Assessing risk and feasibility before migrating to a new technology
- Evaluating a technology's security posture and compliance readiness
- Selecting a cloud provider with cost, feature, and lock-in analysis

## When NOT to use

- Single-criterion decisions ("which is faster?") → run a benchmark instead
- Quick stack selection for MVP → see composing-fullstack-tech-stacks
- Decisions already made — don't run a post-hoc evaluation to justify a predetermined answer
- Evaluating only 2 options with obvious trade-offs → use the decision matrix from making-technology-decisions

---

## Quick start

```
Evaluation type → Gather data → Score → Validate → Document decision + ADR
```

Choose the right workflow:
```
Comparing frameworks/libraries?          → Framework Comparison Workflow
Committing to a platform for 3+ years?  → TCO Analysis Workflow
Planning a major rewrite or migration?  → Migration Assessment Workflow
Regulated environment / security audit? → Security Evaluation Workflow
Choosing primary cloud provider?         → Cloud Provider Selection Workflow
```

---

## Workflow

### A. Framework Comparison Workflow

**Step 1: Define requirements and weights (sum to 100%)**
```
Performance:          __%
Scalability:          __%
Developer Experience: __%
Ecosystem/Community:  __%
Learning Curve:       __%
                     ----
Total:               100%
```

**Step 2: Score each option (1–10 per criterion)**
```markdown
| Criterion    | Weight | React | Vue | Angular | Svelte |
|--------------|--------|-------|-----|---------|--------|
| Performance  | 20%    | 7     | 7   | 7       | 9      |
| Ecosystem    | 25%    | 9     | 7   | 8       | 5      |
| DX           | 25%    | 7     | 9   | 6       | 8      |
| Learning     | 15%    | 7     | 8   | 5       | 8      |
| Scalability  | 15%    | 8     | 7   | 9       | 7      |
| **Weighted** | 100%   | **7.7**| **7.75**|**7.0**|**7.25**|
```

**Step 3: Validate recommendation against constraints**
- Team's existing skills (don't ignore hiring market)
- Corporate backing and long-term viability
- Integration with existing tools and CI/CD

**Step 4: Document decision**
```markdown
## Decision: [Technology]
Alternatives: [A, B, C]
Selection rationale: [2–3 sentences]
Trade-offs accepted: [list]
Re-evaluate if: [trigger conditions]
```

---

### B. TCO Analysis Workflow

**Step 1: Gather cost inputs**

| Cost Category | Option A | Option B |
|---------------|----------|----------|
| Licensing/tooling | $__ | $__ |
| Training hours × rate | $__ | $__ |
| Migration/setup cost | $__ | $__ |
| Monthly hosting | $__ | $__ |
| Annual support | $__ | $__ |
| Maintenance hours/month × rate | $__ | $__ |

**Step 2: Project over 3–5 years with growth**
```python
def tco_projection(initial, monthly_ops, annual_growth, years=5):
    total = initial
    monthly = monthly_ops
    for year in range(years):
        yearly = monthly * 12
        total += yearly
        monthly *= (1 + annual_growth)
    return total

# Example: $5K setup, $500/mo ops, 20% annual growth, 5 years
print(f"5-year TCO: ${tco_projection(5000, 500, 0.20):,.0f}")
```

**Step 3: Identify optimization opportunities**
- Reserved pricing vs on-demand (typically 30–60% saving on compute)
- Automation reducing maintenance hours
- Cheaper alternatives for specific components

**Step 4: Compare break-even point**
```
Break-even = (Setup cost of B - Setup cost of A) / (Monthly savings of B vs A)
```

---

### C. Migration Assessment Workflow

**Step 1: Document current state**
```
□ Lines of code: ___
□ Components/modules: ___
□ External dependencies: ___
□ Team members experienced with current tech: ___
□ Pain points driving migration: [list]
```

**Step 2: Assess risk per category**

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Team learning curve | High | Medium | Training sprints before migration |
| Parallel system maintenance | High | High | Feature freeze during migration window |
| Data migration failures | Medium | Critical | Full backup + rollback plan before start |
| Integration breakage | Medium | High | Contract tests before and after |

**Step 3: Plan phases**
```
Phase 1 — Foundation (2–4 weeks)
  □ Setup new infrastructure
  □ Create migration utilities / codemods
  □ Train team: spike on representative component

Phase 2 — Incremental migration (bulk of timeline)
  □ Migrate by feature area, not by layer
  □ Maintain parallel systems with feature parity check
  □ Continuous integration tests on both stacks

Phase 3 — Completion (1–2 weeks)
  □ Remove legacy code
  □ Performance optimization
  □ Documentation update

Phase 4 — Stabilization (2–4 weeks monitoring)
  □ Monitor error rates, latency, and resource usage
  □ Address tail issues
  □ Gather retrospective metrics
```

**Step 4: Define rollback triggers**
```
□ Error rate > baseline + 20% for > 15 minutes → rollback
□ p99 latency doubles → investigate or rollback
□ Data integrity check fails → immediate rollback + incident
```

---

### D. Security Evaluation Workflow

**Step 1: Identify compliance standards required**
```
□ GDPR   □ SOC2   □ HIPAA   □ PCI-DSS   □ Other: ___
```

**Step 2: Gather security metrics per technology**

| Metric | Technology A | Technology B |
|--------|-------------|-------------|
| CVEs (last 12 months) | | |
| Critical/High CVE count | | |
| Avg patch response time (days) | | |
| Encryption at rest support | | |
| Audit logging built-in | | |

```bash
# Check CVE count for a package
npm audit --json | jq '.vulnerabilities | length'
# or for Python
pip-audit --json | jq '.dependencies[].vulns | length'

# Check last patch date
npm view <package> time.modified
```

**Step 3: Score compliance readiness per standard**

| Requirement | Met? | Gap | Remediation cost |
|-------------|------|-----|-----------------|
| Encryption in transit | ✓ | — | — |
| Access logging | ✗ | Missing audit trail | 3 dev-days |
| Data retention controls | ✗ | No TTL policy | 1 dev-day |

**Step 4: Risk-based decision**
- If remediation cost > 20% of implementation cost → consider alternative
- Document residual risk and risk owner

---

### E. Cloud Provider Selection Workflow

**Step 1: Map workload requirements**
```
□ Compute: ___ instances / cores / GB RAM
□ Storage: ___ TB (block/object/file)
□ Database: ___ type and size
□ Network transfer: ___ GB/month
□ Special: GPU/TPU / edge / multi-region / compliance certs
```

**Step 2: Verify required services exist and are mature**

| Need | AWS | GCP | Azure |
|------|-----|-----|-------|
| Managed K8s | EKS | GKE (best) | AKS |
| Serverless | Lambda (mature) | Cloud Functions | Azure Functions |
| ML training | SageMaker | Vertex AI (strong) | Azure ML |
| SQL Database | RDS / Aurora | Cloud SQL | Azure SQL |
| NoSQL | DynamoDB | Firestore | Cosmos DB |

**Step 3: Assess lock-in risk**
```
□ List proprietary services you will depend on
□ Estimate migration cost if switching (typically 20–40% of implementation)
□ Identify portable alternatives (e.g., Kubernetes instead of ECS)
□ Score lock-in risk: Low / Medium / High
```

**Step 4: Weight and select**
```
Cost:            __%  (AWS complex discounts; GCP sustained-use; Azure EA)
Features:        __%
Team expertise:  __%
Lock-in risk:    __%
Support quality: __%
               ----
               100%
```

---

## Verification

```bash
# Framework comparison: confirm chosen framework builds and passes type check
npm install && npm run build && npm run type-check
# Must exit 0 before finalizing decision

# TCO: verify projection formula with known baseline
python3 -c "
initial, monthly, growth, years = 5000, 500, 0.20, 5
total = initial
for _ in range(years):
    total += monthly * 12
    monthly *= 1 + growth
print(f'TCO: \${total:,.0f}')
"
# Expected: ~$57,130 for these inputs

# Migration: verify rollback plan is documented
grep -c "rollback" migration-plan.md
# Must be > 0

# Security: verify no critical CVEs in selected package
npm audit --json | jq '.vulnerabilities | to_entries[] | select(.value.severity=="critical") | .key'
# Must return empty (no critical CVEs)
```

---

## Examples

### Input → Output: Framework comparison

**Input:** "Choose between React, Vue, and Angular for an enterprise SaaS with a 15-person frontend team."

**Output:**
```
Weights: Performance 20%, Ecosystem 25%, DX 20%, Learning 10%, Enterprise adoption 25%
Scores:  React 8.2, Angular 7.8, Vue 7.1
Selection: React (Next.js)
Rationale: largest enterprise adoption, strongest TypeScript integration, team can hire for it
Trade-offs: heavier mental model (client/server components in Next.js 14)
Re-evaluate if: team changes significantly or Svelte ecosystem matures to enterprise level
```

### Input → Output: Migration assessment

**Input:** "We're migrating from Angular 1.x to React. Codebase: 50K LOC, 200 components, team of 6."

**Output:**
```
Risk: HIGH — large codebase, team needs React training, 6-month timeline
Phase 1: 3-week React training sprint + 2 pilot components migrated
Phase 2: migrate by feature area (auth first, then dashboard, then reports)
Parallel: keep Angular app functional until 80% components migrated
Rollback trigger: error rate > 25% baseline for 15+ min
Estimated timeline: 8–12 months full migration
```

---

## Anti-patterns / Known gotchas

| Anti-pattern | Rebuttal |
|---|---|
| Over-weighting recent popularity vs long-term stability | A framework trending on GitHub this month may not have enterprise backing in 3 years. Weight corporate backing and LTS commitment explicitly. |
| Ignoring team learning curve in timeline estimates | A 6-month learning curve on a "faster" framework often delivers slower outcomes than a well-known one. Add training time to the TCO. |
| Assuming vendor benchmark numbers are representative | Run your own benchmark on your workload profile — vendor benchmarks are always best-case. |
| Post-hoc evaluation to justify a predetermined choice | Sets biased weights to favor a conclusion. If the decision is already made, write an ADR; don't fake an evaluation. |
| Not accounting for hidden costs (training, hiring, technical debt) | "License is free" often means "hiring is expensive" or "maintenance is a black hole." Include all costs. |
| Missing rollback plan in migration assessment | Without a documented rollback trigger and procedure, migrations that go wrong cause extended outages. Always define the rollback before Phase 1 starts. |

---

## Boundaries / Scope

**In scope:**
- Five evaluation workflows: framework comparison, TCO, migration, security, cloud provider
- Weighted scoring matrices and decision documentation templates
- Cost projection formulas and risk assessment frameworks
- Rollback planning for migrations

**Out of scope:**
- Technology selection for simple 2-option decisions → see making-technology-decisions
- Architecture pattern selection → see applying-software-architecture-patterns
- Implementing the evaluated technology (this skill ends at the decision)
- Detailed security hardening → see hardening-application-security
- Cloud infrastructure implementation → see applying-aws-architecture-patterns
