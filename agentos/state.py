"""Run state persistence — the continuity a fresh, unattended run needs.

One JSON file per run under <state_dir>/runs/<run_id>.json: the goal, every
task's final shape, and the orchestrator's log. `agentos status` reads this;
nothing else in the package depends on its exact shape, so it's safe to
widen later.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Optional

from agentos.task_engine import TaskGraph


def new_run_id() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:6]


class RunStateStore:
    def __init__(self, state_dir: Path):
        self.dir = state_dir / "runs"
        self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, run_id: str, goal: str, graph: TaskGraph, log_lines: list[str]) -> Path:
        path = self.dir / f"{run_id}.json"
        payload = {
            "run_id": run_id,
            "goal": goal,
            "saved_at": time.time(),
            "tasks": {tid: t.model_dump(mode="json") for tid, t in graph.tasks.items()},
            "log": log_lines,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def load(self, run_id: str) -> dict:
        path = self.dir / f"{run_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"no such run: {run_id!r} (looked in {self.dir})")
        return json.loads(path.read_text(encoding="utf-8"))

    def latest_run_id(self) -> Optional[str]:
        files = sorted(self.dir.glob("*.json"))
        return files[-1].stem if files else None

    def list_runs(self) -> list[str]:
        return sorted(p.stem for p in self.dir.glob("*.json"))
