"""Tests for the review-head-check skill's check_head.py script, partly on a small real git repository."""

import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

from tests.skill_scripts import FakeShell, install_shell, load_skill_script, run_main

SKILL = "review-head-check"


def git(*arguments: str) -> str:
    completed = subprocess.run(["git", *arguments], capture_output=True, text=True, encoding="utf-8", check=True)
    return completed.stdout.strip()


def commit_file(name: str, text: str) -> str:
    Path(name).write_text(text, encoding="utf-8")
    git("add", name)
    git("commit", "--quiet", "-m", f"change {name}")
    return git("rev-parse", "HEAD")


@pytest.fixture
def check_head() -> ModuleType:
    return load_skill_script(SKILL, "check_head")


@pytest.fixture
def reviewed_sha(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A pull request branch with one reviewed commit, and a base branch that moved on. Returns the reviewed commit."""
    monkeypatch.chdir(tmp_path)
    git("init", "--quiet", "--initial-branch=main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    commit_file("base.txt", "base\n")
    git("checkout", "--quiet", "-b", "feature")
    reviewed = commit_file("feature.txt", "feature\n")
    git("checkout", "--quiet", "main")
    commit_file("other.txt", "other\n")
    git("checkout", "--quiet", "feature")
    return reviewed


def test_a_clean_merge_of_the_base_branch_is_no_new_commit(check_head: ModuleType, reviewed_sha: str) -> None:
    git("merge", "--quiet", "--no-edit", "main")

    assert check_head.new_commits(reviewed_sha, git("rev-parse", "HEAD")) == []


def test_a_conflict_merge_that_takes_the_base_side_is_listed(check_head: ModuleType, reviewed_sha: str) -> None:
    git("checkout", "--quiet", "main")
    commit_file("feature.txt", "base version\n")
    git("checkout", "--quiet", "feature")
    subprocess.run(["git", "merge", "--quiet", "main"], capture_output=True, check=False)
    head_sha = commit_file("feature.txt", "base version\n")

    assert check_head.new_commits(reviewed_sha, head_sha) == [head_sha[:10]]


def test_a_commit_that_changes_the_pull_request_is_listed(check_head: ModuleType, reviewed_sha: str) -> None:
    git("merge", "--quiet", "--no-edit", "main")
    head_sha = commit_file("feature.txt", "feature, fixed\n")

    assert check_head.new_commits(reviewed_sha, head_sha) == [head_sha[:10]]


def test_an_unmoved_head_needs_no_fetch_and_lists_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], check_head: ModuleType
) -> None:
    pull_request = json.dumps({"headRefName": "42-fix-save", "headRefOid": "abc"})
    shell = install_shell(monkeypatch, check_head, FakeShell({"gh pr view 9": pull_request}))

    printed = run_main(monkeypatch, capsys, check_head, {"pr": 9, "reviewed_sha": "abc"})

    assert printed == {"head_sha": "abc", "commits": []}
    assert not shell.ran("git fetch")


def test_a_moved_head_is_fetched_before_its_commits_are_listed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], check_head: ModuleType
) -> None:
    pull_request = json.dumps({"headRefName": "42-fix-save", "headRefOid": "def4567890ab"})
    shell = install_shell(monkeypatch, check_head, FakeShell({"gh pr view 9": pull_request}))
    monkeypatch.setattr(check_head, "new_commits", lambda reviewed, head: [head[:10]])

    printed = run_main(monkeypatch, capsys, check_head, {"pr": 9, "reviewed_sha": "abc"})

    assert printed == {"head_sha": "def4567890ab", "commits": ["def4567890"]}
    assert shell.ran("git fetch --quiet origin 42-fix-save")
