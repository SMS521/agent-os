"""Runtime: turns an AgentSpec + a Task into one real Claude Agent SDK call.

This is the only module that imports claude_agent_sdk. Everything upstream
(planner, orchestrator, task/phase engines) works in terms of the plain
models in models.py; everything downstream of a run (evaluation, git_ops)
reads a RunResult, not SDK types. Swapping SDK versions, or even swapping
the SDK for something else, should only ever touch this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from claude_agent_sdk import (
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    query,
)

from agentos.approvals import ApprovalQueue
from agentos.models import AgentSpec, SkillSpec, Task
from agentos.permissions import PermissionEngine


@dataclass
class RunResult:
    task_id: str
    ok: bool
    output: Optional[str]
    session_id: Optional[str]
    cost_usd: Optional[float]
    error: Optional[str] = None


def _strip_frontmatter(skill_md_text: str) -> str:
    if not skill_md_text.startswith("---"):
        return skill_md_text.strip()
    parts = skill_md_text.split("---", 2)
    return parts[2].strip() if len(parts) >= 3 else skill_md_text.strip()


def build_system_prompt(agent: AgentSpec, skills: list[SkillSpec], task: Task) -> str:
    """Agent's own system_prompt, plus the full body of every skill it's
    equipped with (the Anthropic Agent Skills pattern: load the whole
    SKILL.md when it's relevant, not just its one-line description), plus
    the task itself."""
    parts = [agent.system_prompt.strip()]

    if skills:
        parts.append("## Skills available to you\n")
        for skill in skills:
            body = _strip_frontmatter(Path(skill.path, "SKILL.md").read_text(encoding="utf-8"))
            parts.append(f"### {skill.name}\n\n{body}\n")

    parts.append(
        "## Current task\n\n"
        f"task_id: {task.task_id}\n"
        f"phase: {task.phase}\n"
        f"description: {task.description}\n"
        f"expected outputs: {', '.join(task.outputs) or '(none declared)'}\n"
        f"risk_level: {task.risk_level}\n"
    )
    return "\n".join(parts)


def make_can_use_tool(permission_engine: PermissionEngine, approvals: ApprovalQueue, agent: AgentSpec, task: Task):
    """Wires the Permission Engine into the SDK's live per-tool-call gate.
    A denial here writes a PENDING row to the approval queue so a human can
    revisit it with `agentos approve <id>` on a later run — the SDK session
    itself does not block waiting for that decision, consistent with
    'NIGHT_QUEUE'-style unattended runs: it moves on, the task goes back to
    RETRY/ESCALATED, a human looks at the run's approval queue afterward."""

    async def can_use_tool(tool_name: str, input_data: dict, context) -> PermissionResultAllow | PermissionResultDeny:
        decision = permission_engine.check_tool_call(agent=agent, task=task, tool_name=tool_name, input_data=input_data)
        if decision.allowed:
            return PermissionResultAllow(updated_input=input_data)

        if decision.requires_human_approval:
            approvals.request(
                task_id=task.task_id,
                agent_id=agent.agent_id,
                action=decision.action or tool_name,
                description=f"{tool_name}({input_data}) — {decision.reason}",
                risk_level=task.risk_level,
            )
        return PermissionResultDeny(message=decision.reason)

    return can_use_tool


async def run_agent_task(
    agent: AgentSpec,
    skills: list[SkillSpec],
    task: Task,
    repo_root: Path,
    permission_engine: PermissionEngine,
    approvals: ApprovalQueue,
) -> RunResult:
    """Run one task end to end in a single SDK session and return its result.
    Multi-turn follow-up (e.g. a validator re-checking after a fix) is a
    second call to this function with a new Task, not a shared client — each
    task gets its own session so a run's audit trail stays one task = one
    session_id."""

    options = ClaudeAgentOptions(
        system_prompt=build_system_prompt(agent, skills, task),
        allowed_tools=agent.tools,
        model=agent.model,
        cwd=str(repo_root),
        max_turns=agent.max_turns,
        permission_mode="default",
        can_use_tool=make_can_use_tool(permission_engine, approvals, agent, task),
    )

    prompt = f"Task {task.task_id} ({task.phase}): {task.description}"

    result_msg: Optional[ResultMessage] = None
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            result_msg = message

    if result_msg is None:
        return RunResult(task.task_id, False, None, None, None, error="no ResultMessage received from SDK session")

    return RunResult(
        task_id=task.task_id,
        ok=not result_msg.is_error,
        output=result_msg.result,
        session_id=result_msg.session_id,
        cost_usd=result_msg.total_cost_usd,
        error=None if not result_msg.is_error else (result_msg.result or "SDK session reported an error"),
    )
