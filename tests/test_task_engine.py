import pytest

from agentos.models import Task, TaskStatus
from agentos.task_engine import TaskEngineError, TaskGraph


def make_task(task_id_suffix: str, deps: list[str] | None = None, **kw) -> Task:
    t = Task(description=f"task {task_id_suffix}", owner_agent="developer-agent", phase="development", **kw)
    t.task_id = f"task_{task_id_suffix}"
    if deps:
        t.dependencies = deps
    return t


def test_ready_tasks_respects_dependencies():
    graph = TaskGraph()
    a = make_task("a")
    b = make_task("b", deps=["task_a"])
    graph.add_many([a, b])

    assert [t.task_id for t in graph.ready_tasks()] == ["task_a"]

    graph.mark("task_a", TaskStatus.COMPLETED)
    assert [t.task_id for t in graph.ready_tasks()] == ["task_b"]


def test_cycle_detected():
    graph = TaskGraph()
    a = make_task("a", deps=["task_b"])
    b = make_task("b", deps=["task_a"])
    graph.tasks[a.task_id] = a
    graph.tasks[b.task_id] = b
    with pytest.raises(TaskEngineError, match="cycle"):
        graph.validate()


def test_unknown_dependency_rejected():
    graph = TaskGraph()
    a = make_task("a", deps=["task_missing"])
    with pytest.raises(TaskEngineError):
        graph.add_many([a])


def test_self_dependency_rejected():
    graph = TaskGraph()
    a = make_task("a")
    a.dependencies = [a.task_id]
    with pytest.raises(TaskEngineError):
        graph.add_many([a])


def test_propagate_blocked_cascades_transitively():
    graph = TaskGraph()
    a = make_task("a")
    b = make_task("b", deps=["task_a"])
    c = make_task("c", deps=["task_b"])
    graph.add_many([a, b, c])

    graph.mark("task_a", TaskStatus.ESCALATED)
    blocked = graph.propagate_blocked()

    assert {t.task_id for t in blocked} == {"task_b", "task_c"}
    assert graph.tasks["task_b"].status == TaskStatus.BLOCKED
    assert graph.tasks["task_c"].status == TaskStatus.BLOCKED


def test_retry_then_escalate():
    graph = TaskGraph()
    a = make_task("a")
    a.max_retries = 1
    graph.add_many([a])

    status = graph.retry_or_escalate("task_a", "boom")
    assert status == TaskStatus.CREATED
    assert graph.tasks["task_a"].retry_count == 1

    status = graph.retry_or_escalate("task_a", "boom again")
    assert status == TaskStatus.ESCALATED
    assert graph.tasks["task_a"].retry_count == 2


def test_is_complete_only_when_all_terminal():
    graph = TaskGraph()
    a = make_task("a")
    graph.add_many([a])
    assert not graph.is_complete()
    graph.mark("task_a", TaskStatus.COMPLETED)
    assert graph.is_complete()


def test_summary_counts_by_status():
    graph = TaskGraph()
    graph.add_many([make_task("a"), make_task("b")])
    graph.mark("task_a", TaskStatus.COMPLETED)
    assert graph.summary() == {"created": 1, "completed": 1}


def test_duplicate_task_id_rejected():
    graph = TaskGraph()
    a = make_task("a")
    a2 = make_task("a")
    graph.add(a)
    with pytest.raises(TaskEngineError):
        graph.add(a2)
