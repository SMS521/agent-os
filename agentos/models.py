"""Core data contracts shared by every subsystem.

Nothing in this file talks to the network, the filesystem beyond what it's
given, or the Claude Agent SDK. It exists so the Registry, Permission Engine,
Task Engine, Phase Engine, Orchestrator and Evaluation loop all agree on the
shape of an agent, a skill, a task and an approval request without importing
each other.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator

RiskLevel = str  # "low" | "medium" | "high" — kept as str for forward-compat with custom levels


class AgentStatus(str, Enum):
    """Lifecycle of an *agent slot* — separate from any one task's status.

    An agent can be REGISTERED (known to the registry) but INACTIVE (not
    staffed for the current phase); the Orchestrator flips it to ACTIVE only
    when the Phase Engine's roster calls for it.
    """

    REGISTERED = "registered"
    ACTIVE = "active"
    INACTIVE = "inactive"
    DISABLED = "disabled"


class TaskStatus(str, Enum):
    """A task's position in the lifecycle from Sheet 06 of the blueprint."""

    CREATED = "created"
    READY = "ready"          # dependencies satisfied, waiting for an agent slot
    RUNNING = "running"
    WAITING = "waiting"      # blocked on a human approval
    REVIEW = "review"        # in the Evaluation loop
    APPROVED = "approved"    # validators + (if required) human said PASS
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY = "retry"
    ESCALATED = "escalated"  # exhausted retries or hit a policy wall; a human must look
    BLOCKED = "blocked"      # dependency failed/escalated; this task can't proceed

    @property
    def is_terminal(self) -> bool:
        return self in (TaskStatus.COMPLETED, TaskStatus.ESCALATED, TaskStatus.BLOCKED)


class PhaseStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETE = "complete"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    AUTO_APPROVED = "auto_approved"  # granted by policy.yaml, not a human — always logged


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class SkillSpec(BaseModel):
    """One entry from registry/skills/<id>/SKILL.md's front matter.

    Mirrors the Anthropic Agent Skills convention: a folder with a SKILL.md
    an agent loads when the task at hand matches `description`.
    """

    skill_id: str
    name: str
    description: str
    required_tools: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = "low"
    phase: Optional[str] = None  # which phase this skill is normally relevant in, if any
    path: str  # folder containing SKILL.md, resolved by the registry loader


class AgentSpec(BaseModel):
    """One entry from registry/agents.yaml — the Agent Registry's unit."""

    agent_id: str
    role: str
    skills: list[str] = Field(default_factory=list)      # skill_ids
    tools: list[str] = Field(default_factory=list)        # tool names the SDK session may use
    model: str = "claude-sonnet-5"
    autonomy: str = "supervised"                           # tier name from policy.yaml
    system_prompt: str
    status: AgentStatus = AgentStatus.REGISTERED
    max_turns: Optional[int] = None
    description: str = ""

    @field_validator("autonomy")
    @classmethod
    def _known_tier(cls, v: str) -> str:
        # Loose validation here; permissions.py does the authoritative check
        # against the live policy.yaml so this file doesn't need to import it.
        if not v:
            raise ValueError("autonomy tier must not be empty")
        return v


class Phase(BaseModel):
    """One entry from config/phases.yaml plus live status."""

    id: str
    description: str
    roster: list[str] = Field(default_factory=list)   # agent_ids eligible this phase
    completion_criteria: list[str] = Field(default_factory=list)
    status: PhaseStatus = PhaseStatus.PENDING


class Task(BaseModel):
    """The task contract every agent's work is judged against.

    Matches Sheet 06 of the architecture blueprint field-for-field, plus the
    bookkeeping (status, retries, result) the Task Engine needs at runtime.
    """

    task_id: str = Field(default_factory=lambda: _new_id("task"))
    description: str
    owner_agent: str                          # agent_id
    phase: str                                 # phase id
    dependencies: list[str] = Field(default_factory=list)   # task_ids
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    validators: list[str] = Field(default_factory=list)     # agent_ids that must independently review
    risk_level: RiskLevel = "low"
    human_approval_required: bool = False
    task_type: Optional[str] = None            # e.g. "research_finding", "staging_deploy" — see policy.yaml

    status: TaskStatus = TaskStatus.CREATED
    retry_count: int = 0
    max_retries: int = 2
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    def touch(self) -> None:
        self.updated_at = time.time()

    @field_validator("risk_level")
    @classmethod
    def _valid_risk(cls, v: str) -> str:
        if v not in ("low", "medium", "high"):
            raise ValueError(f"risk_level must be low/medium/high, got {v!r}")
        return v


class ApprovalRequest(BaseModel):
    """One row in the Human Approval System's queue."""

    approval_id: str = Field(default_factory=lambda: _new_id("appr"))
    task_id: str
    agent_id: str
    action: str                 # e.g. "git_push_main", "production_deploy"
    description: str
    risk_level: RiskLevel = "medium"
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: float = Field(default_factory=time.time)
    decided_at: Optional[float] = None
    decided_by: Optional[str] = None   # "human" or the policy rule that auto-approved it
    reason: Optional[str] = None


class EvaluationReport(BaseModel):
    """Output of the Evaluation loop (Sheet 09) for one task."""

    task_id: str
    passed: bool
    checks: dict[str, bool] = Field(default_factory=dict)   # e.g. {"tests": True, "review": False}
    notes: str = ""
    reviewer_agent: Optional[str] = None
