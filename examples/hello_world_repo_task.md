# Walkthrough: a goal from `agentos plan` to a merged branch

This traces one real run so the pieces in the README are concrete. The goal:

```bash
agentos run "Add a /healthz endpoint that checks DB connectivity" --repo ~/code/some-api
```

## 1. Planning

`agentos/planner.py` sends the goal, the agent roster, and the phase list to
`planner-agent` (`claude-opus-5`) with `output_format` constrained to
`PLAN_SCHEMA`. A representative result, after the engine resolves
`local_id`s into real `task_id`s:

```
task_a1b2c3d4e5  [planning     ] product-agent    deps=-                What "healthy" means: DB reachable...
task_f6g7h8i9j0  [architecture ] architect-agent  deps=task_a1b2c3d4e5  Decide check strategy: ping vs...
task_k1l2m3n4o5  [development  ] developer-agent  deps=task_f6g7h8i9j0  Implement GET /healthz...
task_p6q7r8s9t0  [review       ] qa-agent         deps=task_k1l2m3n4o5  Run test suite against...
task_u1v2w3x4y5  [release      ] release-agent    deps=task_p6q7r8s9t0  Commit + release...
```

`agentos plan` prints exactly this and stops — nothing has touched the
target repo yet. Worth running on its own for anything non-trivial, per the
README's "read the plan before trusting the run" note.

## 2. Orchestration, phase by phase

**`planning`** activates `product-agent`'s roster. Its task has no
dependencies, so it runs immediately: reads the repo, writes down what
"healthy" should mean here (DB reachable within N ms, HTTP 200/503), what's
out of scope (no auth on this endpoint, no dependent-service checks yet).
Its `validators` list is empty by design for a planning-phase task in this
example — see the note in `evaluation.py`: a task with no validators is an
automatic FAIL, so in a real registry entry you'd normally still name at
least one reviewer. Assume this one names `research-agent` as validator;
it reviews and returns `## Verdict\nPASS`. Task → `COMPLETED`. Not a code
change, so `_release()` finds nothing to commit and cleans up without
opening a branch.

**`architecture`** activates once `planning`'s task is `COMPLETED`.
`architect-agent` (`claude-opus-5`) picks a strategy (a lightweight
`SELECT 1` on the existing pool, 500ms timeout, no new dependency) and
writes it down; `security-agent` validates — checks it doesn't leak
connection details in the response body — PASS.

**`development`** activates. `developer-agent` (`delegated` tier)
implements the endpoint and a test. Its task's `validators` are
`[qa-agent]`. `qa-agent` gets its own SDK session with a **different**
task: "independently review task ...'s output," including the implementer's
own summary, but instructed not to trust it — it runs the real test suite
itself and reports `## Verdict\nPASS` with the command output attached, per
the `code-review` skill's required shape.

**`release`** activates. `release-agent` (`autonomous` tier) runs
`git_ops.create_feature_branch` → `agent-os/task_k1l2m3n4o5`,
`commit_all`, `push_branch`. Then `permissions.can_promote()`:

- tier `autonomous`: `promote_without_human = True`
- task_type: `"staging_deploy"` — in `promotable_task_types`
- risk_level: `"low"`

All three clear → `approvals.auto_approve()` records the decision (visible
later via `agentos approvals --all`) and the branch is left pushed,
unmerged, for CI/staging to pick up. If the task's `task_type` had been
`"production_deploy"` or `risk_level: "high"`, the same tier would instead
land in `approvals.request()` — a `PENDING` row — and the run continues to
report it in its final summary rather than blocking on it.

## 3. What a human sees afterward

```bash
$ agentos status --repo ~/code/some-api
run 20260820T091500Z-a1b2c3  goal: 'Add a /healthz endpoint that checks DB connectivity'
tasks: {'completed': 5}

0 pending approval(s):
```

If a task type had needed a human instead:

```bash
$ agentos approvals --repo ~/code/some-api
appr_9f8e7d6c5b  pending  [high] promote (task task_u1v2w3x4y5) — promote task_u1v2w3x4y5 (agent-os/task_u1v2w3x4y5) — risk_level 'high' always requires human approval

$ agentos approve appr_9f8e7d6c5b --repo ~/code/some-api --reason "reviewed the diff, looks right"
appr_9f8e7d6c5b: APPROVED
merged agent-os/task_u1v2w3x4y5 into main (a1b2c3d4)
```

## What would have stopped the run early

- Any task's SDK session erroring twice past `max_retries` → `ESCALATED`,
  which `phase_engine.phase_tasks_stuck()` catches at the end of that
  phase's loop, and the orchestrator stops rather than starting the next
  phase.
- The run's total SDK cost crossing `limits.max_budget_usd_per_run` in
  `config/policy.yaml` (default `$20`) — checked before every task, not
  just at phase boundaries.
- A validator disagreeing — evaluation requires *every* validator to say
  PASS, so one FAIL sends the task to `retry_or_escalate`, not to release.
