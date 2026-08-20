"""Permission Engine: config/policy.yaml -> allow/deny + approval-required.

This is the one module every risky action passes through, whether it's a
live tool call an agent is about to make (`check_tool_call`, wired into the
SDK's `can_use_tool` callback in runtime.py) or a promotion decision at the
end of a task (`can_promote`, used by release-management). Nothing here
grants a tool an agent's registry.py entry doesn't already list — this only
narrows further and decides who has to sign off.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from agentos.models import AgentSpec, Task


class PolicyError(Exception):
    """A malformed or self-contradictory policy.yaml — fail at load time, not mid-run."""


@dataclass
class TierPolicy:
    name: str
    git_commit_feature_branch: bool = False
    git_commit_main: bool = False
    multi_task_per_cycle: bool = False
    promote_without_human: bool = False
    description: str = ""


@dataclass
class Decision:
    allowed: bool
    requires_human_approval: bool
    reason: str = ""
    action: Optional[str] = None


# Tool calls this engine recognizes as carrying a named, policy-relevant
# "action" (from human_approval_required / promotable_task_types). Anything
# not matched here is allowed as an ordinary in-scope tool call, subject
# only to the agent's own `tools` list from the registry.
def classify_action(tool_name: str, input_data: dict) -> Optional[str]:
    if tool_name in ("Write", "Edit"):
        path = str(input_data.get("file_path") or input_data.get("path") or "")
        if path.replace("\\", "/").endswith("config/policy.yaml"):
            return "modify_this_policy_file"
        return None

    if tool_name != "Bash":
        return None

    cmd = str(input_data.get("command", ""))
    low = cmd.lower()

    if "git push" in low and ("main" in low or "master" in low or "--force" in low):
        return "git_push_main"
    if "git merge" in low and ("main" in low or "master" in low):
        return "git_merge_to_main"
    if "rm -rf /" in low or low.strip() in ("rm -rf .", "rm -rf *"):
        return "delete_repository"
    if "deploy" in low and "prod" in low:
        return "production_deploy"
    return None


class PermissionEngine:
    def __init__(
        self,
        tiers: dict[str, TierPolicy],
        promotable_task_types: list[str],
        human_approval_required: list[str],
        overrides: dict[str, dict],
        limits: dict,
    ):
        self.tiers = tiers
        self.promotable_task_types = set(promotable_task_types)
        self.human_approval_required = set(human_approval_required)
        self.overrides = overrides
        self.limits = limits

    @classmethod
    def load(cls, policy_yaml: Path) -> "PermissionEngine":
        if not policy_yaml.exists():
            raise PolicyError(f"policy file not found: {policy_yaml}")
        raw = yaml.safe_load(policy_yaml.read_text(encoding="utf-8")) or {}

        tiers: dict[str, TierPolicy] = {}
        for name, cfg in (raw.get("autonomy_tiers") or {}).items():
            cfg = dict(cfg or {})
            tiers[name] = TierPolicy(
                name=name,
                git_commit_feature_branch=bool(cfg.get("git_commit_feature_branch", False)),
                git_commit_main=bool(cfg.get("git_commit_main", False)),
                multi_task_per_cycle=bool(cfg.get("multi_task_per_cycle", False)),
                promote_without_human=bool(cfg.get("promote_without_human", False)),
                description=cfg.get("description", ""),
            )
        if not tiers:
            raise PolicyError(f"{policy_yaml}: no autonomy_tiers defined")
        if any(t.git_commit_main for t in tiers.values()):
            raise PolicyError(
                f"{policy_yaml}: git_commit_main must be false for every tier — "
                "main is never auto-committed by this engine, regardless of config"
            )

        return cls(
            tiers=tiers,
            promotable_task_types=raw.get("promotable_task_types", []) or [],
            human_approval_required=raw.get("human_approval_required", []) or [],
            overrides=raw.get("overrides", {}) or {},
            limits=raw.get("limits", {}) or {},
        )

    def tier_for(self, agent: AgentSpec) -> TierPolicy:
        override = self.overrides.get(agent.agent_id, {})
        tier_name = override.get("autonomy_tier", agent.autonomy)
        try:
            return self.tiers[tier_name]
        except KeyError as exc:
            raise PolicyError(
                f"agent {agent.agent_id!r} has unknown autonomy tier {tier_name!r} "
                f"(known tiers: {sorted(self.tiers)})"
            ) from exc

    def check_tool_call(self, agent: AgentSpec, task: Task, tool_name: str, input_data: dict) -> Decision:
        """The `can_use_tool` decision for one SDK tool call. Called once per
        tool invocation, live, while the agent's session is running."""
        tier = self.tier_for(agent)
        action = classify_action(tool_name, input_data)

        if action is not None and action in self.human_approval_required:
            return Decision(False, True, f"{action!r} always requires human approval", action)

        if tool_name == "Bash":
            low = str(input_data.get("command", "")).lower()
            touches_main = "main" in low or "master" in low
            if "git commit" in low:
                if touches_main:
                    return Decision(False, True, "commits to main always require human approval", "git_commit_main")
                if not tier.git_commit_feature_branch:
                    return Decision(
                        False, True,
                        f"tier {tier.name!r} may not commit without approval "
                        f"(git_commit_feature_branch is false)",
                        "git_commit_feature_branch",
                    )
            elif "git push" in low and not touches_main:
                if not tier.git_commit_feature_branch:
                    return Decision(
                        False, True,
                        f"tier {tier.name!r} may not push without approval", "git_push_feature_branch",
                    )

        return Decision(True, False, "within agent's tools and tier", action)

    def can_promote(self, agent: AgentSpec, task: Task) -> Decision:
        """Whether `task` may be promoted/deployed without a human, per policy.yaml."""
        tier = self.tier_for(agent)
        if not tier.promote_without_human:
            return Decision(False, True, f"tier {tier.name!r} cannot auto-promote")
        if task.task_type not in self.promotable_task_types:
            return Decision(
                False, True,
                f"task_type {task.task_type!r} is not in promotable_task_types "
                f"({sorted(self.promotable_task_types)})",
            )
        if task.risk_level == "high":
            return Decision(False, True, "risk_level 'high' always requires human approval")
        return Decision(True, False, "auto-promoted per policy.yaml (tier + task_type + risk_level all clear)")

    def max_tasks_per_cycle(self, agent: AgentSpec) -> int:
        tier = self.tier_for(agent)
        if tier.multi_task_per_cycle:
            return int(self.limits.get("max_tasks_per_unattended_cycle", 1))
        return 1

    @property
    def max_budget_usd_per_run(self) -> float:
        return float(self.limits.get("max_budget_usd_per_run", 5.0))
