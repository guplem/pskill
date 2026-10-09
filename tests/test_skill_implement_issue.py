"""Tests for the implement-issue skill's scripts."""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from pskill_runner.skill_loader import load_skill
from pskill_runner.skill_model import EndBlock, TaskBlock
from tests.skill_scripts import SKILLS_FOLDER, FakeShell, install_shell, load_skill_script, run_main

SKILL = "implement-issue"
LIMITS = ["implement_step", "review", "get_ci_green", "final_review", "resolve_items"]


def issue(**changes: Any) -> dict[str, Any]:
    return {
        "number": 42,
        "title": "Saving crashes",
        "body": "Steps.",
        "labels": [{"name": "bug"}],
        "comments": [{"author": {"login": "ana"}, "body": "Still there."}],
        "state": "OPEN",
        "assignees": [],
        **changes,
    }


@pytest.mark.parametrize(
    ("changes", "sub_issues", "reason"),
    [
        ({}, 0, None),
        ({"assignees": [{"login": "me"}]}, 0, None),
        ({"state": "CLOSED"}, 0, "is closed"),
        ({}, 3, "is a parent issue with 3 sub-issues: implement each sub-issue instead"),
        ({"assignees": [{"login": "ana"}, {"login": "me"}]}, 0, "is assigned to ana, who owns the work"),
        ({"labels": [{"name": "waiting-for-design"}]}, 0, "has the blocking labels waiting-for-design"),
    ],
)
def test_hold_reason_names_why_the_work_must_not_start(
    changes: dict[str, Any], sub_issues: int, reason: str | None
) -> None:
    script = load_skill_script(SKILL, "read_issue")

    assert script.hold_reason(issue(**changes), sub_issues, "me") == reason


def test_read_issue_prints_the_issue_with_its_links_and_branches(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "read_issue")
    timeline = [[{"event": "cross-referenced", "source": {"issue": {"number": 7, "title": "Related"}}}, {"event": "x"}]]
    outputs = {
        "gh issue view 42": json.dumps(issue()),
        "gh api repos/{owner}/{repo}/issues/42/timeline": json.dumps(timeline),
        "gh api repos/{owner}/{repo}/issues/42 ": "0",
        "gh api user": "me",
        "gh repo view": "O/R",
        "git ls-remote": "abc\trefs/heads/42-old-try\n",
    }
    install_shell(monkeypatch, script, FakeShell(outputs))

    printed = run_main(monkeypatch, capsys, script, {"request": "https://github.com/o/r/issues/42"})

    assert printed == {
        "number": 42,
        "title": "Saving crashes",
        "body": "Steps.",
        "labels": ["bug"],
        "comments": [{"author": "ana", "body": "Still there."}],
        "cross_references": [{"number": 7, "title": "Related"}],
        "hold_reason": None,
        "existing_branches": ["42-old-try"],
    }


def test_read_issue_holds_a_link_to_an_issue_of_another_repository(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "read_issue")
    shell = install_shell(monkeypatch, script, FakeShell({"gh repo view": "o/r"}))

    printed = run_main(monkeypatch, capsys, script, {"request": "https://github.com/other/tool/issues/42"})

    assert printed["number"] == 42
    assert printed["hold_reason"] == (
        "is in the repository other/tool, not in o/r: start the skill from a checkout of other/tool"
    )
    assert not shell.ran("gh issue view")


def test_checkout_default_branch_detaches_at_its_latest_commit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "checkout_default_branch")
    shell = install_shell(monkeypatch, script, FakeShell({"gh repo view": "trunk"}))

    printed = run_main(monkeypatch, capsys, script)

    assert printed == {"ok": True, "default_branch": "trunk"}
    assert shell.ran("git switch --quiet --detach origin/trunk")


@pytest.mark.parametrize(
    ("shell", "reason"),
    [
        (FakeShell({"git status --porcelain": "M a.py"}), "The checkout has uncommitted changes: a.py"),
        (FakeShell({"gh repo view": "main"}, failing=["git fetch"]), "The branch main cannot be fetched from GitHub."),
    ],
)
def test_checkout_default_branch_changes_nothing_on_a_problem(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], shell: FakeShell, reason: str
) -> None:
    script = load_skill_script(SKILL, "checkout_default_branch")
    install_shell(monkeypatch, script, shell)

    printed = run_main(monkeypatch, capsys, script)

    assert printed == {"ok": False, "reason": reason}
    assert not shell.ran("git switch")


def test_checkout_base_names_the_branch_and_claims_the_issue(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "checkout_base")
    shell = install_shell(monkeypatch, script, FakeShell(failing=["git rev-parse --verify"]))

    printed = run_main(monkeypatch, capsys, script, {"base": "origin/main", "slug": "fix-save", "issue": 42})

    assert printed == {"ok": True, "base": "main", "branch": "42-fix-save", "plan_file": "implementation-plan-42.md"}
    assert shell.ran("git switch --quiet --detach origin/main")
    assert shell.ran("gh issue edit 42 --add-assignee @me")


@pytest.mark.parametrize(
    ("shell", "reason"),
    [
        (
            FakeShell({"git ls-remote": "abc\trefs/heads/42-fix-save"}),
            "The branch 42-fix-save already exists on GitHub.",
        ),
        (FakeShell(), "The branch 42-fix-save already exists in this checkout."),
        (FakeShell(failing=["git rev-parse", "git fetch"]), "The base branch main cannot be fetched from GitHub."),
    ],
)
def test_checkout_base_changes_nothing_on_a_problem(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], shell: FakeShell, reason: str
) -> None:
    script = load_skill_script(SKILL, "checkout_base")
    install_shell(monkeypatch, script, shell)

    printed = run_main(monkeypatch, capsys, script, {"base": "main", "slug": "fix-save", "issue": 42})

    assert printed == {"ok": False, "reason": reason}
    assert not shell.ran("gh issue edit")


DRAFT_INPUT = {
    "branch": "42-fix-save",
    "base": "main",
    "plan_file": "implementation-plan-42.md",
    "title": "Fix the crash on save",
    "issue": 42,
}


def test_open_draft_pr_pushes_the_plan_and_opens_a_draft(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "open_draft_pr")
    outputs = {
        "git status --porcelain -- implementation-plan-42.md": "?? implementation-plan-42.md",
        "gh pr create": "https://github.com/o/r/pull/9",
    }
    shell = install_shell(monkeypatch, script, FakeShell(outputs, failing=["git rev-parse --verify"]))

    printed = run_main(monkeypatch, capsys, script, DRAFT_INPUT)

    assert printed == {"pr_number": 9, "pr_url": "https://github.com/o/r/pull/9"}
    assert shell.ran("git switch --quiet --create 42-fix-save")
    assert shell.ran("git commit --quiet -m Add the implementation plan")
    assert shell.ran("git push --quiet --set-upstream origin 42-fix-save")
    create = next(command for command in shell.commands if command.startswith("gh pr create"))
    assert "--draft --base main --title Fix the crash on save --assignee @me" in create
    assert "Closes #42" in create


def test_open_draft_pr_a_second_time_reuses_the_branch_the_commit_and_the_pull_request(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "open_draft_pr")
    outputs = {"git branch --show-current": "42-fix-save", "gh pr list": "https://github.com/o/r/pull/9"}
    shell = install_shell(monkeypatch, script, FakeShell(outputs))

    printed = run_main(monkeypatch, capsys, script, {**DRAFT_INPUT, "issue": 0})

    assert printed == {"pr_number": 9, "pr_url": "https://github.com/o/r/pull/9"}
    assert not shell.ran("git switch")
    assert not shell.ran("git commit")
    assert not shell.ran("gh pr create")


def test_mark_ready_marks_the_draft_ready_then_removes_the_plan(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "mark_ready")
    shell = install_shell(monkeypatch, script, FakeShell({"gh pr view": "true", "git rev-parse HEAD": "def456"}))

    printed = run_main(monkeypatch, capsys, script, {"pr": 9, "plan_file": "implementation-plan-42.md"})

    assert printed == {"head_sha": "def456"}
    changes = [
        command for command in shell.commands if command.startswith(("gh pr ready", "git rm", "git commit", "git push"))
    ]
    assert changes == [
        "gh pr ready 9",
        "git rm --quiet implementation-plan-42.md",
        "git commit --quiet -m Remove the implementation plan",
        "git push --quiet",
    ]


def test_mark_ready_a_second_time_only_pushes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "mark_ready")
    shell = install_shell(monkeypatch, script, FakeShell({"gh pr view": "false"}, failing=["git ls-files"]))

    run_main(monkeypatch, capsys, script, {"pr": 9, "plan_file": "implementation-plan-42.md"})

    assert not shell.ran("gh pr ready")
    assert not shell.ran("git rm")
    assert shell.ran("git push --quiet")


def unreviewed_shell(commits: str, merged_tree: str = "t3") -> FakeShell:
    """A branch whose commits after the review are a code fix (c1), the plan removal (c2), and a merge (c3).

    The merge is clean when git's own merge of its parents gives its tree, t3.
    """
    return FakeShell(
        {
            "gh pr view 9 --json headRefName": "42-saving-crash",
            "gh pr view 9 --json headRefOid": "c3full",
            "git rev-list --reverse --first-parent r1..c3full": commits,
            "git rev-list --parents -n 1 c3": "c3 c2 m1",
            "git rev-list --parents -n 1": "c0 p0",
            "git diff-tree --no-commit-id --name-status -r c1": "M\tsrc/save.py",
            "git diff-tree --no-commit-id --name-status -r c2": "D\timplementation-plan-42.md",
            "git diff-tree --no-commit-id --name-status -r c3": "M\tsrc/other.py",
            "git merge-tree --write-tree c2 m1": merged_tree,
            "git rev-parse c3^{tree}": "t3",
        }
    )


def test_check_unreviewed_skips_the_plan_removal_and_a_clean_merge(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "check_unreviewed")
    shell = install_shell(monkeypatch, script, unreviewed_shell("c1\nc2\nc3"))

    printed = run_main(
        monkeypatch, capsys, script, {"pr": 9, "last_reviewed": "r1", "plan_file": "implementation-plan-42.md"}
    )

    assert printed == {"unreviewed": True, "commits": ["c1"], "head_sha": "c3full"}
    assert shell.ran("git fetch --quiet origin 42-saving-crash")


def test_check_unreviewed_counts_a_merge_with_a_conflict_resolution(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "check_unreviewed")
    install_shell(monkeypatch, script, unreviewed_shell("c2\nc3", merged_tree="t4"))

    printed = run_main(
        monkeypatch, capsys, script, {"pr": 9, "last_reviewed": "r1", "plan_file": "implementation-plan-42.md"}
    )

    assert printed == {"unreviewed": True, "commits": ["c3"], "head_sha": "c3full"}


def test_check_unreviewed_finds_nothing_when_no_commit_follows_the_review(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "check_unreviewed")
    install_shell(monkeypatch, script, unreviewed_shell(""))

    printed = run_main(
        monkeypatch, capsys, script, {"pr": 9, "last_reviewed": "r1", "plan_file": "implementation-plan-42.md"}
    )

    assert printed == {"unreviewed": False, "commits": [], "head_sha": "c3full"}


def test_check_unreviewed_lists_a_conflict_merge_that_takes_the_base_side(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`git show --cc` prints nothing for this merge, yet it drops the change of the pull request."""
    monkeypatch.chdir(tmp_path)

    def git(*arguments: str) -> str:
        completed = subprocess.run(["git", *arguments], capture_output=True, text=True, encoding="utf-8", check=False)
        return completed.stdout.strip()

    def commit_file(text: str) -> str:
        Path("feature.txt").write_text(text, encoding="utf-8")
        git("add", "feature.txt")
        git("commit", "--quiet", "-m", "change")
        return git("rev-parse", "HEAD")

    git("init", "--quiet", "--initial-branch=main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    commit_file("base\n")
    git("checkout", "--quiet", "-b", "feature")
    reviewed = commit_file("feature\n")
    git("checkout", "--quiet", "main")
    commit_file("base version\n")
    git("checkout", "--quiet", "feature")
    git("merge", "--quiet", "main")
    head = commit_file("base version\n")
    script = load_skill_script(SKILL, "check_unreviewed")

    assert script.unreviewed_commits(reviewed, head, "implementation-plan-42.md") == [head[:10]]


def test_the_report_and_the_label_reasons_read_the_same_limits_as_the_capped_end() -> None:
    skill = load_skill(SKILLS_FOLDER / SKILL)
    capped = skill.blocks["capped"]
    finish = skill.blocks["finish"]
    assert isinstance(capped, EndBlock) and isinstance(finish, TaskBlock)
    limits_value: str = capped.outputs["limits"]
    expression = limits_value.removeprefix("{{ ").removesuffix(" }}")

    assert finish.next[0].when == limits_value
    for name in LIMITS:
        assert f"['{name}']" in expression
    for instruction in ["report.md", "finish.md"]:
        text = (SKILLS_FOLDER / SKILL / "instructions" / instruction).read_text(encoding="utf-8")
        assert text.startswith(f"{{% set limits = {expression} %}}"), f"{instruction} lists other limits."
        for name in LIMITS:
            assert f"{{% if '{name}' in limits %}}" in text, f"{instruction} has no line for the limit {name}."
