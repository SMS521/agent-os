import subprocess
from pathlib import Path

import pytest

from agentos.git_ops import (
    GitOpsError,
    checkout,
    commit_all,
    create_feature_branch,
    current_branch,
    delete_branch,
    merge_to_main,
)


def _run(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _run(root, "init", "-q", "-b", "main")
    _run(root, "config", "user.email", "test@example.com")
    _run(root, "config", "user.name", "Test")
    (root / "README.md").write_text("hello\n")
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "-m", "initial commit")
    return root


def test_create_feature_branch_from_main(repo: Path):
    branch = create_feature_branch(repo, "task_1")
    assert branch == "agent-os/task_1"
    assert current_branch(repo) == branch


def test_commit_all_refuses_main(repo: Path):
    with pytest.raises(GitOpsError, match="main/master"):
        commit_all(repo, "main", "should not work")


def test_commit_all_refuses_wrong_branch_checked_out(repo: Path):
    create_feature_branch(repo, "task_1")
    with pytest.raises(GitOpsError, match="expected"):
        commit_all(repo, "agent-os/task_other", "wrong branch")


def test_commit_all_happy_path(repo: Path):
    branch = create_feature_branch(repo, "task_1")
    (repo / "new_file.txt").write_text("content\n")
    sha = commit_all(repo, branch, "add new_file.txt")
    assert len(sha) == 40  # a real commit SHA


def test_commit_all_raises_when_nothing_changed(repo: Path):
    branch = create_feature_branch(repo, "task_1")
    with pytest.raises(GitOpsError, match="nothing to commit"):
        commit_all(repo, branch, "no-op")


def test_merge_to_main_requires_explicit_human_confirmation(repo: Path):
    branch = create_feature_branch(repo, "task_1")
    (repo / "new_file.txt").write_text("content\n")
    commit_all(repo, branch, "add file")

    with pytest.raises(GitOpsError, match="human_confirmed"):
        merge_to_main(repo, branch, human_confirmed=False)


def test_merge_to_main_succeeds_when_confirmed(repo: Path):
    branch = create_feature_branch(repo, "task_1")
    (repo / "new_file.txt").write_text("content\n")
    commit_all(repo, branch, "add file")

    sha = merge_to_main(repo, branch, human_confirmed=True)
    assert len(sha) == 40
    assert current_branch(repo) == "main"
    assert (repo / "new_file.txt").exists()


def test_checkout_and_delete_branch_cleanup_cycle(repo: Path):
    branch = create_feature_branch(repo, "task_1")
    checkout(repo, "main")
    delete_branch(repo, branch)
    assert current_branch(repo) == "main"


def test_delete_branch_refuses_main(repo: Path):
    with pytest.raises(GitOpsError, match="main/master"):
        delete_branch(repo, "main")
