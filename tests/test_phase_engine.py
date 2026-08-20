from agentos.models import Phase, PhaseStatus, Task, TaskStatus
from agentos.phase_engine import PhaseEngine
from agentos.task_engine import TaskGraph


def make_engine() -> PhaseEngine:
    phases = {
        "planning": Phase(id="planning", description="p", roster=["product-agent"]),
        "development": Phase(id="development", description="d", roster=["developer-agent", "qa-agent"]),
        "release": Phase(id="release", description="r", roster=["release-agent"]),
    }
    return PhaseEngine(phases=phases, sequence=["planning", "development", "release"])


def test_next_phase_walks_sequence():
    eng = make_engine()
    assert eng.next_phase(None) == "planning"
    assert eng.next_phase("planning") == "development"
    assert eng.next_phase("development") == "release"
    assert eng.next_phase("release") is None


def test_activate_and_complete_toggles_status_and_active_set():
    eng = make_engine()
    eng.activate("planning")
    assert eng.phases["planning"].status == PhaseStatus.ACTIVE
    assert "product-agent" in eng.active_roster()

    eng.complete("planning")
    assert eng.phases["planning"].status == PhaseStatus.COMPLETE
    assert "product-agent" not in eng.active_roster()


def test_is_agent_active_only_within_active_phases():
    eng = make_engine()
    assert not eng.is_agent_active("developer-agent")
    eng.activate("development")
    assert eng.is_agent_active("developer-agent")
    assert not eng.is_agent_active("release-agent")


def test_phase_tasks_complete_true_when_no_tasks_staffed():
    eng = make_engine()
    graph = TaskGraph()
    assert eng.phase_tasks_complete("development", graph) is True


def test_phase_tasks_complete_false_until_all_done():
    eng = make_engine()
    graph = TaskGraph()
    t1 = Task(description="x", owner_agent="developer-agent", phase="development")
    t2 = Task(description="y", owner_agent="qa-agent", phase="development")
    graph.add_many([t1, t2])

    assert eng.phase_tasks_complete("development", graph) is False
    graph.mark(t1.task_id, TaskStatus.COMPLETED)
    assert eng.phase_tasks_complete("development", graph) is False
    graph.mark(t2.task_id, TaskStatus.COMPLETED)
    assert eng.phase_tasks_complete("development", graph) is True


def test_phase_tasks_stuck_detects_escalated_or_blocked():
    eng = make_engine()
    graph = TaskGraph()
    t1 = Task(description="x", owner_agent="developer-agent", phase="development")
    graph.add_many([t1])
    assert eng.phase_tasks_stuck("development", graph) is False
    graph.mark(t1.task_id, TaskStatus.ESCALATED)
    assert eng.phase_tasks_stuck("development", graph) is True
