---
name: designing-operational-dashboards
description: >
  Design effective operational dashboards for SRE, developer, executive, and ops
  audiences: information hierarchy, F/Z-pattern layouts, panel type selection,
  color semantics, time-range strategy, template variables, drill-down links,
  performance optimization (recording rules, query limits), accessibility, and
  lifecycle governance. Use when creating a new monitoring dashboard, reviewing
  an existing dashboard for clarity or performance problems, or establishing
  dashboard standards for a team. Do not use for metric collection setup,
  Prometheus alerting rules, SLO definition, or log/trace pipeline configuration.
---

## When to use

- Designing a new operational dashboard for a service or platform
- Reviewing an existing dashboard that is slow, confusing, or ignored during incidents
- Establishing team-wide dashboard naming, tagging, and refresh standards
- Generating dashboard JSON from service definitions programmatically
- Evaluating a dashboard for accessibility or color-blind usability

## When NOT to use

- Defining SLOs or burn rate alerts → use `building-observability-systems`
- Setting up Prometheus scrape configs or recording rules from scratch
- Configuring log aggregation or distributed tracing
- Writing Grafana plugin code

## Quick start

```yaml
# Minimum viable SRE dashboard structure
dashboard:
  title: "[SRE] payment-service"
  tags: [team:payments, service:payment, env:production, purpose:ops]
  time: { from: "now-15m", to: "now" }
  refresh: "15s"
  variables:
    - name: service
      type: query
      query: "label_values(up, service)"
  panels:
    - { title: "Availability", type: stat, expr: "avg(up{service='$service'})*100", unit: percent }
    - { title: "Error Rate", type: timeseries, expr: "rate(http_errors[5m])", unit: percentunit }
    - { title: "P95 Latency", type: timeseries, expr: "histogram_quantile(0.95, rate(http_duration_bucket[5m]))", unit: ms }
    - { title: "Request Rate", type: timeseries, expr: "sum(rate(http_requests_total[5m]))", unit: reqps }
```

## Workflow

### 1. Define audience and purpose FIRST

Before any panel design, answer:
- **Who reads this?** SRE (incident response), Developer (debugging), Executive (business review), Ops (capacity)
- **What decision does it support?** "Is the service healthy?" vs "Which endpoint is slow?" vs "Are we on track for SLA?"
- **When is it used?** During incidents (needs 15s refresh) vs weekly review (needs 7-day range)

### 2. Apply information hierarchy

```
TOP THIRD — Status at a glance (stat panels, gauges)
  Service health indicator | SLO achievement % | Active alerts count | Error budget remaining

MIDDLE THIRD — Golden signals (timeseries panels)
  Latency P50/P95/P99 | Request rate | Error rate | Saturation (CPU/mem)

BOTTOM THIRD — Details for investigation (tables, heatmaps)
  Slowest endpoints | Error breakdown by type | Dependency status | Recent deployments
```

### 3. Choose layout pattern by audience

**F-pattern (SRE/developer — left-to-right scan):**
```
[Status     ] [SLO Summary ] [Error Budget]
[Latency P50/P95/P99       ] [Error Rate  ]
[Saturation ] [Infra        ] [Debug Info  ]
```

**Z-pattern (executive — diagonal scan):**
```
[Business KPIs    ] → [System Status  ]
         ↓                    ↓
[Trend / 30d      ] ← [Key Metric     ]
```

### 4. Panel type selection

| Data type | Best panel | Avoid |
|---|---|---|
| Single current value + threshold | Stat | Line chart |
| Trend over time | Timeseries | Table |
| Resource % with good/bad bounds | Gauge | Timeseries |
| Top N ranked items | Table | Gauge |
| Distribution / latency histogram | Heatmap | Bar chart |
| Categorical comparison | Bar chart | Timeseries |

### 5. Color and threshold configuration

```yaml
# Traffic light with meaningful thresholds (availability example)
thresholds:
  steps:
    - color: green   # value: null (default)
    - color: yellow  # value: 99.0   (degraded)
    - color: orange  # value: 99.5   (poor)
    - color: red     # value: 99.9   (critical, breaching SLO)
options:
  color_mode: background  # shows color as background, not just text

# Color semantic standards (apply consistently across ALL dashboards)
# green:  #28a745  healthy / success
# yellow: #ffc107  warning / degraded
# red:    #dc3545  error / critical
# blue:   #007bff  informational / neutral
# gray:   #6c757d  disabled / unknown

# Accessibility: add line style variation (dashed vs solid) for color-blind users
custom:
  line_style: { fill: "dash", dash: [8, 4] }  # P99 vs P95 lines
```

### 6. Time range and refresh strategy

| Dashboard type | Default range | Auto-refresh |
|---|---|---|
| Real-time ops (SRE on-call) | Last 15 min | 15–30s |
| Troubleshooting | Last 1 hour | 1 min |
| Business review | Last 24 hours | 5 min |
| Capacity planning | Last 7 days | 15 min |

### 7. Template variables and drill-downs

```yaml
variables:
  - name: service
    type: query
    query: "label_values(up, service)"
    include_all: true
    multi: true
  - name: environment
    type: query
    query: "label_values(up{service='$service'}, environment)"
    current: { text: production, value: production }

# Panel drill-down links
data_links:
  - title: "View Error Logs"
    url: "/d/logs?var-service=${__field.labels.service}&from=${__from}&to=${__to}"
  - title: "Open Traces"
    url: "/d/traces?var-service=${__field.labels.service}"

# Dynamic panel title
title: "${service} — Request Rate"
```

### 8. Performance optimization

```yaml
# Use recording rules for expensive queries (define in Prometheus)
# rule: record: http_request_rate_5m
#       expr: sum(rate(http_requests_total[5m])) by (service, method, handler)

# Then in panel:
expr: http_request_rate_5m   # pre-computed, fast

# Limit data resolution
interval: 15s   # one point per 15s max for 1h window (~240 points)
# Never: rate(metric[1s])[1h]  → 3600 points — browser lag

# Dashboard limits
max_panels: 25
max_queries_per_panel: 10
max_series_per_panel: 50
```

### 9. Testing and validation checklist

- [ ] All panels load without error in target time range
- [ ] Template variable changes update all panels
- [ ] Drill-down links resolve to correct dashboard with correct filters
- [ ] Dashboard loads < 5 seconds on the standard time range
- [ ] Colors are distinguishable in grayscale (print-safe)
- [ ] New team member can identify the primary health signal in < 30 seconds
- [ ] Dashboard identifies the next action during a simulated incident

### 10. Governance

```yaml
# Naming: [Team] [Service] — [Purpose]
title: "[Payments] payment-service — SRE Ops"

# Required tags
tags: [team:payments, service:payment-service, env:production, purpose:ops]

# Retirement: archive after 90 days of < 5 views/week
# Maintenance: quarterly user feedback + broken panel review
```

## Verification

```bash
# Dashboard JSON is valid Grafana schema
python3 -c "import json; json.load(open('dashboard.json')); print('PASS: valid JSON')"

# All panels have titles
python3 -c "
import json
d = json.load(open('dashboard.json'))
no_title = [p for p in d.get('panels', []) if not p.get('title')]
print('FAIL: untitled panels:', no_title) if no_title else print('PASS: all panels titled')
"

# Template variables reference $service or $environment pattern
grep -c '\\$service\|\\$environment\|\\$__' dashboard.json

# No fixed-interval sleeps in query expressions (indicator of bad metric design)
grep '"interval": "1s"' dashboard.json && echo "WARN: 1s interval will produce too many points"

# Panel count within limit
python3 -c "
import json
d = json.load(open('dashboard.json'))
count = len(d.get('panels', []))
print(f'{'PASS' if count <= 25 else 'WARN'}: {count} panels (limit 25)')
"
```

**Exit criterion:** Dashboard passes all checklist items, loads < 5s, and a new team member can identify the primary health indicator without coaching.

## Examples

**Stat panel with threshold (availability):**
```yaml
- title: "API Availability"
  type: stat
  targets:
    - expr: "avg(up{service='payment-service'}) * 100"
  field_config:
    unit: percent
    decimals: 3
    thresholds:
      steps:
        - { color: red, value: null }
        - { color: yellow, value: 99.0 }
        - { color: green, value: 99.9 }
  options:
    color_mode: background
    text_mode: value_and_name
```

**Timeseries panel (latency percentiles):**
```yaml
- title: "Request Latency"
  type: timeseries
  targets:
    - { expr: "histogram_quantile(0.50, rate(http_duration_bucket[5m]))", legend: "P50" }
    - { expr: "histogram_quantile(0.95, rate(http_duration_bucket[5m]))", legend: "P95" }
    - { expr: "histogram_quantile(0.99, rate(http_duration_bucket[5m]))", legend: "P99" }
  field_config:
    unit: ms
    custom: { fill_opacity: 10 }
  options:
    legend: { display_mode: table, values: [min, max, mean, last] }
```

## Anti-patterns / Known gotchas

| Anti-pattern | Rebuttal |
|---|---|
| > 30 panels on one dashboard | Cognitive overload and browser memory exhaustion; split by audience or create a landing + detail pattern |
| Auto-refresh 5s on a 7-day time range | 7d range with high-resolution queries floods Prometheus at 5s; refresh only as fast as the time range needs |
| Color chosen by aesthetics, not semantics | If red means "latency" on one panel and "availability" on another, on-call engineers misread state during incidents |
| No drill-down links from high-level to detail | Operators have to manually open a new dashboard with the right filters; drill-downs reduce MTTR |
| Complex PromQL in dashboard instead of recording rules | Long histogram_quantile + rate queries time out at scale; pre-compute with recording rules |
| Dashboards without tags | Ungoverned dashboards accumulate; tags enable automated audits and retirement workflows |
| Missing legend with only color to distinguish series | Color-blind users can't differentiate; always add line style variation or show labels in-chart |

## Boundaries / Scope

**In scope:** Dashboard information hierarchy, layout patterns, panel type selection, color semantics, time-range strategy, template variables, drill-down links, performance optimization, accessibility, governance lifecycle.

**Out of scope:** Prometheus/Grafana infrastructure setup, SLO and alert definition (see `building-observability-systems`), application instrumentation, log panel/Loki setup, dashboard plugin development.
