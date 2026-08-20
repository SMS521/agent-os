"""Human Approval System: a durable queue of approval requests.

Every gate the Permission Engine raises lands here — as a PENDING row a
human resolves with the CLI (`agentos approve <id>` / `agentos deny <id>`),
or, when policy.yaml's tier/task_type/risk_level all clear it, as an
AUTO_APPROVED row recorded for the audit trail rather than silently skipped.
"Preserve an auditable record of decisions and actions" (blueprint Sheet 10)
means even the actions nobody had to approve still show up here.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from agentos.models import ApprovalRequest, ApprovalStatus


class ApprovalQueue:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._requests: dict[str, ApprovalRequest] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        self._requests = {k: ApprovalRequest.model_validate(v) for k, v in raw.items()}

    def _save(self) -> None:
        data = {k: v.model_dump(mode="json") for k, v in self._requests.items()}
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def request(
        self, *, task_id: str, agent_id: str, action: str, description: str, risk_level: str = "medium"
    ) -> ApprovalRequest:
        req = ApprovalRequest(
            task_id=task_id, agent_id=agent_id, action=action,
            description=description, risk_level=risk_level,
        )
        self._requests[req.approval_id] = req
        self._save()
        return req

    def auto_approve(
        self, *, task_id: str, agent_id: str, action: str, description: str, reason: str, risk_level: str = "low"
    ) -> ApprovalRequest:
        req = ApprovalRequest(
            task_id=task_id, agent_id=agent_id, action=action, description=description,
            risk_level=risk_level, status=ApprovalStatus.AUTO_APPROVED,
            decided_by="policy.yaml", decided_at=time.time(), reason=reason,
        )
        self._requests[req.approval_id] = req
        self._save()
        return req

    def decide(
        self, approval_id: str, approved: bool, *, decided_by: str = "human", reason: Optional[str] = None
    ) -> ApprovalRequest:
        req = self._requests.get(approval_id)
        if req is None:
            raise KeyError(f"no such approval_id: {approval_id!r}")
        if req.status != ApprovalStatus.PENDING:
            raise ValueError(f"approval {approval_id!r} is already {req.status.value}, not pending")
        req.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED
        req.decided_by = decided_by
        req.decided_at = time.time()
        req.reason = reason
        self._save()
        return req

    def get(self, approval_id: str) -> ApprovalRequest:
        try:
            return self._requests[approval_id]
        except KeyError as exc:
            raise KeyError(f"no such approval_id: {approval_id!r}") from exc

    def pending(self) -> list[ApprovalRequest]:
        return [r for r in self._requests.values() if r.status == ApprovalStatus.PENDING]

    def all(self) -> list[ApprovalRequest]:
        return sorted(self._requests.values(), key=lambda r: r.created_at)
