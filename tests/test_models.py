import pytest
from pydantic import ValidationError

from agentos.models import Task, TaskStatus


def test_invalid_risk_level_rejected():
    with pytest.raises(ValidationError):
        Task(description="x", owner_agent="a", phase="p", risk_level="extreme")


def test_terminal_statuses():
    assert TaskStatus.COMPLETED.is_terminal
    assert TaskStatus.ESCALATED.is_terminal
    assert TaskStatus.BLOCKED.is_terminal
    assert not TaskStatus.RUNNING.is_terminal
    assert not TaskStatus.CREATED.is_terminal


def test_touch_updates_timestamp():
    t = Task(description="x", owner_agent="a", phase="p")
    before = t.updated_at
    t.touch()
    assert t.updated_at >= before


def test_task_ids_are_unique_by_default():
    a = Task(description="x", owner_agent="a", phase="p")
    b = Task(description="y", owner_agent="a", phase="p")
    assert a.task_id != b.task_id
