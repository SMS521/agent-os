"""Git operations available to agents — deliberately narrow.

The Permission Engine's `can_use_tool` callback already gates the raw `git`
commands an agent's Bash tool use can attempt; this module adds one more
layer underneath that no policy.yaml setting can loosen: nothing here
merges or pushes to main without an explicit `human_confirmed=True`, passed
only from the CLI's approve path, never from an agent's own call.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

_PROTECTED = ("main", "master")


class GitOpsError(Exception):
    pass


@dataclass
class GitResult:
    ok: bool
    output: str


def _run(repo_root: Path, args: list[str]) -> GitResult:
    proc = subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True)
    return GitResult(ok=proc.returncode == 0, output=(proc.stdout + proc.stderr).strip())


def current_branch(repo_root: Path) -> str:
    res = _run(repo_root, ["rev-parse", "--abbrev-ref", "HEAD"])
    if not res.ok:
        raise GitOpsError(f"git rev-parse failed: {res.output}")
    return res.output


def create_feature_branch(repo_root: Path, task_id: str, base: str = "main") -> str:
    branch = f"agent-os/{task_id}"
    res = _run(repo_root, ["checkout", "-b", branch, base])
    if not res.ok:
        raise GitOpsError(f"could not create branch {branch!r} from {base!r}: {res.output}")
    return branch


def commit_all(repo_root: Path, branch: str, message: str) -> str:
    """Stages and commits everything in the working tree to `branch`. Returns
    the new commit's SHA. Refuses outright if `branch` is main/master, and
    refuses if that isn't actually what's checked out — a caller passing the
    wrong branch name is a bug, not a thing to silently correct."""
    if branch in _PROTECTED:
        raise GitOpsError("refusing to commit directly to main/master — not configurable")
    checked_out = current_branch(repo_root)
    if checked_out != branch:
        raise GitOpsError(f"expected {branch!r} checked out, found {checked_out!r}")

    add = _run(repo_root, ["add", "-A"])
    if not add.ok:
        raise GitOpsError(f"git add failed: {add.output}")

    commit = _run(repo_root, ["commit", "-m", message])
    if not commit.ok:
        if "nothing to commit" in commit.output.lower():
            raise GitOpsError("nothing to commit — the task produced no file changes")
        raise GitOpsError(f"git commit failed: {commit.output}")

    sha = _run(repo_root, ["rev-parse", "HEAD"])
    if not sha.ok:
        raise GitOpsError(f"commit succeeded but rev-parse failed: {sha.output}")
    return sha.output


def push_branch(repo_root: Path, branch: str) -> None:
    if branch in _PROTECTED:
        raise GitOpsError("refusing to push directly to main/master — not configurable")
    res = _run(repo_root, ["push", "-u", "origin", branch])
    if not res.ok:
        raise GitOpsError(f"git push failed: {res.output}")


def checkout(repo_root: Path, branch: str) -> None:
    res = _run(repo_root, ["checkout", branch])
    if not res.ok:
        raise GitOpsError(f"git checkout {branch!r} failed: {res.output}")


def delete_branch(repo_root: Path, branch: str, *, force: bool = False) -> None:
    if branch in _PROTECTED:
        raise GitOpsError("refusing to delete main/master")
    res = _run(repo_root, ["branch", "-D" if force else "-d", branch])
    if not res.ok:
        raise GitOpsError(f"git branch delete {branch!r} failed: {res.output}")


def merge_to_main(repo_root: Path, branch: str, *, human_confirmed: bool) -> str:
    """The only function in this module that touches main. Callable only
    with human_confirmed=True, set exclusively by `agentos approve` after a
    human resolves the corresponding ApprovalRequest — mirrors policy.yaml's
    git_commit_main: false at every tier, enforced here in code as well as
    in config, not just documented as a convention."""
    if not human_confirmed:
        raise GitOpsError("merge_to_main requires human_confirmed=True — see `agentos approve`")

    checkout = _run(repo_root, ["checkout", "main"])
    if not checkout.ok:
        raise GitOpsError(f"could not check out main: {checkout.output}")

    merge = _run(repo_root, ["merge", "--no-ff", branch, "-m", f"Merge {branch} (human-approved)"])
    if not merge.ok:
        raise GitOpsError(f"git merge failed: {merge.output}")

    sha = _run(repo_root, ["rev-parse", "HEAD"])
    if not sha.ok:
        raise GitOpsError(f"merge succeeded but rev-parse failed: {sha.output}")
    return sha.output
