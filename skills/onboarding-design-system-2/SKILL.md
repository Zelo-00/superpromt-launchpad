---
name: onboarding-design-system-2
description: >
  Update, troubleshoot, or extend an existing markdown-html design-system config:
  inspect the effective config resolution, override specific keys without
  re-running the full wizard, debug WCAG contrast failures, and manage project vs
  global scope.
  Use when: the design-system was already onboarded but renders incorrectly,
  you need to override a single token after a brand refresh, or you need to
  understand why a project-scope config is or isn't taking effect.
  Do not use for: first-time setup (use onboarding-design-system skill), markdown
  conversion (use /cs:markdown-html), or frontend JS/CSS token generation.
---

## When to use

- Design-system was already configured but rendered output looks wrong
- Partial brand update: change one colour or font without re-running the full 10-question wizard
- Debugging why a project-scoped config override isn't taking effect
- CI pipeline started failing after a config change — need to diagnose
- Need to reset to defaults and start fresh for a specific scope

## When NOT to use

- First-time setup — use the onboarding-design-system skill instead
- You're converting markdown to HTML — run the config skill first, then `/cs:markdown-html`
- Building a component library or design system from scratch
- Frontend token generation (JSON/CSS/SCSS) for a JS project

## Quick start

```bash
# 1. Diagnose: show effective config (project > global > defaults)
python3 markdown-html/skills/design-system/scripts/config_loader.py --show

# 2. Check status
python3 markdown-html/skills/design-system/scripts/config_loader.py --status

# 3. Override a single key (no wizard re-run)
python3 markdown-html/skills/design-system/scripts/onboard.py \
  --set brand.primary=#1A56DB

# 4. Smoke-test the fix
python3 markdown-html/skills/markdown-html/scripts/convert.py README.md \
  && echo "Conversion OK"
```

## Workflow

### Step 1 — Inspect the effective config

Config resolution order: **project scope** (`./.markdown-html/design-system.json`) overrides **global scope** (`~/.config/markdown-html/design-system.json`) overrides **built-in defaults**.

```bash
python3 markdown-html/skills/design-system/scripts/config_loader.py --show
# Look for:
#   "scope": "project" or "global"
#   "brand.primary": "#HEXCODE"
#   "wcag_status": "pass" or "fail"
```

If the wrong scope is active, check for the presence of `./.markdown-html/design-system.json`:

```bash
ls -la .markdown-html/design-system.json 2>/dev/null \
  && echo "Project scope active" \
  || echo "No project scope; using global"
```

### Step 2 — Override individual keys

```bash
# Dotted-key notation supports nested fields
python3 markdown-html/skills/design-system/scripts/onboard.py \
  --set brand.primary=#E63946            # colour
  --set typography.heading_font=Georgia  # font
  --set design_style=editorial           # style
  --set toc_behavior=none                # TOC
  --set syntax_theme=dark                # code blocks
```

To override in project scope only:
```bash
python3 markdown-html/skills/design-system/scripts/onboard.py \
  --scope project \
  --set brand.primary=#E63946
```

### Step 3 — Debug WCAG contrast failure (exit code 4)

```bash
# Check what contrast ratio the current primary achieves
python3 - <<'PYEOF'
def hex_to_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16)/255 for i in (0, 2, 4))

def luminance(c):
    return sum(
        (v/12.92 if v <= 0.04045 else ((v+0.055)/1.055)**2.4) * w
        for v, w in zip(c, [0.2126, 0.7152, 0.0722])
    )

def contrast(hex1, hex2):
    L1, L2 = sorted([luminance(hex_to_rgb(h)) for h in [hex1, hex2]], reverse=True)
    return (L1 + 0.05) / (L2 + 0.05)

primary = "#F5A623"  # replace with your primary
print(f"Contrast on white: {contrast(primary, '#FFFFFF'):.2f}:1")
print(f"Contrast on black: {contrast(primary, '#000000'):.2f}:1")
print("WCAG AA body text requires: ≥4.5:1")
PYEOF
```

Fixes:
- Darken primary: shift value down in HSL
- Leave `brand.bg` and `brand.text` blank to let auto-derivation pick a passing pair
- Explicitly set `brand.text=#000000` to force dark text on a light primary

### Step 4 — Reset a scope

```bash
# Reset global config (back to built-in defaults)
python3 markdown-html/skills/design-system/scripts/onboard.py --reset --scope global

# Reset project config only
python3 markdown-html/skills/design-system/scripts/onboard.py --reset --scope project

# Verify reset
python3 markdown-html/skills/design-system/scripts/config_loader.py --show \
  | grep "scope\|primary"
```

### Step 5 — CI / headless config diagnosis

```bash
# Check whether MARKDOWN_HTML_NO_CONFIG is unexpectedly set
echo "MARKDOWN_HTML_NO_CONFIG=${MARKDOWN_HTML_NO_CONFIG:-not set}"

# If set to 1, config is ignored → unset or check .env / CI variables
# Never set MARKDOWN_HTML_NO_CONFIG=1 silently for interactive users

# Verify config is readable in the CI environment
python3 markdown-html/skills/design-system/scripts/config_loader.py --status
```

### Checklist

- [ ] Effective config inspected with `--show` (right scope active?)
- [ ] Specific key(s) overridden with `--set`
- [ ] WCAG contrast failure diagnosed if exit code 4 occurs
- [ ] `config_loader.py --status` returns OK after fix
- [ ] Smoke-test conversion runs without errors
- [ ] `MARKDOWN_HTML_NO_CONFIG` not accidentally set in CI

## Verification

```bash
# Effective config has expected values
python3 markdown-html/skills/design-system/scripts/config_loader.py --show \
  | grep -E "primary|heading_font|design_style|wcag_status"

# Status OK
python3 markdown-html/skills/design-system/scripts/config_loader.py --status \
  | grep -i "OK"

# Test conversion
python3 markdown-html/skills/markdown-html/scripts/convert.py README.md \
  && grep -i "color\|font" markdown-html-out/README.html | head -5
```

**Exit criterion:** `config_loader.py --status` returns OK, conversion produces HTML, WCAG status is `pass`.

## Examples

### Example 1 — Brand primary changed, output still shows old colour

```bash
# Diagnose
python3 markdown-html/skills/design-system/scripts/config_loader.py --show | grep primary
# Found: brand.primary: #0066CC  ← old colour

# Project scope may have stale override
ls .markdown-html/design-system.json   # exists → project scope is active

# Update project scope
python3 markdown-html/skills/design-system/scripts/onboard.py \
  --scope project --set brand.primary=#E63946

# Verify
python3 markdown-html/skills/design-system/scripts/config_loader.py --show | grep primary
# Expected: brand.primary: #E63946
```

### Example 2 — WCAG failure after brand update

```bash
# New primary #FFD700 (gold) fails contrast on white (ratio ~1.07:1)
python3 markdown-html/skills/design-system/scripts/onboard.py --set brand.primary=#FFD700
# Exit code 4: WCAG AA body-text contrast fails (1.07 < 4.5)

# Fix: force dark text colour for this primary
python3 markdown-html/skills/design-system/scripts/onboard.py \
  --set brand.primary=#FFD700 \
  --set brand.text=#1A1A1A

# Verify
python3 markdown-html/skills/design-system/scripts/config_loader.py --status
# Expected: wcag_status: pass (body text #1A1A1A on #FFD700 = 8.3:1)
```

### Example 3 — Isolate project config from global

```bash
# Global config has editorial style; this repo needs technical style
python3 markdown-html/skills/design-system/scripts/onboard.py \
  --scope project \
  --set design_style=technical \
  --set toc_behavior=sticky-sidebar

# Confirm project scope takes precedence
python3 markdown-html/skills/design-system/scripts/config_loader.py --show \
  | grep -E "scope|design_style"
# Expected: scope: project | design_style: technical
```

## Anti-patterns / Known gotchas

| Anti-pattern | Why it hurts | Fix |
|---|---|---|
| Re-running full wizard to change one key | Overwrites all other config; resets unwanted defaults | Use `--set key=value` for targeted overrides |
| Resetting global when project scope is the problem | Affects all repos; doesn't fix project issue | Target the right scope: `--reset --scope project` |
| Ignoring scope resolution order | Unexpected config takes effect from wrong scope | Always check `--show` after any change |
| WCAG failure fixed by ignoring it via `brand.text` without checking | Resulting contrast may still fail | Calculate and verify the actual ratio |
| Setting `MARKDOWN_HTML_NO_CONFIG=1` and forgetting | All subsequent runs ignore config | Only set in ephemeral CI runs; unset immediately after |
| Logo URL pointing to a resource that requires auth | base64 embedding fails silently | Use public URL or local path |

## Boundaries / Scope

**In scope:**
- Inspecting effective config and scope resolution
- Targeted key overrides with `--set` (no full re-run needed)
- WCAG contrast diagnosis and remediation
- Scope management (project vs global vs defaults)
- CI / headless environment config debugging

**Out of scope:**
- First-time wizard setup (use onboarding-design-system skill)
- Markdown-to-HTML conversion
- Frontend design token generation
- Component library auditing
