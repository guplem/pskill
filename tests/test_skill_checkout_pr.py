"""Tests for the checkout-pr skill's checkout_pr.py script."""

import json
from typing import Any

import pytest

from tests.skill_scripts import FakeShell, install_shell, load_skill_script, run_main

# A pull request as the REST API gives it.
OPEN_PR: dict[str, Any] = {
    "state": "open",
    "merged_at": None,
    "head": {"ref": "42-fix-save", "repo": {"full_name": "o/r"}},
    "base": {"ref": "main", "repo": {"full_name": "o/r"}},
}
MERGED: dict[str, Any] = {"state": "closed", "merged_at": "2026-01-01T00:00:00Z"}
FORK: dict[str, Any] = {"head": {"ref": "42-fix-save", "repo": {"full_name": "fork/r"}}}


def shell_for(
    pr: dict[str, object], outputs: dict[str, str] | None = None, failing: list[str] | None = None
) -> FakeShell:
    pull_request = {"gh api GET repos/{owner}/{repo}/pulls/7": json.dumps(pr)}
    return FakeShell({**pull_request, "git rev-parse HEAD": "abc123", **(outputs or {})}, failing)


def test_a_new_local_branch_tracks_the_pull_request_branch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script("checkout-pr", "checkout_pr")
    shell = install_shell(monkeypatch, script, shell_for(OPEN_PR, failing=["git rev-parse --verify"]))

    printed = run_main(monkeypatch, capsys, script, {"pr": 7})

    assert shell.ran("git switch --quiet --create 42-fix-save --track origin/42-fix-save")
    assert printed == {"branch": "42-fix-save", "base": "main", "head_sha": "abc123", "plan_file": ""}


def test_an_existing_branch_is_switched_to_and_fast_forwarded(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script("checkout-pr", "checkout_pr")
    shell = install_shell(monkeypatch, script, shell_for(OPEN_PR, outputs={"git branch --show-current": "main"}))

    run_main(monkeypatch, capsys, script, {"pr": 7})

    assert shell.ran("git switch --quiet 42-fix-save")
    assert shell.ran("git merge --quiet --ff-only origin/42-fix-save")


def test_the_plan_file_is_the_newest_one_that_the_branch_added(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script("checkout-pr", "checkout_pr")
    added = {"git log --diff-filter=A": "\nimplementation-plan-42.md\n", "git branch --show-current": "42-fix-save"}
    install_shell(monkeypatch, script, shell_for(OPEN_PR, outputs=added))

    printed = run_main(monkeypatch, capsys, script, {"pr": 7})

    assert printed["plan_file"] == "implementation-plan-42.md"


@pytest.mark.parametrize(
    ("pr_change", "tables", "reason"),
    [
        (MERGED, {}, "Pull request #7 is merged."),
        ({"state": "closed"}, {}, "Pull request #7 is closed."),
        (FORK, {}, "comes from a fork"),
        ({}, {"outputs": {"git status --porcelain": "M a.py\n?? b.py"}}, "uncommitted changes: a.py, b.py"),
        ({}, {"failing": ["git fetch"]}, "cannot be fetched"),
        ({}, {"failing": ["git merge-base"]}, "has commits that GitHub does not have"),
        ({}, {"failing": ["git cat-file -e origin/42-fix-save:.pskill/pskill.py"]}, "has no .pskill/ yet"),
    ],
)
def test_a_problem_pauses_the_run_and_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    pr_change: dict[str, object],
    tables: dict[str, Any],
    reason: str,
) -> None:
    script = load_skill_script("checkout-pr", "checkout_pr")
    shell = install_shell(monkeypatch, script, shell_for({**OPEN_PR, **pr_change}, **tables))

    with pytest.raises(SystemExit) as exit_info:
        run_main(monkeypatch, capsys, script, {"pr": 7})

    assert exit_info.value.code == 1
    assert reason in capsys.readouterr().err
    assert not shell.ran("git switch")
