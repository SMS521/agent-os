"""CLI entry point: agentos plan|run|status|approvals|approve|deny.

Registry, skills and policy always load from *this* agent-os checkout
(agentos/../registry, agentos/../config); `--repo` / $AGENTOS_WORKDIR picks
the target repository agents actually read and write in. The two are
independent on purpose — one agent-os installation can point at many repos.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from typing import Optional

import click
from dotenv import load_dotenv

from agentos.approvals import ApprovalQueue
from agentos.git_ops import GitOpsError, merge_to_main
from agentos.orchestrator import Orchestrator
from agentos.permissions import PermissionEngine
from agentos.planner import plan as run_planner
from agentos.registry import Registry
from agentos.state import RunStateStore, new_run_id

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent

# Load agent-os/.env (ANTHROPIC_API_KEY, AGENTOS_STATE_DIR, AGENTOS_WORKDIR)
# before anything else runs. Only fills in variables not already set in the
# real environment — an exported ANTHROPIC_API_KEY always wins over .env.
load_dotenv(_PACKAGE_ROOT / ".env")


def _target_repo(explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit).resolve()
    env = os.environ.get("AGENTOS_WORKDIR")
    return Path(env).resolve() if env else Path.cwd()


def _state_dir(repo_root: Path) -> Path:
    env = os.environ.get("AGENTOS_STATE_DIR")
    if env:
        return Path(env).resolve()
    # Default lives under *this* agent-os checkout, keyed by the target
    # repo's resolved path — never inside the target repo itself. The
    # previous default (`repo_root / "state"`) put agent-os's own run state,
    # including the approval queue, inside whatever --repo pointed at:
    # untracked, but one `git add -A` (i.e. any successful release) away
    # from being swept into that repo's own commit history.
    key = f"{repo_root.name}-{hashlib.sha256(str(repo_root).encode()).hexdigest()[:10]}"
    return _PACKAGE_ROOT / "state" / key


def _load_engines() -> tuple[Registry, PermissionEngine]:
    registry = Registry.load(_PACKAGE_ROOT)
    permissions = PermissionEngine.load(_PACKAGE_ROOT / "config" / "policy.yaml")
    return registry, permissions


@click.group()
def cli() -> None:
    """agent-os — planner, phase/task DAG, registered agents, evaluation, approvals."""


@cli.command()
@click.argument("goal")
@click.option("--repo", default=None, help="Target repo root (default: $AGENTOS_WORKDIR or cwd).")
def plan(goal: str, repo: Optional[str]) -> None:
    """Run only the Planner and print the resulting task DAG. No agent executes."""
    root = _target_repo(repo)
    registry, _ = _load_engines()
    graph = asyncio.run(run_planner(goal, registry, root))
    for t in graph.tasks.values():
        deps = ", ".join(t.dependencies) or "-"
        click.echo(f"{t.task_id}  [{t.phase:<12}] {t.owner_agent:<16} deps={deps}  {t.description[:70]}")


@cli.command()
@click.argument("goal")
@click.option("--repo", default=None, help="Target repo root (default: $AGENTOS_WORKDIR or cwd).")
def run(goal: str, repo: Optional[str]) -> None:
    """Plan, then orchestrate the goal end to end: agents, evaluation, release, approvals."""
    root = _target_repo(repo)
    registry, permissions = _load_engines()
    state_dir = _state_dir(root)
    approvals = ApprovalQueue(state_dir / "approvals.json")

    graph = asyncio.run(run_planner(goal, registry, root))
    orchestrator = Orchestrator(registry, graph, permissions, approvals, root)
    log = asyncio.run(orchestrator.run())

    run_id = new_run_id()
    path = RunStateStore(state_dir).save(run_id, goal, graph, log.entries)

    click.echo(str(log))
    click.echo(f"\nrun saved: {path}")

    pending = approvals.pending()
    if pending:
        click.echo(f"\n{len(pending)} approval(s) waiting — see `agentos approvals --repo {root}`")


@cli.command()
@click.option("--run-id", "run_id", default=None, help="Defaults to the most recent run.")
@click.option("--repo", default=None)
def status(run_id: Optional[str], repo: Optional[str]) -> None:
    """Show a run's task summary and any pending approvals."""
    root = _target_repo(repo)
    state_dir = _state_dir(root)
    store = RunStateStore(state_dir)

    rid = run_id or store.latest_run_id()
    if rid is None:
        click.echo("no runs recorded yet")
    else:
        data = store.load(rid)
        click.echo(f"run {data['run_id']}  goal: {data['goal']!r}")
        counts: dict[str, int] = {}
        for t in data["tasks"].values():
            counts[t["status"]] = counts.get(t["status"], 0) + 1
        click.echo(f"tasks: {counts}")

    approvals = ApprovalQueue(state_dir / "approvals.json")
    pending = approvals.pending()
    click.echo(f"\n{len(pending)} pending approval(s):")
    for req in pending:
        click.echo(f"  {req.approval_id}  [{req.risk_level}] {req.action} — {req.description}")


@cli.command(name="approvals")
@click.option("--all", "show_all", is_flag=True, help="Include already-decided requests, not just pending.")
@click.option("--repo", default=None)
def list_approvals(show_all: bool, repo: Optional[str]) -> None:
    """List approval requests."""
    root = _target_repo(repo)
    approvals = ApprovalQueue(_state_dir(root) / "approvals.json")
    rows = approvals.all() if show_all else approvals.pending()
    if not rows:
        click.echo("(none)")
    for req in rows:
        click.echo(
            f"{req.approval_id}  {req.status.value:<13} [{req.risk_level}] "
            f"{req.action} (task {req.task_id}) — {req.description}"
        )


@cli.command()
@click.argument("approval_id")
@click.option("--reason", default=None)
@click.option("--repo", default=None)
def approve(approval_id: str, reason: Optional[str], repo: Optional[str]) -> None:
    """Approve a pending request. For a 'promote' action this also merges
    the task's feature branch into main — the one thing this system will
    never do without exactly this command. Any other action type (a push,
    a deploy, a policy edit) is recorded as approved; carrying it out is a
    manual step this v0.1 CLI does not automate for you."""
    root = _target_repo(repo)
    approvals = ApprovalQueue(_state_dir(root) / "approvals.json")
    req = approvals.get(approval_id)
    approvals.decide(approval_id, approved=True, reason=reason)
    click.echo(f"{approval_id}: APPROVED")

    if req.action == "promote":
        branch = f"agent-os/{req.task_id}"
        try:
            sha = merge_to_main(root, branch, human_confirmed=True)
            click.echo(f"merged {branch} into main ({sha[:8]})")
        except GitOpsError as exc:
            click.echo(f"approved, but automatic merge failed — do it by hand: {exc}", err=True)
    else:
        click.echo("recorded as approved — carrying out this action is a manual step in v0.1")


@cli.command()
@click.argument("approval_id")
@click.option("--reason", default=None)
@click.option("--repo", default=None)
def deny(approval_id: str, reason: Optional[str], repo: Optional[str]) -> None:
    """Deny a pending approval request."""
    root = _target_repo(repo)
    approvals = ApprovalQueue(_state_dir(root) / "approvals.json")
    approvals.decide(approval_id, approved=False, reason=reason)
    click.echo(f"{approval_id}: DENIED")


if __name__ == "__main__":
    cli()
