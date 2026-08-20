from pathlib import Path

import pytest

from agentos.models import AgentSpec, Task
from agentos.permissions import PermissionEngine, PolicyError, classify_action

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_engine() -> PermissionEngine:
    return PermissionEngine.load(REPO_ROOT / "config" / "policy.yaml")


def make_agent(agent_id="developer-agent", autonomy="delegated", tools=None) -> AgentSpec:
    return AgentSpec(
        agent_id=agent_id, role="x", tools=tools or ["Read", "Bash"],
        autonomy=autonomy, system_prompt="do things",
    )


def make_task(**kw) -> Task:
    return Task(description="x", owner_agent="developer-agent", phase="development", **kw)


def test_policy_file_loads_and_has_expected_tiers():
    eng = load_engine()
    assert set(eng.tiers) == {"supervised", "delegated", "autonomous"}


def test_git_commit_main_must_be_false_everywhere():
    # invariant enforced at load time, not just by convention
    eng = load_engine()
    assert all(not t.git_commit_main for t in eng.tiers.values())


def test_unknown_tier_raises():
    eng = load_engine()
    agent = make_agent(autonomy="made-up-tier")
    with pytest.raises(PolicyError):
        eng.tier_for(agent)


def test_supervised_tier_requires_approval_for_feature_branch_commit():
    eng = load_engine()
    agent = make_agent(autonomy="supervised")
    task = make_task()
    decision = eng.check_tool_call(agent, task, "Bash", {"command": "git commit -m x"})
    assert decision.allowed is False
    assert decision.requires_human_approval is True


def test_delegated_tier_allows_feature_branch_commit():
    eng = load_engine()
    agent = make_agent(autonomy="delegated")
    task = make_task()
    decision = eng.check_tool_call(agent, task, "Bash", {"command": "git commit -m x"})
    assert decision.allowed is True


def test_commit_to_main_always_requires_approval_even_at_delegated_tier():
    eng = load_engine()
    agent = make_agent(autonomy="delegated")
    task = make_task()
    decision = eng.check_tool_call(agent, task, "Bash", {"command": "git commit -m x on main"})
    assert decision.allowed is False
    assert decision.requires_human_approval is True


def test_push_to_main_always_requires_approval():
    eng = load_engine()
    agent = make_agent(autonomy="autonomous")
    task = make_task()
    decision = eng.check_tool_call(agent, task, "Bash", {"command": "git push origin main"})
    assert decision.allowed is False
    assert decision.action == "git_push_main"


def test_editing_policy_file_itself_always_requires_approval():
    eng = load_engine()
    agent = make_agent(autonomy="autonomous")
    task = make_task()
    decision = eng.check_tool_call(agent, task, "Edit", {"file_path": "config/policy.yaml"})
    assert decision.allowed is False
    assert decision.action == "modify_this_policy_file"


def test_ordinary_read_is_always_allowed():
    eng = load_engine()
    agent = make_agent(autonomy="supervised")
    task = make_task()
    decision = eng.check_tool_call(agent, task, "Read", {"file_path": "README.md"})
    assert decision.allowed is True


def test_can_promote_requires_autonomous_tier():
    eng = load_engine()
    task = make_task(task_type="research_finding", risk_level="low")

    supervised = make_agent(autonomy="supervised")
    assert eng.can_promote(supervised, task).allowed is False

    autonomous = make_agent(autonomy="autonomous")
    assert eng.can_promote(autonomous, task).allowed is True


def test_can_promote_denied_for_high_risk_even_at_autonomous_tier():
    eng = load_engine()
    agent = make_agent(autonomy="autonomous")
    task = make_task(task_type="research_finding", risk_level="high")
    decision = eng.can_promote(agent, task)
    assert decision.allowed is False
    assert "risk_level" in decision.reason


def test_can_promote_denied_for_task_type_not_listed():
    eng = load_engine()
    agent = make_agent(autonomy="autonomous")
    task = make_task(task_type="production_deploy", risk_level="low")
    decision = eng.can_promote(agent, task)
    assert decision.allowed is False


def test_max_tasks_per_cycle_by_tier():
    eng = load_engine()
    assert eng.max_tasks_per_cycle(make_agent(autonomy="supervised")) == 1
    assert eng.max_tasks_per_cycle(make_agent(autonomy="delegated")) > 1


def test_classify_action_git_push_feature_branch_is_not_a_named_action():
    assert classify_action("Bash", {"command": "git push origin agent-os/task_1"}) is None


def test_load_rejects_missing_file(tmp_path):
    with pytest.raises(PolicyError):
        PermissionEngine.load(tmp_path / "nope.yaml")


def test_load_rejects_tier_with_git_commit_main_true(tmp_path):
    bad = tmp_path / "policy.yaml"
    bad.write_text(
        """
autonomy_tiers:
  reckless:
    git_commit_main: true
human_approval_required: []
promotable_task_types: []
"""
    )
    with pytest.raises(PolicyError):
        PermissionEngine.load(bad)
