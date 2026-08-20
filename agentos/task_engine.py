"""Task Engine: the task DAG and its lifecycle transitions (blueprint Sheet 06).

A TaskGraph is deliberately dumb — it knows dependencies and status, nothing
about agents, models, or the SDK. The Orchestrator decides *when* to call
into it; this module only keeps the graph consistent when it does.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agentos.models import Task, TaskStatus


class TaskEngineError(Exception):
    """A malformed DAG (unknown dependency, cycle) — caught before any agent runs."""


@dataclass
class TaskGraph:
    tasks: dict[str, Task] = field(default_factory=dict)

    def add(self, task: Task) -> Task:
        if task.task_id in self.tasks:
            raise TaskEngineError(f"duplicate task_id: {task.task_id!r}")
        self.tasks[task.task_id] = task
        return task

    def add_many(self, tasks: list[Task]) -> None:
        for t in tasks:
            self.add(t)
        self.validate()

    def validate(self) -> None:
        """Every dependency must exist and the graph must be acyclic. Call this
        once after loading a batch of tasks — before any agent is staffed."""
        for t in self.tasks.values():
            for dep in t.dependencies:
                if dep not in self.tasks:
                    raise TaskEngineError(f"task {t.task_id!r} depends on unknown task {dep!r}")
            if t.task_id in t.dependencies:
                raise TaskEngineError(f"task {t.task_id!r} depends on itself")
        self._check_acyclic()

    def _check_acyclic(self) -> None:
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {tid: WHITE for tid in self.tasks}

        def visit(tid: str, stack: list[str]) -> None:
            if color[tid] == GRAY:
                cycle = " -> ".join(stack + [tid])
                raise TaskEngineError(f"dependency cycle: {cycle}")
            if color[tid] == BLACK:
                return
            color[tid] = GRAY
            for dep in self.tasks[tid].dependencies:
                visit(dep, stack + [tid])
            color[tid] = BLACK

        for tid in list(self.tasks):
            if color[tid] == WHITE:
                visit(tid, [])

    def propagate_blocked(self) -> list[Task]:
        """Mark CREATED tasks BLOCKED if any dependency failed or was escalated.
        Runs to a fixpoint in one call so a multi-level cascade is caught in one pass."""
        newly_blocked: list[Task] = []
        changed = True
        while changed:
            changed = False
            for t in self.tasks.values():
                if t.status != TaskStatus.CREATED:
                    continue
                deps = [self.tasks[d] for d in t.dependencies]
                if any(d.status in (TaskStatus.BLOCKED, TaskStatus.ESCALATED) for d in deps):
                    t.status = TaskStatus.BLOCKED
                    t.error = "upstream dependency failed or was escalated"
                    t.touch()
                    newly_blocked.append(t)
                    changed = True
        return newly_blocked

    def ready_tasks(self, phase: str | None = None) -> list[Task]:
        """CREATED tasks whose dependencies are all COMPLETED, optionally
        restricted to one phase (the Orchestrator only staffs one phase's
        roster at a time)."""
        out = []
        for t in self.tasks.values():
            if t.status != TaskStatus.CREATED:
                continue
            if phase is not None and t.phase != phase:
                continue
            deps = [self.tasks[d] for d in t.dependencies]
            if all(d.status == TaskStatus.COMPLETED for d in deps):
                out.append(t)
        return out

    def mark(self, task_id: str, status: TaskStatus, *, result: str | None = None, error: str | None = None) -> Task:
        t = self.tasks[task_id]
        t.status = status
        if result is not None:
            t.result = result
        if error is not None:
            t.error = error
        t.touch()
        return t

    def retry_or_escalate(self, task_id: str, error: str) -> TaskStatus:
        """A failed run either goes back to CREATED for another attempt, or,
        past max_retries, ESCALATED — a human has to look, per the blueprint's
        'never hide failures' / 'do not repeatedly retry without changing
        strategy' principles."""
        t = self.tasks[task_id]
        t.retry_count += 1
        t.error = error
        t.status = TaskStatus.ESCALATED if t.retry_count > t.max_retries else TaskStatus.CREATED
        t.touch()
        return t.status

    def is_complete(self) -> bool:
        return all(t.status.is_terminal for t in self.tasks.values())

    def for_phase(self, phase: str) -> list[Task]:
        return [t for t in self.tasks.values() if t.phase == phase]

    def summary(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for t in self.tasks.values():
            out[t.status.value] = out.get(t.status.value, 0) + 1
        return out
