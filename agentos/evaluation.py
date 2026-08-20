"""Evaluation loop: independent validation before a task counts as done
(blueprint Sheet 09). Every agent in `task.validators` gets its own SDK
session reviewing the repository state the implementer left behind — never
the implementing agent grading its own work. A task only reaches APPROVED
when every validator's report says PASS.
"""

from __future__ import annotations

import re
from pathlib import Path

from agentos.approvals import ApprovalQueue
from agentos.models import EvaluationReport, Task
from agentos.permissions import PermissionEngine
from agentos.registry import Registry
from agentos.runtime import RunResult, run_agent_task

_VERDICT_RE = re.compile(r"##\s*verdict\s*\n\s*(pass|fail)", re.IGNORECASE)


def parse_verdict(output: str | None) -> bool:
    """Looks for the '## Verdict\\nPASS|FAIL' shape the code-review and
    security-review skills specify, falling back to a bare PASS/FAIL line.
    Anything unparseable is a FAIL, not a PASS — an evaluator that didn't
    clearly say PASS did not clear the task."""
    if not output:
        return False
    m = _VERDICT_RE.search(output)
    if m:
        return m.group(1).upper() == "PASS"
    for line in output.splitlines():
        stripped = line.strip().upper()
        if stripped == "PASS":
            return True
        if stripped == "FAIL":
            return False
    return False


async def evaluate(
    task: Task,
    implementer_result: RunResult,
    registry: Registry,
    repo_root: Path,
    permission_engine: PermissionEngine,
    approvals: ApprovalQueue,
) -> EvaluationReport:
    checks: dict[str, bool] = {}
    notes: list[str] = []

    if not task.validators:
        notes.append(
            "task declared no validators — automatic FAIL; every task needs "
            "at least one agent other than its own owner to review it"
        )
        return EvaluationReport(task_id=task.task_id, passed=False, checks=checks, notes="\n".join(notes))

    all_pass = True
    for validator_id in task.validators:
        if validator_id == task.owner_agent:
            checks[validator_id] = False
            notes.append(f"{validator_id}: skipped — a task's own owner cannot validate its own output")
            all_pass = False
            continue

        validator_agent = registry.get_agent(validator_id)
        review_task = Task(
            description=(
                f"Independently review task {task.task_id}'s output.\n\n"
                f"Original task: {task.description}\n"
                f"Expected outputs: {', '.join(task.outputs) or '(none declared)'}\n\n"
                f"Implementing agent's own summary of what it did:\n"
                f"{implementer_result.output or '(no output returned)'}\n\n"
                "Verify this against the actual repository state yourself — "
                "do not take the summary above as true without checking."
            ),
            owner_agent=validator_id,
            phase=task.phase,
            risk_level=task.risk_level,
            task_type=task.task_type,
        )
        skills = registry.skills_for_agent(validator_id)
        result: RunResult = await run_agent_task(
            validator_agent, skills, review_task, repo_root, permission_engine, approvals
        )

        if not result.ok:
            checks[validator_id] = False
            notes.append(f"{validator_id}: session failed — {result.error}")
            all_pass = False
            continue

        passed = parse_verdict(result.output)
        checks[validator_id] = passed
        all_pass = all_pass and passed
        notes.append(f"{validator_id}: {'PASS' if passed else 'FAIL'}")

    return EvaluationReport(
        task_id=task.task_id,
        passed=all_pass,
        checks=checks,
        notes="\n".join(notes),
        reviewer_agent=", ".join(task.validators),
    )
