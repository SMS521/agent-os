from pathlib import Path

import pytest

from agentos.registry import Registry, RegistryError

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_registry_loads_from_repo():
    reg = Registry.load(REPO_ROOT)
    assert "planner-agent" in reg.agents
    assert "developer-agent" in reg.agents
    assert reg.phase_sequence == ["planning", "architecture", "development", "review", "release"]
    assert reg.skills  # at least one skill loaded


def test_every_agent_skill_reference_resolves():
    reg = Registry.load(REPO_ROOT)
    for agent in reg.agents.values():
        for skill_id in agent.skills:
            assert skill_id in reg.skills, f"{agent.agent_id} references missing skill {skill_id}"


def test_every_phase_roster_agent_exists():
    reg = Registry.load(REPO_ROOT)
    for phase in reg.phases.values():
        for agent_id in phase.roster:
            assert agent_id in reg.agents, f"phase {phase.id} roster references missing agent {agent_id}"


def test_roster_for_phase_helper():
    reg = Registry.load(REPO_ROOT)
    dev_roster = reg.roster_for_phase("development")
    assert {a.agent_id for a in dev_roster} == {"developer-agent", "qa-agent"}


def test_skills_for_agent_helper():
    reg = Registry.load(REPO_ROOT)
    skills = reg.skills_for_agent("developer-agent")
    assert [s.skill_id for s in skills] == ["code-implementation"]


def test_unknown_agent_raises(tmp_path):
    reg = Registry.load(REPO_ROOT)
    with pytest.raises(RegistryError):
        reg.get_agent("does-not-exist")


def test_duplicate_agent_id_rejected(tmp_path):
    from agentos.registry import load_agents

    bad = tmp_path / "agents.yaml"
    bad.write_text(
        """
agents:
  - agent_id: dup
    role: A
    system_prompt: x
  - agent_id: dup
    role: B
    system_prompt: y
"""
    )
    with pytest.raises(RegistryError):
        load_agents(bad)


def test_skill_without_frontmatter_rejected(tmp_path):
    from agentos.registry import load_skills

    skills_dir = tmp_path / "skills"
    (skills_dir / "broken").mkdir(parents=True)
    (skills_dir / "broken" / "SKILL.md").write_text("no frontmatter here")
    with pytest.raises(RegistryError):
        load_skills(skills_dir)
