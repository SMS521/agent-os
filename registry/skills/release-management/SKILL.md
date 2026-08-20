---
skill_id: release-management
name: Release Management
description: Commit validated work to a feature branch and decide, per policy.yaml, whether it can be promoted without a human.
required_tools: [Read, Bash, Grep, Glob]
risk_level: high
phase: release
---

# Release Management

Use this skill only after a task has an `APPROVED` evaluation report — never
before. Committing unreviewed work is not this skill's job.

## Do

- Commit to a feature/research branch via `agentos.git_ops`, never straight
  to `main` — `git_commit_main` is `false` at every autonomy tier, always,
  regardless of what `config/policy.yaml` otherwise grants.
- Check the task's `task_type` against `promotable_task_types` in
  `config/policy.yaml` and its `risk_level`. Both conditions must hold —
  listed type **and** not `high` risk — before you may auto-promote; either
  one failing means you open it for human approval and stop there.
- Write a commit message that says what changed and why, not what tool
  produced it.
- Record the promotion decision either way (auto-promoted, or waiting on
  approval `<id>`) so the run's state file shows what happened and who
  decided it.

## Don't

- Don't merge to `main`, deploy to production, or exceed
  `limits.max_budget_usd_per_run` — all of those are in
  `human_approval_required` unconditionally.
- Don't reinterpret an ambiguous `risk_level` upward into eligibility. If
  it's not clearly low/medium and clearly in `promotable_task_types`,
  default to asking a human.

## Output shape

```
## Committed
- branch: <name>, commit: <sha>

## Promotion
auto-promoted (task_type=<x>, risk_level=<y>) | awaiting human approval <approval_id>
```
