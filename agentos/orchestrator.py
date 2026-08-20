"""Orchestrator: walks the phase/task DAG end to end (blueprint Sheet 02).

For each phase in sequence: activate its roster, run every ready task
through an agent session then the evaluation loop, release validated work to
a feature branch, and either auto-promote it or queue a human approval —
then move to the next phase. Tasks within a phase run one at a time,
deliberately: they share one working tree, and a v0.1 goal is a correct
sequential loop, not concurrent git checkouts racing each other. Sheet 11's
"give this its own scoped flow rather than growing this one" applies here
too — true parallel task execution would need per-task git worktrees, which
this version doesn't attempt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agentos.approvals import ApprovalQueue
from agentos.evaluation import evaluate
from agentos.git_ops import (
    GitOpsError,
    checkout,
    commit_all,
    create_feature_branch,
    delete_branch,
    push_branch,
)
from agentos.models import AgentSpec, Task, TaskStatus
from agentos.permissions import PermissionEngine
from agentos.phase_engine import PhaseEngine
from agentos.registry import Registry
from agentos.runtime import run_agent_task
from agentos.task_engine import TaskGraph


@dataclass
class RunLog:
    entries: list[str] = field(default_factory=list)

    def add(self, line: str) -> None:
        self.entries.append(line)

    def __str__(self) -> str:
        return "\n".join(self.entries)


class Orchestrator:
    def __init__(
        self,
        registry: Registry,
        graph: TaskGraph,
        permission_engine: PermissionEngine,
        approvals: ApprovalQueue,
        repo_root: Path,
    ):
        self.registry = registry
        self.graph = graph
        self.permissions = permission_engine
        self.approvals = approvals
        self.repo_root = repo_root
        self.phases = PhaseEngine(phases=dict(registry.phases), sequence=list(registry.phase_sequence))
        self.log = RunLog()
        self.spent_usd = 0.0

    async def run(self) -> RunLog:
        current = self.phases.next_phase(None)
        while current is not None:
            self.phases.activate(current)
            self.log.add(f"phase {current}: activated (roster: {self.phases.roster(current)})")

            await self._run_phase_to_completion(current)

            if self.phases.phase_tasks_stuck(current, self.graph):
                self.log.add(f"phase {current}: stuck (a task is BLOCKED or ESCALATED) — stopping run")
                break
            if self.spent_usd >= self.permissions.max_budget_usd_per_run:
                self.log.add(f"budget ceiling reached (${self.spent_usd:.2f}) — stopping run")
                break

            self.phases.complete(current)
            self.log.add(f"phase {current}: complete")
            current = self.phases.next_phase(current)

        self.log.add(f"run finished — {self.graph.summary()}")
        return self.log

    async def _run_phase_to_completion(self, phase_id: str) -> None:
        while True:
            self.graph.propagate_blocked()
            ready = self.graph.ready_tasks(phase=phase_id)
            if not ready:
                return
            for task in ready:
                if self.spent_usd >= self.permissions.max_budget_usd_per_run:
                    return
                await self._run_one_task(task)

    async def _run_one_task(self, task: Task) -> None:
        agent = self.registry.get_agent(task.owner_agent)
        skills = self.registry.skills_for_agent(task.owner_agent)

        self.graph.mark(task.task_id, TaskStatus.RUNNING)
        self.log.add(f"{task.task_id} ({agent.agent_id}): running — {task.description[:80]!r}")

        result = await run_agent_task(agent, skills, task, self.repo_root, self.permissions, self.approvals)
        if result.cost_usd:
            self.spent_usd += result.cost_usd

        if not result.ok:
            status = self.graph.retry_or_escalate(task.task_id, result.error or "unknown failure")
            self.log.add(f"{task.task_id}: FAILED ({result.error}) -> {status.value}")
            return

        self.graph.mark(task.task_id, TaskStatus.REVIEW, result=result.output)
        report = await evaluate(task, result, self.registry, self.repo_root, self.permissions, self.approvals)
        self.log.add(f"{task.task_id}: evaluation -> {'PASS' if report.passed else 'FAIL'} ({report.notes})")

        if not report.passed:
            status = self.graph.retry_or_escalate(task.task_id, f"evaluation failed:\n{report.notes}")
            self.log.add(f"{task.task_id}: -> {status.value}")
            return

        self.graph.mark(task.task_id, TaskStatus.APPROVED)
        await self._release(task, agent)

    async def _release(self, task: Task, agent: AgentSpec) -> None:
        """Commit validated work to a feature branch, then either auto-promote
        it (policy.yaml tier + task_type + risk_level all clear) or queue a
        human approval. A task with no file changes (a research/product/
        security task that only produced text) is COMPLETED without a
        commit — not every task type produces a git artifact."""
        branch = f"agent-os/{task.task_id}"
        try:
            create_feature_branch(self.repo_root, task.task_id)
        except GitOpsError as exc:
            self.log.add(f"{task.task_id}: could not create release branch ({exc}) — ESCALATED")
            self.graph.mark(task.task_id, TaskStatus.ESCALATED, error=str(exc))
            return

        try:
            sha = commit_all(self.repo_root, branch, f"{task.task_id}: {task.description[:72]}")
        except GitOpsError as exc:
            self.log.add(f"{task.task_id}: no file changes to release ({exc}) — COMPLETED, no commit")
            checkout(self.repo_root, "main")
            delete_branch(self.repo_root, branch, force=True)
            self.graph.mark(task.task_id, TaskStatus.COMPLETED)
            return

        try:
            push_branch(self.repo_root, branch)
            self.log.add(f"{task.task_id}: committed {sha[:8]} and pushed {branch}")
        except GitOpsError as exc:
            self.log.add(f"{task.task_id}: committed {sha[:8]} to {branch} locally, push failed ({exc})")

        try:
            checkout(self.repo_root, "main")
        except GitOpsError as exc:
            # The commit above already succeeded and is safe on `branch` regardless
            # of this — but leaving the tree on a feature branch would mean the
            # *next* task's agent starts from the wrong baseline. Log it loudly
            # rather than silently letting every subsequent task run on stale state.
            self.log.add(
                f"{task.task_id}: WARNING could not return to main after release ({exc}) — "
                f"working tree is still on {branch}, next task will start from there"
            )

        decision = self.permissions.can_promote(agent, task)
        if decision.allowed:
            self.approvals.auto_approve(
                task_id=task.task_id,
                agent_id=agent.agent_id,
                action="promote",
                description=f"promote {task.task_id} ({branch})",
                reason=decision.reason,
                risk_level=task.risk_level,
            )
            self.log.add(f"{task.task_id}: auto-promoted — {decision.reason}")
        else:
            req = self.approvals.request(
                task_id=task.task_id,
                agent_id=agent.agent_id,
                action="promote",
                description=f"promote {task.task_id} ({branch}) — {decision.reason}",
                risk_level=task.risk_level,
            )
            self.log.add(f"{task.task_id}: awaiting human approval {req.approval_id} — {decision.reason}")

        self.graph.mark(task.task_id, TaskStatus.COMPLETED)
