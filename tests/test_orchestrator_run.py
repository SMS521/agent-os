"""Tests for Orchestrator.run()'s phase-walking, including --stop-after.

An empty TaskGraph never has a ready task in any phase, so
_run_phase_to_completion() returns immediately without a live SDK call or
any git operation -- safe to exercise run() itself fully offline.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from agentos.approvals import ApprovalQueue
from agentos.models import PhaseStatus
from agentos.orchestrator import Orchestrator
from agentos.permissions import PermissionEngine
from agentos.registry import Registry
from agentos.task_engine import TaskGraph

REPO_ROOT = Path(__file__).resolve().parent.parent


def make_orchestrator(tmp_path: Path) -> Orchestrator:
    registry = Registry.load(REPO_ROOT)
    permissions = PermissionEngine.load(REPO_ROOT / "config" / "policy.yaml")
    approvals = ApprovalQueue(tmp_path / "approvals.json")
    graph = TaskGraph()  # empty on purpose -- no task ever runs
    return Orchestrator(registry, graph, permissions, approvals, tmp_path)


def test_run_without_stop_after_walks_every_phase(tmp_path: Path):
    orch = make_orchestrator(tmp_path)
    log = asyncio.run(orch.run())

    for phase_id in orch.registry.phase_sequence:
        assert orch.phases.phases[phase_id].status == PhaseStatus.COMPLETE
    assert "run finished" in str(log)


def test_stop_after_phase_halts_before_the_next_phase_activates(tmp_path: Path):
    orch = make_orchestrator(tmp_path)
    sequence = orch.registry.phase_sequence
    assert "architecture" in sequence and "development" in sequence

    asyncio.run(orch.run(stop_after_phase="architecture"))

    idx = sequence.index("architecture")
    for phase_id in sequence[: idx + 1]:
        assert orch.phases.phases[phase_id].status == PhaseStatus.COMPLETE

    for phase_id in sequence[idx + 1 :]:
        assert orch.phases.phases[phase_id].status == PhaseStatus.PENDING

    assert "stopping after phase 'architecture'" in str(orch.log)


def test_stop_after_last_phase_is_equivalent_to_no_stop_after(tmp_path: Path):
    orch = make_orchestrator(tmp_path)
    last_phase = orch.registry.phase_sequence[-1]

    asyncio.run(orch.run(stop_after_phase=last_phase))

    for phase_id in orch.registry.phase_sequence:
        assert orch.phases.phases[phase_id].status == PhaseStatus.COMPLETE
