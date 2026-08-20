# agent-os

A general-purpose multi-agent orchestration system: a Planner turns a goal
into a phase/task DAG, an Orchestrator staffs registered agents against it
one phase at a time, every task goes through independent evaluation before
it counts as done, and a Permission Engine decides — per agent, per action —
whether that can happen unattended or needs a human. Built on the
[Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview).

It is domain-agnostic: point `--repo` at any git repository and describe a
goal. The registry ships with a generic software-delivery agent roster
(product → architecture → development → review → release); add your own
agents and skills for other domains without touching the engine.

## Architecture

```
   goal
    │
    ▼
 Planner (agentos/planner.py) ── one SDK session, output_format = JSON schema
    │
    ▼
 Task DAG (agentos/task_engine.py) ── validated: no cycles, no dangling deps
    │
    ▼
 Orchestrator (agentos/orchestrator.py)
    │
    ├─ Phase Engine (agentos/phase_engine.py) ── activates one phase's roster at a time
    │
    ├─ for each ready task ─────────────────────────────────────────────┐
    │     Runtime (agentos/runtime.py) runs the owning agent's SDK      │
    │     session — system prompt + its skills' full SKILL.md bodies + │
    │     the task — gated live by the Permission Engine's can_use_tool │
    │                                                                    │
    │     Evaluation (agentos/evaluation.py) — every agent in the       │
    │     task's `validators` independently reviews the result;         │
    │     PASS requires all of them to agree, never the implementer's   │
    │     own word                                                      │
    │                                                                    │
    │     Release — commit_all to a feature branch (agentos/git_ops.py),│
    │     then Permission Engine.can_promote() decides auto-promote vs.  │
    │     a queued ApprovalRequest (agentos/approvals.py)                │
    └────────────────────────────────────────────────────────────────────┘
    │
    ▼
 next phase, or stop (a task is BLOCKED/ESCALATED, or the run's budget ceiling is hit)
```

Eight subsystems, each its own module:

| Subsystem | Module | What it owns |
|---|---|---|
| Agent Registry | `agentos/registry.py`, `registry/agents.yaml` | who the agents are: role, skills, tools, model, autonomy tier |
| Skill Registry | `agentos/registry.py`, `registry/skills/*/SKILL.md` | what each agent knows how to do, in the [Anthropic Agent Skills](https://github.com/anthropics/skills) format |
| Task Engine | `agentos/task_engine.py` | the task contract, the DAG, lifecycle transitions (created → running → review → approved → completed / retry / escalated / blocked) |
| Phase Engine | `agentos/phase_engine.py`, `config/phases.yaml` | which agents are eligible to run right now |
| Orchestrator | `agentos/orchestrator.py` | walks the DAG, staffs agents, drives release |
| Permission Engine | `agentos/permissions.py`, `config/policy.yaml` | what's allowed, and whether it needs a human — see **Autonomy tiers** below |
| Human Approval System | `agentos/approvals.py`, `agentos/cli.py` | the queue; `agentos approvals` / `approve` / `deny` |
| Evaluation System | `agentos/evaluation.py` | independent PASS/FAIL before a task is ever released |

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env   # fill in ANTHROPIC_API_KEY
```

See only what the Planner would do, without running any agent:

```bash
agentos plan "Add a /healthz endpoint that checks DB connectivity" --repo /path/to/target/repo
```

Run it end to end — plans, staffs agents phase by phase, evaluates, releases:

```bash
agentos run "Add a /healthz endpoint that checks DB connectivity" --repo /path/to/target/repo
```

Check on approvals and run status any time, including mid-run from another shell:

```bash
agentos status --repo /path/to/target/repo
agentos approvals --repo /path/to/target/repo
agentos approve <approval_id> --repo /path/to/target/repo --reason "reviewed the diff"
agentos deny <approval_id> --repo /path/to/target/repo --reason "not yet"
```

`--repo` (or `$AGENTOS_WORKDIR`) is the target codebase agents read and
write in. The agent/skill/policy registry always loads from *this*
agent-os checkout — one installation can point at many target repos.

## Autonomy tiers

`config/policy.yaml` defines three tiers. An agent's `autonomy` field in
`registry/agents.yaml` (or a per-agent override in `policy.yaml`) picks one:

| Tier | Commit to feature branch | Multiple tasks per unattended run | Promote/deploy without a human |
|---|---|---|---|
| `supervised` (default) | needs approval | no — one task, then stop | no |
| `delegated` | yes | yes | no |
| `autonomous` | yes | yes | **yes**, but only for task types listed in `promotable_task_types` and only when `risk_level != high` |

**One invariant holds at every tier, enforced in two places, not just
config:** nothing ever commits, merges, or pushes to `main` without a human
running `agentos approve` — `policy.yaml` fails to load if any tier sets
`git_commit_main: true`, and `git_ops.merge_to_main()` refuses to run
without an explicit `human_confirmed=True` that only the CLI's approve path
sets.

`autonomous` is a real risk surface. Before widening `promotable_task_types`
or moving more agents onto it, read what each field actually gates in
`permissions.py`'s `can_promote()` and `check_tool_call()` — the shipped
defaults promote `research_finding` and `staging_deploy` only, deliberately
leaving `production_deploy` off the list.

Every promotion decision is recorded in the approval queue whether or not a
human made it — `AUTO_APPROVED` rows carry `decided_by: "policy.yaml"` and
the reason, so the audit trail shows what happened even when nobody had to
act.

## Extending

**Add an agent:** one entry in `registry/agents.yaml` (`agent_id`, `role`,
`tools`, `model`, `autonomy`, `system_prompt`) plus, usually, a skill.
**Add a skill:** a folder under `registry/skills/<id>/SKILL.md` with YAML
front matter (`skill_id`, `name`, `description`, `required_tools`,
`risk_level`, `phase`) and prose instructions below it — the whole body
gets loaded into an agent's system prompt when the agent has that skill.
**Add a phase:** an entry in `config/phases.yaml`'s `phases` list, plus its
id in `default_sequence`.

None of this touches `agentos/`'s code — the engine is data-driven on
purpose, matching the blueprint principle it implements: adding a role is a
registry edit, not a redesign.

## Known limitations (v0.1)

- **Tasks within one phase run sequentially**, not in parallel — they share
  one working tree, and getting a correct DAG walk right came before
  concurrency. True parallel execution needs per-task `git worktree`s; add
  it as its own scoped change if you need it, rather than growing
  `orchestrator.py` in place.
- **`agentos approve` only automates one action type** — a `promote`
  approval merges to `main` for you; every other gated action (a manual
  `git push`, a production deploy) is recorded as approved, and carrying it
  out is on you. Wiring more action types to real automation is
  straightforward but deliberately not done until something needs it.
- **The Planner's output quality depends on the underlying model** reading
  the registry correctly — `planner.py` validates every task's
  `owner_agent` and `phase` against the real registry and raises
  `PlannerError` rather than silently accepting a hallucinated agent name,
  but a plan that's *technically valid* and *strategically bad* is still
  possible. Read `agentos plan`'s output before trusting `agentos run`.
- **`can_use_tool` denials don't yet feed back into a live session** — a
  denied tool call writes a `PENDING` approval and the session moves on
  (or fails the task); approving it later doesn't retroactively unblock
  that same running session, only a subsequent run.

## Testing

```bash
pip install -e ".[dev]" 2>/dev/null || pip install -r requirements-dev.txt
pytest
```

The suite (`tests/`) covers every deterministic subsystem — registry
loading and cross-checks, the task DAG (cycles, blocking cascades, retry →
escalate), the phase engine, the permission engine against the real
`config/policy.yaml`, the approval queue's persistence, and `git_ops`
against real temporary git repositories. It does not call the Claude Agent
SDK — `agentos/runtime.py`, `planner.py`'s SDK call, and `evaluation.py`'s
agent-review path are exercised by running the CLI against a real
`ANTHROPIC_API_KEY`, not by the automated suite.

See `examples/hello_world_repo_task.md` for a walkthrough of what an actual
`agentos run` looks like, phase by phase.
