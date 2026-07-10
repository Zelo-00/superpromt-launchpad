---
name: automating-workspace-workflows
description: >
  Catalog of 43 Google Workspace CLI (gws) recipe templates across 8 categories for
  automating Gmail, Drive, Calendar, Sheets, Chat, Tasks, and Admin workflows.
  Use when: automating a recurring Workspace task via gws, building a cross-service
  workflow, or looking up the right command for a specific Workspace operation.
  Do not use for: gws authentication setup, role-specific recipe bundling (see
  profiling-workspace-roles), or third-party Workspace integrations.
---

## When to use

- Automating a recurring Workspace task (send email, create event, update sheet)
- Building a cross-service workflow combining Calendar + Tasks + Chat
- Looking up the correct gws command for a specific Workspace operation

## When NOT to use

- gws not authenticated (`gws auth login` first)
- GUI-only Workspace operations (use Admin Console directly)
- Third-party integrations (Zapier, Make, Google Apps Script)

## Quick start

**Always verify syntax before using any recipe in production:**
```bash
gws <service> --help
gws schema <service>.<resource>.<method>
```

**⚠️ gws is pre-v1.0. Every recipe below is a verified command template — confirm exact syntax with `gws schema` before production use.**

**8 categories — 43 recipes total:**
| Category | Count |
|---|---|
| Email | 8 |
| Files | 7 |
| Calendar | 6 |
| Reporting | 5 |
| Collaboration | 5 |
| Data | 4 |
| Admin | 4 |
| Cross-Service | 4 |

## Workflow

### Email (8 recipes)

```bash
# send-email
gws gmail users.messages send me \
  --to "recipient@example.com" --subject "Subject" --body "Body text"

# reply-to-thread
gws gmail users.messages reply me --thread-id <THREAD_ID> --body "Reply text"

# forward-email
gws gmail users.messages forward me --message-id <MSG_ID> --to "forward@example.com"

# search-emails  (Gmail query syntax)
gws gmail users.messages list me \
  --query "from:client@example.com after:2026/01/01 is:unread" --json
# Query operators: is:unread | has:attachment | newer_than:7d | label:important

# unread-digest  (top 20 unread)
gws gmail users.messages list me --query "is:unread" --limit 20 --json

# label-manager
gws gmail users.labels list me --json
gws gmail users.labels create me --name "Projects/Alpha"

# filter-setup  (auto-label + archive)
gws gmail users.settings.filters create me \
  --criteria '{"from":"notifications@service.com"}' \
  --action '{"addLabelIds":["Label_123"],"removeLabelIds":["INBOX"]}'

# archive-old  (read emails older than 30 days)
gws gmail users.messages list me --query "is:read older_than:30d" --json
# Extract message IDs, then batch-modify to remove INBOX label
```

### Files (7 recipes)

```bash
# upload-file
gws drive files create --name "Report Q1" --upload report.pdf --parents <FOLDER_ID>

# create-sheet
gws sheets spreadsheets create --title "Budget 2026" --json

# share-file  (user write access)
gws drive permissions create <FILE_ID> \
  --type user --role writer --emailAddress "user@example.com"

# share-folder  (group write access)
gws drive permissions create <FOLDER_ID> \
  --type group --role writer --emailAddress "team@company.com"

# export-file  (Google Doc/Sheet → PDF)
gws drive files export <FILE_ID> --mime "application/pdf" --output report.pdf

# list-files  (in folder)
gws drive files list --parents <FOLDER_ID> --json

# find-large-files
gws drive files list --orderBy "quotaBytesUsed desc" --limit 20 --json

# cleanup-trash  (permanent — list first: gws drive files list --trashed)
gws drive files emptyTrash
```

### Calendar (6 recipes)

```bash
# create-event  (with attendees)
gws calendar events insert primary \
  --summary "Sprint Planning" \
  --start "2026-07-01T10:00:00" --end "2026-07-01T11:00:00" \
  --attendees "team@company.com" --location "Room A"

# today-schedule
gws calendar events list primary \
  --timeMin "$(date -u +%Y-%m-%dT00:00:00Z)" \
  --timeMax "$(date -u +%Y-%m-%dT23:59:59Z)" --json

# find-time  (freebusy query)
gws calendar freebusy query \
  --json '{"timeMin":"2026-07-01T09:00:00Z","timeMax":"2026-07-01T17:00:00Z",
           "items":[{"id":"colleague@company.com"}]}'
# Verify exact schema: gws schema calendar.freebusy.query

# reschedule
gws calendar events patch primary <EVENT_ID> \
  --start "2026-07-02T14:00:00" --end "2026-07-02T15:00:00"

# meeting-prep  (helper)
gws workflow +meeting-prep
# Output: agenda, attendees, related Drive files, previous notes

# quick-event  (natural language)
gws calendar +insert --help   # verify before using
```

### Reporting (5 recipes)

```bash
# standup-report  (yesterday + today + tasks + blockers)
gws workflow +standup-report

# weekly-summary
gws workflow +weekly-digest

# drive-activity
gws drive activities list --json

# email-stats  (last 7 days)
gws gmail users.messages list me --query "newer_than:7d" --json \
  | python3 output_analyzer.py --count

# task-progress
gws tasks tasks list <TASKLIST_ID> --json \
  | python3 output_analyzer.py --group-by "status"
```

### Collaboration (5 recipes)

```bash
# chat-message
gws chat spaces.messages create <SPACE_NAME> --text "Deployment complete: v1.4.2"

# list-spaces
gws chat spaces list --json

# create-doc
gws docs documents create --title "Meeting Notes - 2026-07-01" --json

# task-create
gws tasks tasks insert <TASKLIST_ID> --title "Review PR #42" --due "2026-07-05"

# share-folder  (see Files section above)
```

### Data (4 recipes)

```bash
# sheet-read
gws sheets spreadsheets.values get <SHEET_ID> --range "Sheet1!A1:D10" --json

# sheet-write  (update specific range)
gws sheets spreadsheets.values update <SHEET_ID> --range "Sheet1!A1" \
  --values '[["Name","Score"],["Alice",95],["Bob",87]]'

# sheet-append  (add rows)
gws sheets spreadsheets.values append <SHEET_ID> --range "Sheet1!A1" \
  --values '[["Charlie",92]]'

# export-contacts
gws people people.connections list me \
  --personFields names,emailAddresses --json
```

### Admin (4 recipes)

```bash
# list-users  (requires admin.directory.user.readonly scope)
gws admin users list --domain company.com --json

# list-groups  (requires admin.directory.group.readonly scope)
gws admin groups list --domain company.com --json

# user-info
gws admin users get user@company.com --json

# audit-logins
gws admin activities list login --json
```

### Cross-Service (4 recipes)

```bash
# morning-briefing  (calendar + gmail + tasks)
python3 scripts/gws_recipe_runner.py --run morning-briefing --dry-run
# Remove --dry-run to execute; --dry-run shows command sequence only

# eod-wrap  (completed + pending + tomorrow)
python3 scripts/gws_recipe_runner.py --run eod-wrap --dry-run

# project-status  (Drive + Sheets + Tasks aggregate)
python3 scripts/gws_recipe_runner.py --run project-status --dry-run

# inbox-zero  (label, archive, reply, or create task)
python3 scripts/gws_recipe_runner.py --run inbox-zero --dry-run
```

**Pre-automation checklist:**
- [ ] `gws auth status` returns authenticated
- [ ] Syntax verified with `gws schema` for non-helper commands
- [ ] IDs (`<FILE_ID>`, `<SHEET_ID>`, etc.) fetched programmatically, not hardcoded
- [ ] `--dry-run` used first on recipe runner commands
- [ ] Admin scope confirmed in GCP API console for admin recipes
- [ ] `cleanup-trash` preceded by `gws drive files list --trashed` review

## Verification (exit criterion)

```bash
# Auth check
gws auth status && echo "PASS" || echo "FAIL"

# Confirm email sent and retrievable
gws gmail users.messages list me --query "subject:TestSubject newer_than:1d" --json \
  | python -c "import sys,json; d=json.load(sys.stdin); assert d.get('messages')"

# Confirm sheet write
gws sheets spreadsheets.values get "$SHEET_ID" --range "Sheet1!A1" --json \
  | python -c "import sys,json; d=json.load(sys.stdin); assert d.get('values')"

# Confirm calendar event created
gws calendar events list primary \
  --timeMin "2026-07-01T00:00:00Z" --timeMax "2026-07-01T23:59:59Z" --json \
  | python -c "import sys,json; d=json.load(sys.stdin); assert d.get('items')"

# Confirm Chat message posted (space membership check)
gws chat spaces list --json | python -c \
  "import sys,json; spaces=json.load(sys.stdin); assert len(spaces.get('spaces',[])) > 0"
```

## Examples

**Example 1 — Deploy notification pipeline**
```bash
VERSION="v1.4.2"
SPACE="spaces/AAAA_BBB"
TASKLIST="<TASKLIST_ID>"

# Announce deploy
gws chat spaces.messages create "$SPACE" \
  --text "✅ Deploy $VERSION complete. Monitoring 15 min."

# Create follow-up verification task
gws tasks tasks insert "$TASKLIST" \
  --title "Verify $VERSION metrics post-deploy" \
  --due "$(date -u -d '+1 hour' +%Y-%m-%dT%H:%M:%SZ)"
```

**Example 2 — Morning briefing script (manual)**
```bash
#!/bin/bash
# Today's events
gws calendar events list primary \
  --timeMin "$(date -u +%Y-%m-%dT00:00:00Z)" \
  --timeMax "$(date -u +%Y-%m-%dT23:59:59Z)" --json | jq '.items[].summary'

# Unread count
gws gmail users.messages list me --query "is:unread" --json \
  | jq '.resultSizeEstimate // 0'

# Pending tasks
gws tasks tasks list <TASKLIST_ID> --json \
  | jq '[.items[]? | select(.status=="needsAction")] | length'
```

## Anti-patterns / Known gotchas

| Anti-pattern | Rebuttal |
|---|---|
| Copying recipes without `gws schema` verification | gws is pre-v1.0; parameter names change without notice; verify before production use |
| Hardcoding `<FILE_ID>` or `<FOLDER_ID>` in scripts | IDs differ across environments; always fetch dynamically at runtime |
| Piping `--json` without null-guarding | Some calls return `{}` not `{"items":[]}` on empty results; guard with `.get("items", [])` |
| Running `filter-setup` without testing criteria first | A badly configured filter archives critical emails immediately; test on a label first |
| Admin recipes without scope verification | 403 errors return no useful message; confirm scopes in GCP API console first |
| `gws drive files emptyTrash` without reviewing contents | Drive trash deletion is permanent; always `list --trashed` before emptying |

## Boundaries / Scope

**In scope:**
- 43 gws CLI recipe templates across 8 categories
- Pre-v1.0 syntax verification guidance for all recipes
- Cross-service workflow patterns (multi-service automation)
- Admin scope requirements per recipe

**Out of scope:**
- Role-specific bundling (see `profiling-workspace-roles`)
- gws CLI authentication setup
- Google Apps Script automation
- Third-party Workspace integrations (Zapier, Make)
