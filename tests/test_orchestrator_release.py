"""Tests for Orchestrator._release()'s git housekeeping.

This doesn't touch the Claude Agent SDK (no live query() call), so it's
safe to exercise directly against a real temporary git repo, the same
pattern as test_git_ops.py.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from agentos.approvals import ApprovalQueue
from agentos.git_ops import current_branch
from agentos.models import Task, TaskStatus
from agentos.orchestrator import Orchestrator
from agentos.permissions import PermissionEngine
from agentos.registry import Registry
from agentos.task_engine import TaskGraph

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _run(root, "init", "-q", "-b", "main")
    _run(root, "config", "user.email", "test@example.com")
    _run(root, "config", "user.name", "Test")
    (root / "README.md").write_text("hello\n")
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "-m", "initial commit")
    return root


def make_orchestrator(repo: Path, tmp_path: Path) -> tuple[Orchestrator, Task]:
    registry = Registry.load(REPO_ROOT)
    permissions = PermissionEngine.load(REPO_ROOT / "config" / "policy.yaml")
    approvals = ApprovalQueue(tmp_path / "approvals.json")
    graph = TaskGraph()
    task = Task(description="add a file", owner_agent="developer-agent", phase="development", risk_level="low")
    graph.add(task)
    orch = Orchestrator(registry, graph, permissions, approvals, repo)
    return orch, task


def test_release_returns_to_main_after_successful_commit(repo: Path, tmp_path: Path):
    # Regression test: _release() used to leave the working tree checked
    # out on the just-created feature branch after a successful commit —
    # only the "nothing to commit" path returned to main. Found live: a
    # second task in the same run then operated with the wrong branch
    # checked out.
    orch, task = make_orchestrator(repo, tmp_path)
    agent = orch.registry.get_agent(task.owner_agent)

    (repo / "new_file.txt").write_text("content\n")
    asyncio.run(orch._release(task, agent))

    assert current_branch(repo) == "main"
    assert orch.graph.tasks[task.task_id].status == TaskStatus.COMPLETED


def test_release_with_no_changes_also_returns_to_main(repo: Path, tmp_path: Path):
    # The pre-existing "nothing to commit" path — confirm it still works
    # after the fix, not just the new success path.
    orch, task = make_orchestrator(repo, tmp_path)
    agent = orch.registry.get_agent(task.owner_agent)

    asyncio.run(orch._release(task, agent))

    assert current_branch(repo) == "main"
    assert orch.graph.tasks[task.task_id].status == TaskStatus.COMPLETED
