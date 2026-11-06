"""Tests for the implement-issue skill's scripts."""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from pskill_runner.computed_values import compute, render_text
from pskill_runner.skill_loader import load_skill
from pskill_runner.skill_model import CallBlock, EndBlock, TaskBlock
from tests.skill_scripts import SKILLS_FOLDER, FakeShell, install_shell, load_skill_script, run_main

SKILL = "implement-issue"
LIMITS = ["implement_step", "get_ci_green", "critical", "resolve_items"]


def issue(**changes: Any) -> dict[str, Any]:
    """An issue as the REST API gives it."""
    return {
        "number": 42,
        "title": "Saving crashes",
        "body": "Steps.",
        "labels": [{"name": "bug"}],
        "state": "open",
        "assignees": [],
        "sub_issues_summary": {"total": 0},
        **changes,
    }


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({}, None),
        ({"sub_issues_summary": None}, None),
        ({"assignees": [{"login": "me"}]}, None),
        ({"state": "closed"}, "is closed"),
        ({"pull_request": {"url": "u"}}, "is a pull request, not an issue"),
        ({"sub_issues_summary": {"total": 3}}, "is a parent issue with 3 sub-issues: implement each sub-issue instead"),
        ({"assignees": [{"login": "ana"}, {"login": "me"}]}, "is assigned to ana, who owns the work"),
        ({"labels": [{"name": "waiting-for-design"}]}, "has the blocking labels waiting-for-design"),
    ],
)
def test_hold_reason_names_why_the_work_must_not_start(changes: dict[str, Any], reason: str | None) -> None:
    script = load_skill_script(SKILL, "read_issue")

    assert script.hold_reason(issue(**changes), "me") == reason


def test_read_issue_prints_the_issue_with_its_links_and_branches(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "read_issue")
    timeline = [{"event": "cross-referenced", "source": {"issue": {"number": 7, "title": "Related"}}}, {"event": "x"}]
    outputs = {
        "gh api GET repos/{owner}/{repo}/issues/42/timeline": json.dumps(timeline),
        "gh api GET repos/{owner}/{repo}/issues/42/comments": json.dumps(
            [{"user": {"login": "ana"}, "body": "Still."}]
        ),
        "gh api GET repos/{owner}/{repo}/issues/42": json.dumps(issue(body=None)),
        "gh api GET user": json.dumps({"login": "me"}),
        "gh api GET repos/{owner}/{repo}": json.dumps({"full_name": "O/R"}),
        "git ls-remote": "abc\trefs/heads/42-old-try\n",
    }
    install_shell(monkeypatch, script, FakeShell(outputs))

    printed = run_main(monkeypatch, capsys, script, {"request": "https://github.com/o/r/issues/42"})

    assert printed == {
        "number": 42,
        "title": "Saving crashes",
        "body": "",
        "labels": ["bug"],
        "comments": [{"author": "ana", "body": "Still."}],
        "cross_references": [{"number": 7, "title": "Related"}],
        "hold_reason": None,
        "existing_branches": ["42-old-try"],
    }


def test_read_issue_holds_a_link_to_an_issue_of_another_repository(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "read_issue")
    outputs = {"gh api GET repos/{owner}/{repo}": json.dumps({"full_name": "o/r"})}
    shell = install_shell(monkeypatch, script, FakeShell(outputs))

    printed = run_main(monkeypatch, capsys, script, {"request": "https://github.com/other/tool/issues/42"})

    assert printed["number"] == 42
    assert printed["hold_reason"] == (
        "is in the repository other/tool, not in o/r: start the skill from a checkout of other/tool"
    )
    assert not shell.ran("gh api GET repos/{owner}/{repo}/issues")


def test_checkout_default_branch_detaches_at_its_latest_commit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "checkout_default_branch")
    outputs = {"gh api GET repos/{owner}/{repo}": json.dumps({"default_branch": "trunk"})}
    shell = install_shell(monkeypatch, script, FakeShell(outputs))

    printed = run_main(monkeypatch, capsys, script)

    assert printed == {"ok": True, "default_branch": "trunk"}
    assert shell.ran("git switch --quiet --detach origin/trunk")


@pytest.mark.parametrize(
    ("shell", "reason"),
    [
        (FakeShell({"git status --porcelain": "M a.py"}), "The checkout has uncommitted changes: a.py"),
        (
            FakeShell({"gh api GET repos/{owner}/{repo}": '{"default_branch": "main"}'}, failing=["git fetch"]),
            "The branch main cannot be fetched from GitHub.",
        ),
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
    outputs = {"gh api GET user": json.dumps({"login": "me"})}
    shell = install_shell(monkeypatch, script, FakeShell(outputs, failing=["git rev-parse --verify"]))

    printed = run_main(monkeypatch, capsys, script, {"base": "origin/main", "slug": "fix-save", "issue": 42})

    assert printed == {"ok": True, "base": "main", "branch": "42-fix-save", "plan_file": "implementation-plan-42.md"}
    assert shell.ran("git switch --quiet --detach origin/main")
    assert shell.ran('gh api POST repos/{owner}/{repo}/issues/42/assignees {"assignees": ["me"]}')


@pytest.mark.parametrize(
    ("shell", "reason"),
    [
        (
            FakeShell({"git ls-remote": "abc\trefs/heads/42-fix-save"}),
            "The branch 42-fix-save already exists on GitHub.",
        ),
        (FakeShell(), "The branch 42-fix-save already exists in this checkout."),
        (FakeShell(failing=["git rev-parse", "git fetch"]), "The base branch main cannot be fetched from GitHub."),
        (
            FakeShell({"git rev-list HEAD --not --remotes": "c1\nc2"}, failing=["git rev-parse"]),
            "HEAD holds 2 commits that no branch on GitHub has. Push or move them before the switch, or they are lost.",
        ),
    ],
)
def test_checkout_base_changes_nothing_on_a_problem(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], shell: FakeShell, reason: str
) -> None:
    script = load_skill_script(SKILL, "checkout_base")
    install_shell(monkeypatch, script, shell)

    printed = run_main(monkeypatch, capsys, script, {"base": "main", "slug": "fix-save", "issue": 42})

    assert printed == {"ok": False, "reason": reason}
    assert not shell.ran("gh api POST")


DRAFT_INPUT = {
    "branch": "42-fix-save",
    "base": "main",
    "plan_file": "implementation-plan-42.md",
    "title": "Fix the crash on save",
    "issue": 42,
}
NEW_PULL_REQUEST = json.dumps({"number": 9, "html_url": "https://github.com/o/r/pull/9"})
# Last in a table of outputs: it is the start of the other GitHub paths.
REPOSITORY = "gh api GET repos/{owner}/{repo}"


def test_open_draft_pr_pushes_the_plan_and_opens_a_draft(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "open_draft_pr")
    outputs = {
        "git status --porcelain -- implementation-plan-42.md": "?? implementation-plan-42.md",
        "gh api GET repos/{owner}/{repo}/pulls?head=": "[]",
        "gh api POST repos/{owner}/{repo}/pulls": NEW_PULL_REQUEST,
        "gh api GET user": json.dumps({"login": "me"}),
        REPOSITORY: json.dumps({"owner": {"login": "ana"}}),
    }
    shell = install_shell(monkeypatch, script, FakeShell(outputs, failing=["git rev-parse --verify"]))

    printed = run_main(monkeypatch, capsys, script, DRAFT_INPUT)

    assert printed == {"pr_number": 9, "pr_url": "https://github.com/o/r/pull/9"}
    assert shell.ran("git switch --quiet --create 42-fix-save")
    assert shell.ran("git commit --quiet -m Add the implementation plan")
    assert shell.ran("git push --quiet --set-upstream origin 42-fix-save")
    assert shell.ran("gh api GET repos/{owner}/{repo}/pulls?head=ana%3A42-fix-save&state=open")
    create = next(command for command in shell.commands if command.startswith("gh api POST repos/{owner}/{repo}/pulls"))
    assert '"base": "main"' in create
    assert '"draft": true' in create
    assert '"head": "42-fix-save"' in create
    assert '"title": "Fix the crash on save"' in create
    assert "Closes #42" in create
    assert shell.ran('gh api POST repos/{owner}/{repo}/issues/9/assignees {"assignees": ["me"]}')


def test_open_draft_pr_a_second_time_reuses_the_branch_the_commit_and_the_pull_request(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "open_draft_pr")
    outputs = {
        "git branch --show-current": "42-fix-save",
        "gh api GET repos/{owner}/{repo}/pulls?head=": f"[{NEW_PULL_REQUEST}]",
        "gh api GET user": json.dumps({"login": "me"}),
        REPOSITORY: json.dumps({"owner": {"login": "ana"}}),
    }
    shell = install_shell(monkeypatch, script, FakeShell(outputs))

    printed = run_main(monkeypatch, capsys, script, {**DRAFT_INPUT, "issue": 0})

    assert printed == {"pr_number": 9, "pr_url": "https://github.com/o/r/pull/9"}
    assert not shell.ran("git switch")
    assert not shell.ran("git commit")
    assert not shell.ran("gh api POST repos/{owner}/{repo}/pulls")
    # A first run can stop between the create and the assign: the assign is safe to repeat.
    assert shell.ran('gh api POST repos/{owner}/{repo}/issues/9/assignees {"assignees": ["me"]}')


def ready_result(returncode: int, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["gh", "pr", "ready", "9"], returncode, "", stderr)


def install_mark_ready(
    monkeypatch: pytest.MonkeyPatch, draft: bool, ready: subprocess.CompletedProcess[str], **shell_options: Any
) -> tuple[Any, FakeShell]:
    script = load_skill_script(SKILL, "mark_ready")
    outputs = {"gh api GET repos/{owner}/{repo}/pulls/9": json.dumps({"draft": draft}), "git rev-parse HEAD": "def456"}
    shell = install_shell(monkeypatch, script, FakeShell(outputs, **shell_options))

    def fake_gh_pr_ready(pr_number: str) -> subprocess.CompletedProcess[str]:
        shell.commands.append(f"gh pr ready {pr_number}")
        return ready

    monkeypatch.setattr(script, "gh_pr_ready", fake_gh_pr_ready)
    return script, shell


def test_mark_ready_marks_the_draft_ready_then_removes_the_plan(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script, shell = install_mark_ready(monkeypatch, True, ready_result(0))

    printed = run_main(
        monkeypatch, capsys, script, {"pr": 9, "branch": "42-fix-save", "plan_file": "implementation-plan-42.md"}
    )

    assert printed == {"head_sha": "def456"}
    changes = [
        command
        for command in shell.commands
        if command.startswith(("gh pr ready", "gh api POST", "git rm", "git commit", "git push"))
    ]
    assert changes == [
        "gh pr ready 9",
        "git rm --quiet implementation-plan-42.md",
        "git commit --quiet -m Remove the implementation plan",
        "git push --quiet origin HEAD:42-fix-save",
    ]


def test_mark_ready_uses_the_proxy_route_when_graphql_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    refused = ready_result(1, "GitHub GraphQL is not available through this proxy (HTTP 403)")
    script, shell = install_mark_ready(monkeypatch, True, refused)

    run_main(monkeypatch, capsys, script, {"pr": 9, "branch": "42-fix-save", "plan_file": "implementation-plan-42.md"})

    assert shell.ran("gh api POST repos/{owner}/{repo}/pulls/9/ccr/ready_for_review")


def test_mark_ready_stops_on_another_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script, shell = install_mark_ready(monkeypatch, True, ready_result(1, "HTTP 401: Bad credentials\n"))

    with pytest.raises(SystemExit, match="`gh pr ready 9` failed: HTTP 401: Bad credentials"):
        run_main(
            monkeypatch, capsys, script, {"pr": 9, "branch": "42-fix-save", "plan_file": "implementation-plan-42.md"}
        )
    assert not shell.ran("gh api POST")
    assert not shell.ran("git push")


def test_mark_ready_a_second_time_only_pushes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script, shell = install_mark_ready(monkeypatch, False, ready_result(0), failing=["git ls-files"])

    run_main(monkeypatch, capsys, script, {"pr": 9, "branch": "42-fix-save", "plan_file": "implementation-plan-42.md"})

    assert not shell.ran("gh pr ready")
    assert not shell.ran("git rm")
    assert shell.ran("git push --quiet origin HEAD:42-fix-save")


def test_the_report_and_the_label_reasons_read_the_limits_of_the_script() -> None:
    skill = load_skill(SKILLS_FOLDER / SKILL)
    capped = skill.blocks["capped"]
    finish = skill.blocks["finish"]
    assert isinstance(capped, EndBlock) and isinstance(finish, TaskBlock)

    assert capped.outputs["limits"] == "{{ steps.limits.json.limits }}"
    assert finish.next[0].when == "{{ steps.limits.json.limits }}"
    script = (SKILLS_FOLDER / SKILL / "scripts" / "list_limits.py").read_text(encoding="utf-8")
    for instruction in ["report.md", "finish.md"]:
        text = (SKILLS_FOLDER / SKILL / "instructions" / instruction).read_text(encoding="utf-8")
        assert text.startswith("{% set limits = steps.limits.json.limits %}"), f"{instruction} lists other limits."
        for name in LIMITS:
            assert f'"{name}"' in script, f"list_limits.py never names the limit {name}."
            assert f"{{% if '{name}' in limits %}}" in text, f"{instruction} has no line for the limit {name}."


PUBLISH_BODY_READERS = ["implement-issue", "resolve-pr-feedback"]
PROXY_FOOTER = "\n\n---\n_Generated by [Claude Code](https://claude.ai/code)_"


def test_every_writer_of_a_description_has_the_same_publish_body_script() -> None:
    copies = {
        reader: (SKILLS_FOLDER / reader / "scripts" / "publish_body.py").read_bytes() for reader in PUBLISH_BODY_READERS
    }

    assert len(set(copies.values())) == 1, f"The copies differ: {sorted(copies)}. Change both together."
    found = sorted(path.parents[1].name for path in SKILLS_FOLDER.glob("*/scripts/publish_body.py"))
    assert found == PUBLISH_BODY_READERS


def publish(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path, current: str | None, new: str
) -> tuple[dict[str, Any], FakeShell]:
    script = load_skill_script(SKILL, "publish_body")
    body_file = tmp_path / "body.md"
    body_file.write_bytes(new.encode("utf-8"))
    outputs = {"gh api GET repos/{owner}/{repo}/pulls/9": json.dumps({"body": current})}
    shell = install_shell(monkeypatch, script, FakeShell(outputs))
    printed = run_main(monkeypatch, capsys, script, {"pr": 9, "body_file": str(body_file)})
    return printed, shell


def test_publish_body_writes_a_changed_description(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    printed, shell = publish(monkeypatch, capsys, tmp_path, "Old.", "New.\r\nLine.")

    assert printed == {"changed": True}
    assert shell.ran('gh api PATCH repos/{owner}/{repo}/pulls/9 {"body": "New.\\r\\nLine."}')


@pytest.mark.parametrize(
    ("current", "new"),
    [
        ("Same.\r\n", "Same.\n"),
        ("Same." + PROXY_FOOTER, "Same."),
        ("Same." + PROXY_FOOTER, "Same." + PROXY_FOOTER),
    ],
)
def test_publish_body_leaves_a_description_that_differs_only_in_line_endings_or_the_proxy_footer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path, current: str, new: str
) -> None:
    printed, shell = publish(monkeypatch, capsys, tmp_path, current, new)

    assert printed == {"changed": False}
    assert not shell.ran("gh api PATCH")


def test_publish_body_strips_the_proxy_footer_so_that_footers_never_stack(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    printed, shell = publish(monkeypatch, capsys, tmp_path, None, "New." + PROXY_FOOTER)

    assert printed == {"changed": True}
    assert shell.ran('gh api PATCH repos/{owner}/{repo}/pulls/9 {"body": "New."}')


def test_open_draft_pr_finds_the_pull_request_of_a_branch_that_gh_would_rewrite(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`gh api` fills `:repo` in a path, so `{owner}:repo-x` must not reach it: the owner and colon go encoded."""
    script = load_skill_script(SKILL, "open_draft_pr")
    outputs = {
        "git branch --show-current": "repo-cleanup",
        "gh api GET repos/{owner}/{repo}/pulls?head=": f"[{NEW_PULL_REQUEST}]",
        "gh api GET user": json.dumps({"login": "me"}),
        REPOSITORY: json.dumps({"owner": {"login": "ana"}}),
    }
    shell = install_shell(monkeypatch, script, FakeShell(outputs))

    run_main(monkeypatch, capsys, script, {**DRAFT_INPUT, "branch": "repo-cleanup", "issue": 0})

    assert shell.ran("gh api GET repos/{owner}/{repo}/pulls?head=ana%3Arepo-cleanup&state=open")


def on_pause_text(mode: str, steps: dict[str, Any]) -> str:
    skill = load_skill(SKILLS_FOLDER / SKILL)
    assert skill.on_pause is not None
    context = {
        "inputs": {"request": "42"},
        "steps": steps,
        "history": {},
        "run": {"id": "r-1", "mode": mode, "harness": "claude-code", "dir": "runs/r-1"},
        "skill": {"id": SKILL, "dir": str(skill.folder)},
    }
    return render_text(skill.instruction_text(skill.on_pause), context).strip()


def test_an_autonomous_pause_comments_on_the_pull_request_when_one_exists() -> None:
    text = on_pause_text(
        "autonomous", {"read_issue": {"json": {"number": 42}}, "open_draft_pr": {"json": {"pr_number": 57}}}
    )

    assert '{"number": 57, "run_id": "r-1", "body_file": "<file>"}' in text
    assert "scripts/post_comment.py" in text
    assert '"number": 42' not in text
    assert "#42" not in text
    assert "r-1" in text


def test_an_autonomous_pause_comments_on_the_issue_before_the_pull_request_exists() -> None:
    text = on_pause_text("autonomous", {"read_issue": {"json": {"number": 42}}})

    assert '{"number": 42, "run_id": "r-1", "body_file": "<file>"}' in text


def test_an_autonomous_pause_with_no_issue_yet_posts_nothing() -> None:
    text = on_pause_text("autonomous", {})

    assert "post_comment.py" not in text
    assert text


def test_an_interactive_pause_has_no_pause_steps() -> None:
    assert on_pause_text("interactive", {"read_issue": {"json": {"number": 42}}}) == ""


def post_comment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path, comments: list[Any]
) -> tuple[dict[str, Any], FakeShell]:
    script = load_skill_script(SKILL, "post_comment")
    body_file = tmp_path / "comment.md"
    body_file.write_bytes(b'Paused at `review`: $(rm -rf) "quoted".\r\n')
    outputs = {
        "gh api GET repos/{owner}/{repo}/issues/57/comments": json.dumps(comments),
        "gh api POST repos/{owner}/{repo}/issues/57/comments": json.dumps({"html_url": "https://x/57#c1"}),
    }
    shell = install_shell(monkeypatch, script, FakeShell(outputs))
    printed = run_main(monkeypatch, capsys, script, {"number": 57, "run_id": "r-1", "body_file": str(body_file)})
    return printed, shell


POSTED_PAUSE_BODY = 'Paused at `review`: $(rm -rf) "quoted".\n\n<!-- implement-issue-pause: r-1 -->'


def test_post_comment_posts_the_file_as_a_comment_with_no_shell_in_between(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    printed, shell = post_comment(
        monkeypatch, capsys, tmp_path, [{"id": 7, "body": "Another comment.", "html_url": "u7"}]
    )

    assert printed == {"comment_url": "https://x/57#c1", "posted": True}
    expected_body = json.dumps({"body": POSTED_PAUSE_BODY})
    assert shell.ran(f"gh api POST repos/{{owner}}/{{repo}}/issues/57/comments {expected_body}")


def test_post_comment_posts_a_new_comment_for_a_later_pause_and_edits_none(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    earlier = {"id": 8, "body": "Paused earlier.\n\n<!-- implement-issue-pause: r-1 -->", "html_url": "u8"}

    printed, shell = post_comment(monkeypatch, capsys, tmp_path, [earlier])

    assert printed == {"comment_url": "https://x/57#c1", "posted": True}
    assert not shell.ran("gh api PATCH")


def test_post_comment_run_twice_for_the_same_pause_posts_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    older = {"id": 6, "body": POSTED_PAUSE_BODY, "html_url": "u6"}
    same = {"id": 8, "body": POSTED_PAUSE_BODY, "html_url": "https://x/57#c8"}

    printed, shell = post_comment(
        monkeypatch, capsys, tmp_path, [older, {"id": 7, "body": "Other.", "html_url": "u7"}, same]
    )

    assert printed == {"comment_url": "https://x/57#c8", "posted": False}
    assert not shell.ran("gh api POST")


NO_LIMIT_INPUT: dict[str, Any] = {
    "build_done": True,
    "ready_runs": 1,
    "ci_runs": 1,
    "critical_rounds": 1,
    "last_critical_findings": 0,
    "pushed_since_ready": False,
    "items_left": 0,
}


@pytest.mark.parametrize(
    ("changes", "limits"),
    [
        ({}, []),
        ({"build_done": False}, ["implement_step"]),
        ({"ready_runs": 2}, ["get_ci_green"]),
        ({"critical_rounds": 6, "last_critical_findings": 1}, ["critical"]),
        ({"critical_rounds": 7, "last_critical_findings": 2}, ["critical"]),
        ({"critical_rounds": 6, "last_critical_findings": 0}, []),
        ({"critical_rounds": 5, "last_critical_findings": 1}, []),
        ({"critical_rounds": 13, "pushed_since_ready": True}, ["critical"]),
        ({"critical_rounds": 12, "pushed_since_ready": True}, []),
        ({"critical_rounds": 13, "pushed_since_ready": False}, []),
        ({"items_left": 1}, ["resolve_items"]),
        ({"build_done": False, "items_left": 2}, ["implement_step", "resolve_items"]),
    ],
)
def test_list_limits_names_each_limit_that_cut_work_short(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], changes: dict[str, Any], limits: list[str]
) -> None:
    script = load_skill_script(SKILL, "list_limits")

    printed = run_main(monkeypatch, capsys, script, {**NO_LIMIT_INPUT, **changes})

    assert printed["limits"] == limits


@pytest.mark.parametrize(
    ("changes", "unreviewed_push"),
    [
        ({"critical_rounds": 13, "pushed_since_ready": True}, True),
        ({"critical_rounds": 13, "pushed_since_ready": False}, False),
        ({"critical_rounds": 12, "pushed_since_ready": True}, False),
    ],
)
def test_list_limits_says_when_the_safety_cap_of_the_critical_rounds_left_a_push_with_no_round(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], changes: dict[str, Any], unreviewed_push: bool
) -> None:
    script = load_skill_script(SKILL, "list_limits")

    printed = run_main(monkeypatch, capsys, script, {**NO_LIMIT_INPUT, **changes})

    assert printed["unreviewed_push"] is unreviewed_push


def test_list_limits_counts_the_critical_rounds_of_the_skill() -> None:
    skill = load_skill(SKILLS_FOLDER / SKILL)
    critical_resolve = skill.blocks["critical_resolve"]
    script = load_skill_script(SKILL, "list_limits")
    assert isinstance(critical_resolve, CallBlock)

    assert critical_resolve.next[0].when == "{{ (history.critical | length) < 6 }}"
    assert script.CRITICAL_ROUNDS == 6


def test_the_safety_cap_of_the_critical_rounds_goes_to_the_limits_that_name_it() -> None:
    critical = load_skill(SKILLS_FOLDER / SKILL).blocks["critical"]
    script = load_skill_script(SKILL, "list_limits")

    assert critical.on_max_visits == "limits"
    assert critical.max_visits == script.CRITICAL_VISITS


def test_the_finish_note_lists_the_decisions_and_asks_only_what_can_change_the_pull_request() -> None:
    text = (SKILLS_FOLDER / SKILL / "instructions" / "finish.md").read_text(encoding="utf-8")

    assert "> **Decisions taken:**" in text
    assert "a name, a UI text" in text and "copies a precedent" in text and "Each risk point" in text
    assert "only what can change what the pull request does" in text


def instruction(name: str) -> str:
    return (SKILLS_FOLDER / SKILL / "instructions" / name).read_text(encoding="utf-8")


def test_the_plan_lists_the_tests_the_stale_texts_and_the_reused_code() -> None:
    text = instruction("write_plan.md")

    assert "5. **Lists**" in text
    assert "**New cases:** each new case of the change, with the name of the test that covers it." in text
    assert "**Stale texts:** each text that `git grep` finds for a name or a value that the change renames" in text
    assert '**Reused code:** for each new piece, the existing code that it reuses, or "none found".' in text
    assert "6. **Checks:**" in text and "7. **Out of scope.**" in text


def test_the_build_proves_each_test_can_fail_and_ticks_the_lists_before_the_review() -> None:
    text = instruction("implement_step.md")

    assert "break the guarded code on purpose" in text
    assert "never with `git checkout -- <file>`" in text
    assert "tick each line of the three **Lists** of the plan against the diff" in text


FINDING = {"reviewer": "correctness", "title": "Missing guard"}


def rendered_instruction(
    name: str,
    limits: list[str],
    verdict: str = "fixed",
    last_findings: list[dict[str, Any]] | None = None,
    unreviewed_push: bool = False,
) -> str:
    decision = {**FINDING, "verdict": verdict, "reason": "Added it."}
    fixed = {"outputs": {"decisions": [decision], "fixed": int(verdict == "fixed"), "left": 0}}
    findings = [FINDING] if last_findings is None else last_findings
    context = {
        "steps": {
            "limits": {"json": {"limits": limits, "unreviewed_push": unreviewed_push}},
            "open_draft_pr": {"json": {"pr_number": 9, "pr_url": "https://x/9"}},
            "critical": {"outputs": {"findings": findings, "reviewed_sha": "c6c6c6c6c6c6c6"}},
            "critical_resolve": fixed,
            "get_ci_green": {"outputs": {"state": "passed", "failed_checks": [], "head_sha": "h5", "fixes": 0}},
            "write_description": {"summary": "S"},
            "finish": {"labels": [], "reasons": "R"},
        },
        "history": {
            "implement_step": [{}],
            "review": [{}, {}],
            "resolve": [],
            "answer_comments": [],
            "critical": [{}] * 6,
            "critical_resolve": [fixed] * 6,
            "get_ci_green": [{"outputs": {"fixes": 0}}],
        },
        "skill": {"id": SKILL, "dir": "skill"},
    }
    return render_text(instruction(name), context)


@pytest.mark.parametrize("name", ["finish.md", "report.md"])
def test_the_critical_limit_names_the_fixes_that_no_review_saw(name: str) -> None:
    text = rendered_instruction(name, ["critical"])

    assert (
        "he critical rounds stopped at their cap after 6 rounds, and the last critical round was not clean. The head"
        ' has an unreviewed fix: no review saw the commits after c6c6c6c6c6, which fix: "Missing guard".\n'
    ) in text


@pytest.mark.parametrize("name", ["finish.md", "report.md"])
def test_the_critical_limit_names_a_last_round_whose_findings_got_no_fix(name: str) -> None:
    text = rendered_instruction(name, ["critical"], verdict="dismissed")

    assert (
        "he critical rounds stopped at their cap after 6 rounds, and the last critical round was not clean: its"
        " findings got no fix, and no later round checked them.\n"
    ) in text
    assert "unreviewed fix" not in text


@pytest.mark.parametrize("name", ["finish.md", "report.md"])
def test_the_critical_limit_names_a_push_that_the_safety_cap_left_with_no_round(name: str) -> None:
    text = rendered_instruction(name, ["critical"], last_findings=[], unreviewed_push=True)

    assert (
        "he critical rounds stopped at their cap after 6 rounds. The head has an unreviewed fix: no review saw the"
        " commits after c6c6c6c6c6, and a push after the safety cap of the critical rounds got no round.\n"
    ) in text
    assert "not clean" not in text


@pytest.mark.parametrize("name", ["finish.md", "report.md"])
def test_no_critical_limit_names_no_unreviewed_commit(name: str) -> None:
    assert "c6c6c6c6c6" not in rendered_instruction(name, [])


def test_the_report_counts_the_review_and_the_critical_rounds() -> None:
    assert "- Review rounds: 2, then 6 critical rounds." in rendered_instruction("report.md", [])


SCOPED_CALLS = ["review", "resolve", "critical", "critical_resolve", "answer_comments"]


@pytest.mark.parametrize("name", SCOPED_CALLS)
def test_every_review_and_resolution_pins_the_scope_to_the_head_of_the_first_review_round(name: str) -> None:
    block = load_skill(SKILLS_FOLDER / SKILL).blocks[name]
    assert isinstance(block, CallBlock)
    first_round = {"outputs": {"findings": [], "reviewed_sha": "r1"}}
    later_round = {"outputs": {"findings": [], "reviewed_sha": "r2"}}

    assert compute(block.inputs["scope_sha"], {"history": {}}) == ""
    assert compute(block.inputs["scope_sha"], {"history": {"review": [first_round, later_round]}}) == "r1"
