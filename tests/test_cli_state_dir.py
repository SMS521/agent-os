"""Tests for agentos.cli._state_dir()'s default location.

Regression coverage: the default used to be `repo_root / "state"` — inside
whatever --repo pointed at. That put agent-os's own approval queue and run
logs, untracked, inside the target repo, one `git add -A` away from being
committed into that repo's own history.
"""

from pathlib import Path

from agentos.cli import _PACKAGE_ROOT, _state_dir


def test_state_dir_defaults_outside_target_repo(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("AGENTOS_STATE_DIR", raising=False)
    target_repo = tmp_path / "some-target-repo"
    target_repo.mkdir()

    result = _state_dir(target_repo)

    assert _PACKAGE_ROOT in result.parents
    assert target_repo not in result.parents
    assert result != target_repo / "state"


def test_state_dir_is_deterministic_per_repo(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("AGENTOS_STATE_DIR", raising=False)
    target_repo = tmp_path / "some-target-repo"
    target_repo.mkdir()

    assert _state_dir(target_repo) == _state_dir(target_repo)


def test_state_dir_differs_for_different_repos(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("AGENTOS_STATE_DIR", raising=False)
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()

    assert _state_dir(repo_a) != _state_dir(repo_b)


def test_state_dir_respects_explicit_env_override(monkeypatch, tmp_path: Path):
    override = tmp_path / "custom-state"
    monkeypatch.setenv("AGENTOS_STATE_DIR", str(override))

    result = _state_dir(tmp_path / "whatever-repo")

    assert result == override.resolve()
