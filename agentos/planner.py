"""Master Planner: turns a goal into the Task Engine's DAG (blueprint Sheet 02).

Runs once per goal, before any phase is activated, using its own SDK
session with `output_format` set to a JSON schema — the planner is
constrained to return a structured task list, not prose the rest of the
system would have to parse hopefully.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from agentos.models import AgentSpec, Task
from agentos.registry import Registry
from agentos.task_engine import TaskEngineError, TaskGraph


class PlannerError(Exception):
    pass


PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "local_id": {
                        "type": "string",
                        "description": "short id (e.g. 't1') used only to express dependencies within this plan",
                    },
                    "description": {"type": "string"},
                    "owner_agent": {"type": "string"},
                    "phase": {"type": "string"},
                    "dependencies": {"type": "array", "items": {"type": "string"}},
                    "inputs": {"type": "array", "items": {"type": "string"}},
                    "outputs": {"type": "array", "items": {"type": "string"}},
                    "validators": {"type": "array", "items": {"type": "string"}},
                    "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
                    "human_approval_required": {"type": "boolean"},
                    "task_type": {"type": ["string", "null"]},
                },
                "required": ["local_id", "description", "owner_agent", "phase"],
            },
        }
    },
    "required": ["tasks"],
}


def _build_prompt(goal: str, registry: Registry) -> str:
    agents_desc = "\n".join(
        f"- {a.agent_id} ({a.role}): {a.description.strip() or a.system_prompt.strip().splitlines()[0]}"
        for a in registry.agents.values()
        if a.agent_id != "planner-agent"
    )
    phases_desc = "\n".join(
        f"- {registry.phases[pid].id}: {registry.phases[pid].description} "
        f"(eligible agents: {', '.join(registry.phases[pid].roster)})"
        for pid in registry.phase_sequence
    )
    return (
        f"Goal:\n{goal}\n\n"
        f"Registered agents you may assign work to:\n{agents_desc}\n\n"
        f"Phases, in default order (independent tasks from different phases "
        f"may still run in parallel if the DAG allows it):\n{phases_desc}\n\n"
        "Produce the task list as JSON matching your output schema. Use "
        "`local_id` values (e.g. \"t1\", \"t2\") to express `dependencies` — "
        "the engine assigns the real task_ids afterward. Only assign a task "
        "to an agent listed on that phase's roster above."
    )


async def plan(goal: str, registry: Registry, repo_root: Path) -> TaskGraph:
    planner_agent: AgentSpec = registry.get_agent("planner-agent")

    options = ClaudeAgentOptions(
        system_prompt=planner_agent.system_prompt,
        allowed_tools=planner_agent.tools,
        model=planner_agent.model,
        cwd=str(repo_root),
        max_turns=planner_agent.max_turns,
        permission_mode="default",
        output_format={"type": "json_schema", "schema": PLAN_SCHEMA},
    )

    result_msg: Optional[ResultMessage] = None
    async for message in query(prompt=_build_prompt(goal, registry), options=options):
        if isinstance(message, ResultMessage):
            result_msg = message

    if result_msg is None:
        raise PlannerError("planning session produced no result")
    if result_msg.is_error:
        raise PlannerError(f"planning session failed: {result_msg.result}")

    payload = result_msg.structured_output
    if payload is None:
        try:
            payload = json.loads(result_msg.result or "{}")
        except json.JSONDecodeError as exc:
            raise PlannerError(f"planner output was neither structured_output nor valid JSON: {exc}") from exc

    raw_tasks = payload.get("tasks", [])
    if not raw_tasks:
        raise PlannerError("planner returned an empty task list")

    return _to_task_graph(raw_tasks, registry)


def _to_task_graph(raw_tasks: list[dict], registry: Registry) -> TaskGraph:
    for raw in raw_tasks:
        _validate_owner_and_phase(raw, registry)

    # Pass 1: mint real Task objects, remember local_id -> real task_id.
    local_to_real: dict[str, str] = {}
    tasks: list[Task] = []
    for raw in raw_tasks:
        task = Task(
            description=raw["description"],
            owner_agent=raw["owner_agent"],
            phase=raw["phase"],
            inputs=raw.get("inputs", []) or [],
            outputs=raw.get("outputs", []) or [],
            validators=raw.get("validators", []) or [],
            risk_level=raw.get("risk_level", "low") or "low",
            human_approval_required=bool(raw.get("human_approval_required", False)),
            task_type=raw.get("task_type"),
        )
        local_id = raw.get("local_id")
        if local_id:
            if local_id in local_to_real:
                raise PlannerError(f"duplicate local_id {local_id!r} in planner output")
            local_to_real[local_id] = task.task_id
        tasks.append(task)

    # Pass 2: resolve dependencies from local_id to real task_id.
    for raw, task in zip(raw_tasks, tasks):
        deps = []
        for dep in raw.get("dependencies", []) or []:
            if dep not in local_to_real:
                raise PlannerError(
                    f"task {raw.get('local_id')!r} depends on unknown local_id {dep!r}"
                )
            deps.append(local_to_real[dep])
        task.dependencies = deps

    graph = TaskGraph()
    try:
        graph.add_many(tasks)
    except TaskEngineError as exc:
        raise PlannerError(f"planner produced an invalid DAG: {exc}") from exc
    return graph


def _validate_owner_and_phase(raw: dict, registry: Registry) -> None:
    owner = raw.get("owner_agent")
    phase = raw.get("phase")
    local_id = raw.get("local_id")
    if owner not in registry.agents:
        raise PlannerError(f"planner assigned task {local_id!r} to unknown agent {owner!r}")
    if phase not in registry.phases:
        raise PlannerError(f"planner assigned task {local_id!r} to unknown phase {phase!r}")
    if owner not in registry.phases[phase].roster:
        raise PlannerError(
            f"planner assigned task {local_id!r} to {owner!r}, which is not on "
            f"phase {phase!r}'s roster ({registry.phases[phase].roster})"
        )
