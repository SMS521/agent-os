"""Agent Registry + Skill Registry loaders.

Both registries are plain files on disk, on purpose — adding an agent or a
skill is a YAML entry / a new folder, not a code change. This module only
reads and validates them into the models from models.py; it never decides
who runs when (that's phase_engine.py + orchestrator.py) and never decides
what's allowed (that's permissions.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from agentos.models import AgentSpec, Phase, SkillSpec


class RegistryError(Exception):
    """Raised for a malformed registry file — fail loudly, not with a KeyError later."""


def _parse_skill_frontmatter(text: str, skill_dir: Path) -> dict:
    """Parse a SKILL.md's YAML front matter (the Anthropic Agent Skills format:
    a `---`-delimited YAML block at the top of the file, prose body after)."""
    if not text.startswith("---"):
        raise RegistryError(
            f"{skill_dir}/SKILL.md has no YAML front matter (must start with '---')"
        )
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise RegistryError(f"{skill_dir}/SKILL.md front matter is not closed with '---'")
    meta = yaml.safe_load(parts[1]) or {}
    if not isinstance(meta, dict):
        raise RegistryError(f"{skill_dir}/SKILL.md front matter must be a YAML mapping")
    return meta


def load_skills(skills_dir: Path) -> dict[str, SkillSpec]:
    """Load every registry/skills/<id>/SKILL.md into a SkillSpec keyed by skill_id."""
    skills: dict[str, SkillSpec] = {}
    if not skills_dir.exists():
        return skills

    for entry in sorted(skills_dir.iterdir()):
        skill_md = entry / "SKILL.md"
        if not entry.is_dir() or not skill_md.exists():
            continue
        meta = _parse_skill_frontmatter(skill_md.read_text(encoding="utf-8"), entry)
        skill_id = meta.get("skill_id", entry.name)
        try:
            skills[skill_id] = SkillSpec(
                skill_id=skill_id,
                name=meta.get("name", skill_id),
                description=meta.get("description", ""),
                required_tools=meta.get("required_tools", []) or [],
                risk_level=meta.get("risk_level", "low"),
                phase=meta.get("phase"),
                path=str(skill_md.parent),
            )
        except Exception as exc:  # pydantic ValidationError etc.
            raise RegistryError(f"invalid SKILL.md at {skill_md}: {exc}") from exc

    return skills


def load_agents(agents_yaml: Path) -> dict[str, AgentSpec]:
    """Load registry/agents.yaml into AgentSpecs keyed by agent_id."""
    if not agents_yaml.exists():
        raise RegistryError(f"agent registry not found: {agents_yaml}")

    raw = yaml.safe_load(agents_yaml.read_text(encoding="utf-8")) or {}
    entries = raw.get("agents", [])
    if not isinstance(entries, list):
        raise RegistryError(f"{agents_yaml}: top-level 'agents' must be a list")

    agents: dict[str, AgentSpec] = {}
    for entry in entries:
        try:
            spec = AgentSpec(**entry)
        except Exception as exc:
            agent_id = entry.get("agent_id", "<unknown>") if isinstance(entry, dict) else "<unknown>"
            raise RegistryError(f"invalid agent entry {agent_id!r} in {agents_yaml}: {exc}") from exc
        if spec.agent_id in agents:
            raise RegistryError(f"duplicate agent_id {spec.agent_id!r} in {agents_yaml}")
        agents[spec.agent_id] = spec

    return agents


def load_phases(phases_yaml: Path) -> tuple[dict[str, Phase], list[str]]:
    """Load config/phases.yaml into Phases keyed by id, plus the default sequence."""
    if not phases_yaml.exists():
        raise RegistryError(f"phase config not found: {phases_yaml}")

    raw = yaml.safe_load(phases_yaml.read_text(encoding="utf-8")) or {}
    entries = raw.get("phases", [])
    sequence = raw.get("default_sequence", [])

    phases: dict[str, Phase] = {}
    for entry in entries:
        try:
            phase = Phase(**entry)
        except Exception as exc:
            phase_id = entry.get("id", "<unknown>") if isinstance(entry, dict) else "<unknown>"
            raise RegistryError(f"invalid phase entry {phase_id!r} in {phases_yaml}: {exc}") from exc
        if phase.id in phases:
            raise RegistryError(f"duplicate phase id {phase.id!r} in {phases_yaml}")
        phases[phase.id] = phase

    missing = [p for p in sequence if p not in phases]
    if missing:
        raise RegistryError(f"default_sequence references unknown phase(s): {missing}")

    return phases, sequence


@dataclass
class Registry:
    """Convenience façade combining agents, skills and phases for the rest of the system."""

    agents: dict[str, AgentSpec] = field(default_factory=dict)
    skills: dict[str, SkillSpec] = field(default_factory=dict)
    phases: dict[str, Phase] = field(default_factory=dict)
    phase_sequence: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, root: Path) -> "Registry":
        agents = load_agents(root / "registry" / "agents.yaml")
        skills = load_skills(root / "registry" / "skills")
        phases, sequence = load_phases(root / "config" / "phases.yaml")

        # Cross-check: every skill an agent claims must exist in the skill registry.
        for agent in agents.values():
            unknown = [s for s in agent.skills if s not in skills]
            if unknown:
                raise RegistryError(
                    f"agent {agent.agent_id!r} references unknown skill(s) {unknown}"
                )

        # Cross-check: every agent named in a phase roster must exist in the agent registry.
        for phase in phases.values():
            unknown = [a for a in phase.roster if a not in agents]
            if unknown:
                raise RegistryError(
                    f"phase {phase.id!r} roster references unknown agent(s) {unknown}"
                )

        return cls(agents=agents, skills=skills, phases=phases, phase_sequence=sequence)

    def get_agent(self, agent_id: str) -> AgentSpec:
        try:
            return self.agents[agent_id]
        except KeyError as exc:
            raise RegistryError(f"no such agent_id: {agent_id!r}") from exc

    def get_skill(self, skill_id: str) -> SkillSpec:
        try:
            return self.skills[skill_id]
        except KeyError as exc:
            raise RegistryError(f"no such skill_id: {skill_id!r}") from exc

    def skills_for_agent(self, agent_id: str) -> list[SkillSpec]:
        return [self.skills[s] for s in self.get_agent(agent_id).skills]

    def roster_for_phase(self, phase_id: str) -> list[AgentSpec]:
        try:
            phase = self.phases[phase_id]
        except KeyError as exc:
            raise RegistryError(f"no such phase id: {phase_id!r}") from exc
        return [self.agents[a] for a in phase.roster]
