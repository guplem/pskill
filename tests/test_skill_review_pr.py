"""Tests for the review-pr skill's scripts."""

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


def test_post_findings_posts_inline_and_puts_lines_outside_the_diff_in_one_comment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "post_findings")
    shell = install_shell(
        monkeypatch, script, FakeShell(failing=["gh api repos/{owner}/{repo}/pulls/9/comments -f body=**required: Far"])
    )
    findings = [
        {"reviewer": "tests", **finding("q"), "title": "Near"},
        {"reviewer": "docs", **finding("q", "README.md"), "title": "Far"},
    ]

    printed = run_main(monkeypatch, capsys, script, {"pr": 9, "head_sha": "abc", "findings": findings})

    assert printed == {"inline": 1, "in_conversation": 1}
    conversation = next(command for command in shell.commands if "issues/9/comments" in command)
    assert "**required: Far** at `README.md:2` (docs reviewer)" in conversation


def test_post_findings_fails_when_the_conversation_comment_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "post_findings")
    install_shell(monkeypatch, script, FakeShell(failing=["gh api"]))

    with pytest.raises(SystemExit, match="1 findings could not be posted"):
        run_main(
            monkeypatch,
            capsys,
            script,
            {"pr": 9, "head_sha": "abc", "findings": [{"reviewer": "tests", **finding("q")}]},
        )
