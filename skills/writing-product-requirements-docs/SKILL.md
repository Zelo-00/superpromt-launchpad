---
name: writing-product-requirements-docs
description: Write Product Requirements Documents in three formats — full standard PRD (11 sections), one-page PRD (fast decisions), and feature brief (lightweight hypothesis). Also covers Agile epics with user story breakdowns. Use when you need to document a feature or initiative for engineering, design, and stakeholder alignment. Do not use for sprint planning, engineering architecture design, or market research (each needs its own workflow).
---

# Writing Product Requirements Docs

Document product features with the right level of detail for the decision at hand — a full PRD for major initiatives, a one-pager for fast alignment, a feature brief for early exploration.

## When to use

- New feature or product initiative needs cross-functional documentation
- Engineering team needs defined acceptance criteria before build starts
- Stakeholder alignment required before committing resources
- Hypothesis-stage idea needs a lightweight written frame
- Agile epic needs story breakdown and success metrics

## When NOT to use

- Sprint planning or ticket writing → engineering workflow
- System architecture or API design → technical spec
- Market research or audience profiling → `market-research`
- Roadmap prioritization → `building-pm-toolkit-outputs`

## Quick start

```
Choose format:
  Full PRD         → major initiative, multi-team, needs exec approval
  One-page PRD     → fast feature decision, single team, < 4 weeks delivery
  Feature Brief    → early-stage hypothesis, not yet committed
  Agile Epic       → structured story breakdown inside an existing roadmap

Fill in required inputs → draft → review → finalize
```

## Workflow

### Format 1 — Standard PRD (11 sections)

Use for: major initiatives, new product lines, multi-team features, exec approval required.

**Required inputs before writing:**
- Problem statement and target user
- Proposed solution (high-level)
- Timeline constraints
- Success metrics (at least 3 KPIs)
- Known risks

**Sections:**

**1. Executive Summary** (one page max)
- Problem statement (2–3 sentences)
- Proposed solution (2–3 sentences)
- Business impact (3 bullet points)
- Timeline (high-level milestones)
- Resources required (team size + budget)
- Success metrics (3–5 KPIs)

**2. Problem Definition**
- Customer problem: Who / What / When / Where / Why / Impact
- Market opportunity: TAM, SAM, SOM; growth rate; competitive gaps; why now
- Business case: revenue potential; cost savings; strategic alignment; cost of inaction

**3. Solution Overview**
- High-level description
- Key capabilities
- User journey (end-to-end flow)
- Differentiation / unique value prop
- In scope / Out of scope / MVP definition

**4. User Stories & Requirements**
```
As a [persona]
I want to [action]
So that [outcome/benefit]

Acceptance Criteria:
- [ ] Criterion 1
- [ ] Criterion 2
```
Functional requirements table: ID / Requirement / Priority (P0/P1/P2) / Notes
Non-functional: performance, scalability, security, reliability, usability, compliance

**5. Design & UX** — design principles, links to mockups, information architecture

**6. Technical Specifications** — architecture overview, API design, data model, security

**7. Go-to-Market** — launch plan (soft/full), pricing strategy, success metrics table

**8. Risks & Mitigations**
| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| Technical debt | Medium | High | 20% sprint allocation |

**9. Timeline & Milestones**
| Milestone | Date | Deliverables | Success Criteria |

**10. Team & Resources** — team structure + budget breakdown

**11. Appendix** — user research data, competitive analysis, legal/compliance docs

---

### Format 2 — One-Page PRD

Use for: fast feature decisions, single team, < 4 weeks delivery, no exec approval needed.

```markdown
# [Feature Name] — One-Page PRD
Date: [date] | Author: [PM] | Status: Draft / In Review / Approved

## Problem
[2–3 sentences: what problem, for whom]

## Solution
[2–3 sentences: what we're building]

## Why Now?
- [Reason 1]
- [Reason 2]

## Success Metrics
| Metric | Current | Target |
|--------|---------|--------|
| KPI 1  | X       | Y      |

## Scope
In: [Feature 1], [Feature 2]
Out: [Feature A], [Feature B]

## User Flow
Step 1 → Step 2 → Step 3 → Success

## Risks
1. [Risk] → [Mitigation]

## Timeline
Design: Week 1–2 | Dev: Week 3–6 | QA: Week 7 | Launch: Week 8

## Resources
Engineering: N devs | Design: N designer | QA: N tester

## Open Questions
1. [Question]?
```

---

### Format 3 — Feature Brief (Lightweight)

Use for: early-stage hypothesis, not yet committed to build, needs a frame for discussion.

```markdown
# Feature: [Name]

## Context
[Why are we considering this?]

## Hypothesis
We believe that [building this feature]
For [these users]
Will [achieve this outcome]
We'll know we're right when [we see this metric]

## Proposed Solution
[High-level approach, no implementation details]

## Effort Estimate
Size: XS / S / M / L / XL | Confidence: High / Medium / Low

## Next Steps
- [ ] User research
- [ ] Design exploration
- [ ] Technical spike
- [ ] Stakeholder review
```

---

### Format 4 — Agile Epic

Use for: structured story breakdown inside an existing roadmap.

```markdown
# Epic: [Name]
Epic ID: EPIC-XXX | Theme: [Product Theme] | Quarter: QX 20XX
Status: Discovery / In Progress / Complete

## Problem Statement
[2–3 sentences]

## Goals & Objectives
1. [Objective 1]
2. [Objective 2]

## Success Metrics
- [Metric 1]: [Target]
- [Metric 2]: [Target]

## User Stories
| Story ID | Title       | Priority | Points | Status |
|----------|-------------|----------|--------|--------|
| US-001   | As a user…  | P0       | 5      | To Do  |

## Dependencies
- [Team/System 1]

## Acceptance Criteria
- [ ] All P0 stories complete
- [ ] Performance targets met
- [ ] Security review passed
- [ ] Documentation updated
```

## Verification

Before delivering any PRD:
- [ ] Format matches the initiative size (don't use a full PRD for a 1-week feature)
- [ ] Problem statement names a specific user and a specific pain — not a generic need
- [ ] Success metrics are measurable and have a current baseline and target
- [ ] Scope section explicitly lists what is OUT as well as what is IN
- [ ] Open questions are listed, not buried or omitted
- [ ] Acceptance criteria are testable (not "works well" — specific pass/fail conditions)

## Examples

**One-page PRD — Real-time collaboration:**

```
# Real-time Collaboration — One-Page PRD
Date: 2026-07-01 | Author: Jane S. | Status: In Review

## Problem
Enterprise PMs working on shared PRDs spend 30+ minutes daily on status-check messages because the tool lacks real-time co-editing. Collaboration happens in Slack, not in the product.

## Solution
Add multiplayer cursor + live-sync editing to the PRD editor, with presence indicators (name + color) per active editor.

## Why Now?
- #1 pain point in last 3 customer interviews
- Competitor shipped a basic version last month
- Engineering capacity available in Q3

## Success Metrics
| Metric         | Current | Target |
|----------------|---------|--------|
| Collab sessions/wk | 0   | 200    |
| Slack pings/PRD    | 12  | <3     |
| NPS (PM segment)   | 32  | 45     |

## Scope
In: live cursor, live sync, presence indicators
Out: comments/threads (Q4), version history (Q4)
```

---

**Feature Brief — Search improvements:**
```
## Hypothesis
We believe that adding filter-by-status to the search results page
For project managers searching for blocked tasks
Will reduce "I can't find it" support tickets by 40%
We'll know we're right when support tickets mentioning "search" drop by 40% in 30 days
```

## Anti-patterns / Known gotchas

| Gotcha | Fix |
|---|---|
| Writing a full 11-section PRD for a 3-day feature | Use a one-page PRD or feature brief |
| Vague problem statement ("users are frustrated") | Name the user, the specific task, and the measurable impact |
| Missing "out of scope" section | Out of scope is as important as in scope — prevents scope creep |
| Success metrics without baselines | Every target needs a current state to compare against |
| Acceptance criteria like "works correctly" | Write testable criteria: "User can filter by status; results update within 200ms" |
| Open questions buried in the body | Collect them in a dedicated section so they don't get lost |

## Boundaries / Scope

- Covers documentation and structure; does not make prioritization decisions → `building-pm-toolkit-outputs`
- Does not include competitive research inputs → `market-research`
- Technical architecture and API design → engineering spec (separate)
- Sprint breakdown and ticket writing → engineering workflow
