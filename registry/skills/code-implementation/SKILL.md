---
skill_id: code-implementation
name: Code Implementation
description: Implement exactly the task given, with tests, without unrequested refactors or speculative abstraction.
required_tools: [Read, Write, Edit, Bash, Grep, Glob]
risk_level: medium
phase: development
---

# Code Implementation

Use this skill to turn one task from the DAG into working code.

## Do

- Implement exactly the task's `description` and `outputs` — nothing the
  task didn't ask for, no matter how tempting the adjacent cleanup looks.
- Write or update tests for what you touched. A task without a test that
  can fail is a task nobody can verify is still done six months from now.
- When you believe the task is complete, state that explicitly and stop.
  Say what you did and why it satisfies the task's `outputs` — the QA and
  Reviewer agents validate independently; you are not grading your own
  work by asserting "done" louder.
- Respect the repository's own conventions (existing patterns, lint config,
  commit style) over your own defaults.

## Don't

- Don't refactor code outside the task's scope, add abstractions for
  hypothetical future tasks, or add error handling for states that can't
  occur here. Three similar lines beat a premature abstraction.
- Don't touch `main` or push anything — that's the Release agent's job,
  gated by `config/policy.yaml`.
- Don't silently work around a failing test or a blocked dependency by
  loosening the thing that's failing. A red test is information.

## Output shape

```
## Changed
- <file> — <what and why, one line>

## Tests
- <what you added/updated, and that it passes>

## Done means
<restate the task's `outputs`, and confirm each is satisfied>
```
