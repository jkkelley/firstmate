---
name: context-compaction
description: Distill a long session into a structured CONTEXT_STATE.md file to prevent context drift across sessions. Use when context usage exceeds 30%, before starting a new thread, or when architecture details feel stale.
user-invocable: true
metadata:
  internal: true
---

# Context Compaction Protocol

Produces and maintains a `CONTEXT_STATE.md` file at the project root.
This file is the single source of truth for the current session state.
It is not a summary of the conversation - it is a machine-readable state schema that any agent can hydrate from at the start of a new session.

## When to Invoke

- Context usage exceeds 30% (check with `/context`)
- You are about to start a new chat thread on the same project
- An agent produced output that contradicted a previous architectural decision
- You have completed a significant milestone and want to checkpoint

## Step 1 - Read Before Writing

Before producing any output, check whether `CONTEXT_STATE.md` already exists in the project root:

```bash
cat CONTEXT_STATE.md 2>/dev/null || echo "NO_EXISTING_STATE"
```

If it exists, load it.
You will diff proposed changes against it in Step 3 - never silently overwrite.

## Step 2 - Scan the Session

Scan the last 20+ messages and extract the following signal categories.
Discard everything else.

| Signal          | What to capture                                                         |
| --------------- | ----------------------------------------------------------------------- |
| Infrastructure  | IP addresses, node roles, hostnames, storage classes, ingress config    |
| Toolchain       | Active tools, versions, integrations (ArgoCD, Jenkins, ESO, etc.)       |
| Active tasks    | What is currently in progress, next pending action                      |
| Decisions made  | Architecture choices and the reason they were made                      |
| Lessons learned | Failed approaches - one line each: "X failed because Y; do not retry Z" |
| Blockers        | Unresolved issues with their last known state                           |

## Step 3 - Diff and Confirm Before Writing

If an existing `CONTEXT_STATE.md` was found, surface any fields that would change:

```
PROPOSED CHANGES TO CONTEXT_STATE.md:
  control_plane_ip: <previous-ip> → <new-ip>   ← CHANGED
  dns_server: (no change)
  active_task: (no change)

Confirm before updating? (yes / no / show full diff)
```

Do not write until the user confirms.
If there is no existing file, proceed directly to Step 4.

## Step 4 - Write CONTEXT_STATE.md

Write the file to the project root using this exact schema.
Do not add or remove top-level fields without user instruction.

```markdown
# CONTEXT_STATE.md

> Source of truth for AI session state. Feed this as the opening prompt of any new session.
> Do not edit manually unless re-validating against live infrastructure.

## Meta

| Field        | Value                    |
| ------------ | ------------------------ |
| last_updated | YYYY-MM-DD HH:MM UTC     |
| updated_by   | context-compaction skill |
| project      | <project name>           |
| repo         | <github.com/org/repo>    |

## Infrastructure

| Resource         | Value |
| ---------------- | ----- |
| control_plane_ip |       |
| worker_ips       |       |
| dns_server       |       |
| ingress          |       |
| storage          |       |
| registry         |       |
| dns_zone         |       |

## Toolchain

| Tool    | Role    | Notes           |
| ------- | ------- | --------------- |
| ArgoCD  | GitOps  |                 |
| Jenkins | CI      |                 |
| ESO     | Secrets | source: AWS SSM |
|         |         |                 |

## Active Tasks

| Priority | Task | Status      | Next Action |
| -------- | ---- | ----------- | ----------- |
| 1        |      | in_progress |             |
| 2        |      | pending     |             |

## Decisions Made

| Date       | Decision | Reason |
| ---------- | -------- | ------ |
| YYYY-MM-DD |          |        |

## Lessons Learned

- YYYY-MM-DD: <issue X> failed because <Y>; do not retry <Z>

## Blockers

| Blocker | Last Known State | Owner |
| ------- | ---------------- | ----- |
|         |                  |       |

## Hydration Prompt

Copy-paste this at the start of a new session:

\`\`\`
Read CONTEXT_STATE.md in this project root before doing anything else.
Use the Infrastructure and Toolchain tables as ground truth.
Current focus: [replace with active task].
Do not suggest IP addresses, tool versions, or architecture patterns
that contradict CONTEXT_STATE.md without flagging the conflict first.
\`\`\`
```

## Step 5 - Commit the State File

After writing, commit immediately so the file has a git history.
Stale state is detectable by `git log`.

```bash
git add CONTEXT_STATE.md
git commit -m "chore: checkpoint session state via context-compaction"
```

If the project uses Conventional Commits with semantic-release, use `chore:` - this produces no version bump.

## Staleness Detection

Any agent reading `CONTEXT_STATE.md` should check the `last_updated` field.
If it is older than **7 days**, surface a warning before using it:

```
⚠ CONTEXT_STATE.md was last updated <N> days ago.
  Verify infrastructure fields before trusting them.
  Run the context-compaction skill to refresh.
```

## Wiring Into an Existing Project

To make Claude automatically load this state on every session, add one line to the project's `CLAUDE.md`:

```markdown
## Session State

See `CONTEXT_STATE.md` for current infrastructure state, active tasks, and lessons learned.
Read it before starting any task.
```

That's all.
Cursor loads `CLAUDE.md` automatically - the agent will see the pointer and read the state file without any further instruction from you.
