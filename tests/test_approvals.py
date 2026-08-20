import pytest

from agentos.approvals import ApprovalQueue
from agentos.models import ApprovalStatus


def test_request_then_decide_round_trips_through_disk(tmp_path):
    path = tmp_path / "approvals.json"
    queue = ApprovalQueue(path)

    req = queue.request(task_id="t1", agent_id="release-agent", action="promote", description="ship it")
    assert req.status == ApprovalStatus.PENDING
    assert len(queue.pending()) == 1

    # reload from disk to prove persistence, not just in-memory state
    reloaded = ApprovalQueue(path)
    assert len(reloaded.pending()) == 1

    reloaded.decide(req.approval_id, approved=True, decided_by="human", reason="looks good")
    assert reloaded.pending() == []

    again = ApprovalQueue(path)
    decided = again.get(req.approval_id)
    assert decided.status == ApprovalStatus.APPROVED
    assert decided.decided_by == "human"
    assert decided.reason == "looks good"


def test_auto_approve_is_recorded_not_silently_skipped(tmp_path):
    queue = ApprovalQueue(tmp_path / "approvals.json")
    req = queue.auto_approve(
        task_id="t1", agent_id="release-agent", action="promote",
        description="auto", reason="policy cleared it",
    )
    assert req.status == ApprovalStatus.AUTO_APPROVED
    assert req.decided_by == "policy.yaml"
    assert req in queue.all()
    assert req not in queue.pending()


def test_deny_sets_status(tmp_path):
    queue = ApprovalQueue(tmp_path / "approvals.json")
    req = queue.request(task_id="t1", agent_id="a", action="git_push_main", description="x")
    queue.decide(req.approval_id, approved=False, reason="not yet")
    assert queue.get(req.approval_id).status == ApprovalStatus.DENIED


def test_cannot_decide_twice(tmp_path):
    queue = ApprovalQueue(tmp_path / "approvals.json")
    req = queue.request(task_id="t1", agent_id="a", action="x", description="y")
    queue.decide(req.approval_id, approved=True)
    with pytest.raises(ValueError):
        queue.decide(req.approval_id, approved=True)


def test_unknown_approval_id_raises(tmp_path):
    queue = ApprovalQueue(tmp_path / "approvals.json")
    with pytest.raises(KeyError):
        queue.get("nope")
    with pytest.raises(KeyError):
        queue.decide("nope", approved=True)
