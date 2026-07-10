---
name: managing-git-dag-branches
description: >
  Manage git branches for multi-agent collaboration using a DAG (directed acyclic graph)
  model — structured naming, worktree isolation, frontier detection, merge strategies,
  and tag-based archival. Keeps parallel agent work immutable, traceable, and garbage-
  collection-safe while enabling clean winner selection and history replay.
  Use when: running a multi-agent coding session, evaluating parallel agent branches,
  selecting and merging the winning attempt, or recovering from a failed session.
  Do not use for: standard single-developer git workflows, rebase-based histories, or
  GitHub PR review workflows without agent parallelism.
---

## When to use

- Orchestrating N parallel agents on the same task in isolated git worktrees
- Detecting which branches are "frontier" (latest agent work, no children yet)
- Choosing a merge strategy after evaluating agent outputs
- Archiving losing branches without losing their commit objects
- Visualizing parallel agent DAG for debugging or auditing

## When NOT to use

- Single-developer linear workflow — normal `feature/` branches work fine
- Using `git rebase` as the standard history strategy (DAG model assumes no rewrites)
- GitHub PR-based workflows where agents push to shared remotes
- You don't have multiple parallel agents; orchestrate a single agent instead

## Quick start

```bash
# Create isolated worktrees for agents (each shares the .git store)
SESSION="$(date +%Y%m%d-%H%M%S)"
for i in 1 2 3; do
  git worktree add /tmp/hub-agent-$i \
    -b "hub/${SESSION}/agent-${i}/attempt-1"
done

# After agents complete — check frontier (branch tips with no children)
git log --all --oneline --graph --decorate --branches="hub/${SESSION}/*"

# Merge winner (no-ff preserves branch topology)
git merge --no-ff "hub/${SESSION}/agent-2/attempt-1"

# Archive losers via tags, then delete branch refs
for i in 1 3; do
  git tag "hub/archive/${SESSION}/agent-${i}" "hub/${SESSION}/agent-${i}/attempt-1"
  git branch -D "hub/${SESSION}/agent-${i}/attempt-1"
done

# Clean up worktrees
for i in 1 2 3; do git worktree remove /tmp/hub-agent-$i; done
```

## Workflow

### 1. Branch naming convention

```
hub/{session-id}/agent-{N}/attempt-{M}
```

| Component | Format | Example |
|---|---|---|
| `session-id` | `YYYYMMDD-HHMMSS` | `20260628-143022` |
| `agent-N` | sequential integer | `agent-1`, `agent-2` |
| `attempt-M` | retry counter, starts at 1 | `attempt-1`, `attempt-2` |

This creates queryable namespaces:
- `hub/*` — all hub work ever
- `hub/{session}/*` — all work for one session
- `hub/{session}/agent-{N}/*` — all attempts by one agent

### 2. Worktree isolation

```bash
# Each agent gets its own working directory but shares the .git object store
git worktree add /tmp/hub-agent-1 -b hub/${SESSION}/agent-1/attempt-1
git worktree add /tmp/hub-agent-2 -b hub/${SESSION}/agent-2/attempt-1

# Key properties:
# - Agents cannot check out the same branch simultaneously
# - Commits in one worktree are immediately visible to others via git log
# - Object store is shared — no duplication
```

### 3. Frontier detection

The **frontier** = branch tips that are NOT ancestors of any other tip. These represent the latest, un-merged work.

```bash
# Manual check: is branch A an ancestor of branch B?
git merge-base --is-ancestor hub/${S}/agent-1/attempt-1 hub/${S}/agent-2/attempt-1 \
  && echo "agent-1 is ancestor (superseded)" || echo "agent-1 is on frontier"

# Visual frontier: all tips at once
git log --all --oneline --graph --decorate --branches="hub/${SESSION}/*"
```

### 4. Merge strategies

| Strategy | Command | When |
|---|---|---|
| **No-fast-forward** | `git merge --no-ff <branch>` | Default; preserves branch topology in DAG |
| **Squash** | `git merge --squash <branch>` | Agent made many small noise commits |
| **Cherry-pick** | `git cherry-pick <sha>` | Only some of an agent's commits are wanted |

```bash
# No-ff creates a merge commit showing which agent produced the work
git merge --no-ff hub/${SESSION}/agent-2/attempt-1 \
  -m "Merge: agent-2 wins session ${SESSION} — replaced O(n²) with hash map"
```

### 5. Archive losers, never delete

```bash
# Tags are immutable and survive git GC (unlike branch refs)
git tag hub/archive/${SESSION}/agent-1 hub/${SESSION}/agent-1/attempt-1
git tag hub/archive/${SESSION}/agent-3 hub/${SESSION}/agent-3/attempt-1

# Now safe to delete branch refs (commits still reachable via tags)
git branch -D hub/${SESSION}/agent-1/attempt-1
git branch -D hub/${SESSION}/agent-3/attempt-1

# Verify commits still accessible
git show hub/archive/${SESSION}/agent-1 --stat
```

### 6. Immutability rules

1. **Never rebase agent branches** — rewrites SHAs, breaks frontier detection
2. **Never force-push** — could overwrite another agent's work
3. **Never amend agent commits** — history is append-only
4. **Never delete without tagging first** — always create the archive tag before deleting the branch ref
5. **Board (`.agenthub/board/`) is append-only** — new files only, never edit existing posts

### Checklist

- [ ] Session ID is timestamp-based, unique per run
- [ ] Each agent has its own worktree at a separate filesystem path
- [ ] No two worktrees check out the same branch
- [ ] All agents complete before evaluation begins
- [ ] Loser branches tagged before branch refs deleted
- [ ] Worktrees removed after merge

## Verification (exit criterion)

```bash
SESSION="<your-session-id>"

# All agent branches exist
git branch --list "hub/${SESSION}/*" | wc -l

# No agent branches left after archival (should be 0)
git branch --list "hub/${SESSION}/*" | wc -l
# (run after cleanup — expect 0)

# Archive tags exist for losers
git tag --list "hub/archive/${SESSION}/*"

# Winner merge commit visible in main history
git log --oneline --first-parent | head -5

# No orphan worktrees remain
git worktree list | grep "hub-agent" && echo "WARN orphan worktrees" || echo "PASS clean"

# Loser commits still reachable via tags
git show hub/archive/${SESSION}/agent-1 --format="%H %s" -s && echo "PASS commit preserved"
```

## Examples

### Example 1: Three agents, one winner

```bash
# Setup
SESSION="20260628-160000"
for i in 1 2 3; do
  git worktree add /tmp/hub-$i -b "hub/${SESSION}/agent-${i}/attempt-1" HEAD
done

# [agents do their work in /tmp/hub-1, /tmp/hub-2, /tmp/hub-3]
# [evaluator picks agent-2 as winner]

# Merge winner
git merge --no-ff "hub/${SESSION}/agent-2/attempt-1" -m "Merge: agent-2 wins"

# Archive losers
for i in 1 3; do
  git tag "hub/archive/${SESSION}/agent-${i}" "hub/${SESSION}/agent-${i}/attempt-1"
  git branch -D "hub/${SESSION}/agent-${i}/attempt-1"
done
git branch -D "hub/${SESSION}/agent-2/attempt-1"

# Cleanup
for i in 1 2 3; do git worktree remove /tmp/hub-$i --force; done
```

### Example 2: Re-spawn on failure

Agent 1 failed (compile error, no meaningful commit). Create attempt-2:

```bash
git worktree add /tmp/hub-agent-1-r2 \
  -b "hub/${SESSION}/agent-1/attempt-2" HEAD
# Re-dispatch agent to /tmp/hub-agent-1-r2
```

## Anti-patterns / Known gotchas

| Anti-pattern | Rebuttal |
|---|---|
| **Rebasing agent branches** | Rebase rewrites SHAs. The evaluator compares `git diff base...branch` — after rebase, `base` may no longer be a real ancestor and the diff is meaningless. Always merge or cherry-pick. |
| **Deleting branch without tagging** | Git GC will eventually collect unreachable commits. Tags are immutable pointers that survive GC. Tag first, always. |
| **Checking out same branch in two worktrees** | Git refuses this. Each worktree needs its own branch. The `attempt-M` suffix exists for retries; always create a new branch name. |
| **Evaluating before all agents complete** | Partial evaluation compares finished work against in-progress work. Wait for every Agent tool call to return before scoring. |
| **Force-push on shared agent branches** | Overwrites history other agents or the evaluator already read. The DAG must be append-only. |

## Boundaries / Scope

**In scope:**
- Branch naming conventions for multi-agent sessions
- Git worktree creation, isolation, and cleanup
- Frontier detection algorithms and git log visualization
- Merge strategies (no-ff / squash / cherry-pick) with selection guidance
- Tag-based archival of losing branches

**Out of scope:**
- Evaluating agent output quality (that is the coordinator's job)
- GitHub PR creation or remote push workflows
- Single-agent or single-developer git workflows
- Conflict resolution when two agents edit the same file (design to avoid this via task decomposition)
