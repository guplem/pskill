"""Tests for the review-pr skill's scripts."""

import subprocess
from typing import Any

import pytest

from tests.skill_scripts import FakeShell, install_shell, load_skill_script, run_main

SKILL = "review-pr"


def test_read_pr_lists_the_changed_paths_and_the_code_paths_without_the_plan(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "read_pr")
    changed = "src/app.py\nREADME.md\ndocs/guide.txt\nimplementation-plan-42.md\ntests/test_app.py\n"
    install_shell(monkeypatch, script, FakeShell({"git diff --name-only origin/main...abc": changed}))

    printed = run_main(
        monkeypatch, capsys, script, {"base": "main", "head_sha": "abc", "plan_file": "implementation-plan-42.md"}
    )

    assert printed == {
        "paths": ["src/app.py", "README.md", "docs/guide.txt", "tests/test_app.py"],
        "code_paths": ["src/app.py", "tests/test_app.py"],
    }


APP_AT_HEAD = "def add(a, b):\n    return a - b\n"


def finding(quote: str, file: str = "calc.py") -> dict[str, Any]:
    return {"file": file, "line": 2, "severity": "required", "title": "Wrong operator", "summary": "S.", "quote": quote}


def collect(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], findings: list[dict[str, Any]]
) -> dict[str, Any]:
    script = load_skill_script(SKILL, "collect_findings")
    shell = FakeShell({"git show abc:calc.py": APP_AT_HEAD, "git show origin/main:gone.py": "x = 1\n"})
    shell.failing = ["git show abc:gone.py", "git show abc:missing.py", "git show origin/main:missing.py"]
    install_shell(monkeypatch, script, shell)
    results = [{"reviewer": "correctness", "findings": findings}, {"reviewer": "tests", "findings": []}]
    printed: dict[str, Any] = run_main(
        monkeypatch, capsys, script, {"results": results, "head_sha": "abc", "base": "main"}
    )
    return printed


def test_collect_findings_keeps_a_quoted_finding_with_its_reviewer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    printed = collect(monkeypatch, capsys, [finding("return a - b")])

    assert printed == {"findings": [{"reviewer": "correctness", **finding("return a - b")}], "count": 1, "dropped": []}


def test_every_line_of_a_multi_line_quote_must_be_in_the_file(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    printed = collect(
        monkeypatch, capsys, [finding("def add(a, b):\n  return a - b"), finding("def add(a, b):\nreturn a * b")]
    )

    assert printed["count"] == 1
    assert printed["dropped"] == [{"reviewer": "correctness", "title": "Wrong operator"}]


@pytest.mark.parametrize(("quote", "file"), [("x = 1", "gone.py")])
def test_a_quote_from_a_file_that_the_change_deletes_is_checked_against_the_base(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], quote: str, file: str
) -> None:
    printed = collect(monkeypatch, capsys, [finding(quote, file)])

    assert printed["count"] == 1


@pytest.mark.parametrize(("quote", "file"), [("  ", "calc.py"), ("return a * b", "calc.py"), ("x", "missing.py")])
def test_a_finding_without_a_real_quote_is_dropped(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], quote: str, file: str
) -> None:
    printed = collect(monkeypatch, capsys, [finding(quote, file)])

    assert printed["count"] == 0
    assert len(printed["dropped"]) == 1


def test_collect_findings_sorts_the_findings_by_file_and_line_so_that_copies_come_together(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "collect_findings")
    install_shell(monkeypatch, script, FakeShell({"git show abc:": APP_AT_HEAD}))
    results = [
        {
            "reviewer": "correctness",
            "findings": [finding("return a - b", "b.py"), {**finding("def add(a, b):", "a.py"), "line": 9}],
        },
        {
            "reviewer": "tests",
            "findings": [{**finding("def add(a, b):", "a.py"), "line": 1}, finding("return a - b", "b.py")],
        },
    ]

    printed = run_main(monkeypatch, capsys, script, {"results": results, "head_sha": "abc", "base": "main"})

    order = [(item["file"], item["line"], item["reviewer"]) for item in printed["findings"]]
    assert order == [("a.py", 1, "tests"), ("a.py", 9, "correctness"), ("b.py", 2, "correctness"), ("b.py", 2, "tests")]


INLINE_ENDPOINT = "gh api repos/{owner}/{repo}/pulls/9/comments"


def outside_diff_shell(title: str) -> FakeShell:
    """GitHub refuses an inline comment on a line that the diff does not show with HTTP 422."""
    shell = FakeShell(failing=[f"{INLINE_ENDPOINT} -f body=**required: {title}"])
    shell.failure_stderr = "gh: Validation Failed (HTTP 422)"
    return shell


def test_post_findings_posts_inline_and_puts_lines_outside_the_diff_in_one_comment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "post_findings")
    shell = install_shell(monkeypatch, script, outside_diff_shell("Far"))
    findings = [
        {"reviewer": "tests", **finding("q"), "title": "Near"},
        {"reviewer": "docs", **finding("q", "README.md"), "title": "Far"},
    ]

    printed = run_main(monkeypatch, capsys, script, {"pr": 9, "head_sha": "abc", "findings": findings})

    assert printed == {"inline": 1, "in_conversation": 1, "already_posted": 0}
    conversation = next(
        command for command in shell.commands if command.startswith("gh api repos/{owner}/{repo}/issues/9/comments -f")
    )
    assert "**required: Far** at `README.md:2` (docs reviewer)" in conversation


def test_post_findings_stops_on_an_inline_failure_that_is_not_a_line_outside_the_diff(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "post_findings")
    shell = install_shell(monkeypatch, script, FakeShell(failing=[f"{INLINE_ENDPOINT} -f"]))
    shell.failure_stderr = "gh: Bad credentials (HTTP 401)"

    with pytest.raises(subprocess.CalledProcessError):
        run_main(
            monkeypatch,
            capsys,
            script,
            {"pr": 9, "head_sha": "abc", "findings": [{"reviewer": "tests", **finding("q")}]},
        )
    assert not shell.ran("gh api repos/{owner}/{repo}/issues/9/comments -f")


def test_post_findings_skips_the_findings_that_an_earlier_try_already_posted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "post_findings")
    near = {"reviewer": "tests", **finding("q"), "title": "Near"}
    far = {"reviewer": "docs", **finding("q", "README.md"), "title": "Far"}
    shell = install_shell(monkeypatch, script, outside_diff_shell("Far"))
    run_main(monkeypatch, capsys, script, {"pr": 9, "head_sha": "abc", "findings": [near, far]})
    posted_bodies = "\n".join(command for command in shell.commands if " -f body=" in command)

    resumed = install_shell(monkeypatch, script, FakeShell({f"{INLINE_ENDPOINT} --paginate": posted_bodies}))
    printed = run_main(monkeypatch, capsys, script, {"pr": 9, "head_sha": "abc", "findings": [near, far]})

    assert printed == {"inline": 0, "in_conversation": 0, "already_posted": 2}
    assert not resumed.ran(f"{INLINE_ENDPOINT} -f")
    assert not resumed.ran("gh api repos/{owner}/{repo}/issues/9/comments -f")


def test_post_findings_fails_when_the_conversation_comment_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "post_findings")
    shell = install_shell(monkeypatch, script, outside_diff_shell("Wrong operator"))
    shell.failing.append("gh api repos/{owner}/{repo}/issues/9/comments -f")

    with pytest.raises(SystemExit, match="1 findings could not be posted"):
        run_main(
            monkeypatch,
            capsys,
            script,
            {"pr": 9, "head_sha": "abc", "findings": [{"reviewer": "tests", **finding("q")}]},
        )
