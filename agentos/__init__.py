"""agent-os: a general-purpose multi-agent orchestration system.

Planner -> Phase Engine -> Task Engine (DAG) -> Orchestrator -> Agent Registry
+ Skill Registry, gated throughout by the Permission Engine and the Human
Approval System, with an independent Evaluation loop before anything counts
as done. See README.md for the architecture this package implements.
"""

__version__ = "0.1.0"
