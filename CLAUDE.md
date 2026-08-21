# Working on agent-os

## Standing rule: announce, explain, wait — every time

Before running `agentos run`, `agentos approve`, or any other command that
lets a registered agent write files, run shell commands, commit, push, or
promote/deploy against a target repo, a Claude session operating this
system must, in the chat, in this order:

1. **State the plan** — what is about to happen, concretely (which
   command, against which repo, which agents/tasks it touches).
2. **State why** — what it's for and what the expected result is.
3. **Wait for an explicit yes** before executing.

This holds **per action, not per conversation.** An approval for one step
does not carry forward to the next one — a "go ahead" on `agentos plan`
does not authorize the `agentos run` that follows it, and approval for one
`agentos run` does not authorize a second one, even on the same goal or
the same repo. Ask again every time, plainly, without assuming standing
consent.

This is stricter than (and takes precedence over) the general "confirm
before risky actions" judgment call a Claude session would otherwise make
on its own — here it is not a judgment call, it is a fixed rule the user
set explicitly on 2026-08-20.

`agentos plan` (read-only — `planner-agent` only has `Read`/`Grep`/`Glob`,
never touches the target repo) does not need this same gate to be run once
to *see* a plan, but still say what you're about to plan and why before
running it, and do not chain straight into `agentos run` on its output
without a fresh, separate yes.

## What this doesn't change

`config/policy.yaml`'s autonomy tiers and the Human Approval System
(`agentos/approvals.py`) still govern what a *registered agent* may do
without a human once a run is underway (see README's "Autonomy tiers").
This CLAUDE.md rule is a layer above that: it governs whether the
orchestrating Claude session is allowed to *start* a run or approve a
queued request at all, not what happens inside one once started.

**This rule does not bind the individual agent sessions a run spawns**
(`product-agent`, `developer-agent`, `qa-agent`, `release-agent`, etc.).
Each is a single non-interactive SDK session with no chat channel back to
a human mid-task; if one tries to "wait for an explicit yes" the way this
file describes, it cannot receive an answer and fails its task by doing
nothing instead. That happened for real on 2026-08-21 against
`financial-event-radar`: `product-agent` read that repo's `CLAUDE.md`,
applied this exact rule to itself, and spent all three of its attempts
asking permission instead of doing its (harmless, read-only) job, until
QA/review correctly failed and escalated it. A target repo's own
`CLAUDE.md`, if it states an equivalent rule, needs the same carve-out —
see `financial-event-radar/CLAUDE.md` for the corrected version.
