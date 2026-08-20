"""Phase Engine: the phase state machine and per-phase agent rosters.

Reads config/phases.yaml (via registry.py) once, then tracks which phases
are live for the current run. "Roster" is a ceiling — who's *eligible* this
phase, per the Orchestrator, which still only activates an agent when the
Task Engine has a ready task for it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from agentos.models import Phase, PhaseStatus, TaskStatus
from agentos.task_engine import TaskGraph


class PhaseEngineError(Exception):
    pass


@dataclass
class PhaseEngine:
    phases: dict[str, Phase]
    sequence: list[str]
    _active: set[str] = field(default_factory=set)

    def activate(self, phase_id: str) -> Phase:
        phase = self._get(phase_id)
        phase.status = PhaseStatus.ACTIVE
        self._active.add(phase_id)
        return phase

    def complete(self, phase_id: str) -> Phase:
        phase = self._get(phase_id)
        phase.status = PhaseStatus.COMPLETE
        self._active.discard(phase_id)
        return phase

    def active_phases(self) -> list[Phase]:
        return [self.phases[p] for p in self._active]

    def roster(self, phase_id: str) -> list[str]:
        return list(self._get(phase_id).roster)

    def active_roster(self) -> set[str]:
        """Every agent_id eligible under any currently-active phase — this is
        what the Orchestrator checks before staffing an agent, and what
        `agentos status` prints as 'who's on the clock right now'."""
        out: set[str] = set()
        for phase_id in self._active:
            out.update(self.phases[phase_id].roster)
        return out

    def is_agent_active(self, agent_id: str) -> bool:
        return agent_id in self.active_roster()

    def phase_tasks_complete(self, phase_id: str, graph: TaskGraph) -> bool:
        tasks = graph.for_phase(phase_id)
        if not tasks:
            return True  # nothing was staffed into this phase (yet) — not a block
        return all(t.status == TaskStatus.COMPLETED for t in tasks)

    def phase_tasks_stuck(self, phase_id: str, graph: TaskGraph) -> bool:
        tasks = graph.for_phase(phase_id)
        return any(t.status in (TaskStatus.ESCALATED, TaskStatus.BLOCKED) for t in tasks)

    def next_phase(self, current: Optional[str]) -> Optional[str]:
        if current is None:
            return self.sequence[0] if self.sequence else None
        if current not in self.sequence:
            return None
        idx = self.sequence.index(current)
        return self.sequence[idx + 1] if idx + 1 < len(self.sequence) else None

    def _get(self, phase_id: str) -> Phase:
        try:
            return self.phases[phase_id]
        except KeyError as exc:
            raise PhaseEngineError(f"no such phase id: {phase_id!r}") from exc
