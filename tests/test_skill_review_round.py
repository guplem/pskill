"""Tests for the review-round skill's scripts."""

import re
from typing import Any

import pytest
import yaml

from pskill_runner.computed_values import compute, render_text
from tests.skill_scripts import SKILLS_FOLDER, FakeShell, install_shell, load_skill_script, run_main

SKILL = "review-round"


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
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    findings: list[dict[str, Any]],
    round_number: int = 1,
    critical: bool = False,
) -> dict[str, Any]:
    script = load_skill_script(SKILL, "collect_findings")
    shell = FakeShell({"git show abc:calc.py": APP_AT_HEAD, "git show origin/main:gone.py": "x = 1\n"})
    shell.failing = ["git show abc:gone.py", "git show abc:missing.py", "git show origin/main:missing.py"]
    install_shell(monkeypatch, script, shell)
    results = [{"reviewer": "correctness", "findings": findings}, {"reviewer": "tests", "findings": []}]
    script_input = {"results": results, "head_sha": "abc", "base": "main", "round": round_number, "critical": critical}
    printed: dict[str, Any] = run_main(monkeypatch, capsys, script, script_input)
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

    script_input = {"results": results, "head_sha": "abc", "base": "main", "round": 1, "critical": False}
    printed = run_main(monkeypatch, capsys, script, script_input)

    order = [(item["file"], item["line"], item["reviewer"]) for item in printed["findings"]]
    assert order == [("a.py", 1, "tests"), ("a.py", 9, "correctness"), ("b.py", 2, "correctness"), ("b.py", 2, "tests")]


SUGGESTION = {**finding("return a - b"), "severity": "suggestion", "title": "Name it subtract"}


def test_round_1_keeps_the_suggestions(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    printed = collect(monkeypatch, capsys, [finding("return a - b"), SUGGESTION])

    assert [item["severity"] for item in printed["findings"]] == ["required", "suggestion"]


@pytest.mark.parametrize(("round_number", "critical"), [(2, False), (3, False), (4, False), (1, True)])
def test_from_round_2_on_and_in_a_critical_round_every_suggestion_is_left_out(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], round_number: int, critical: bool
) -> None:
    printed = collect(monkeypatch, capsys, [finding("return a - b"), SUGGESTION], round_number, critical)

    assert printed == {"findings": [{"reviewer": "correctness", **finding("return a - b")}], "count": 1, "dropped": []}


def reviewer_rows() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    block = yaml.safe_load((SKILLS_FOLDER / "review-round" / "skill.yaml").read_text(encoding="utf-8"))["blocks"][
        "review"
    ]
    return block, {row["name"]: row for row in block["for_each"]}


def test_every_reviewer_only_reads() -> None:
    block, _ = reviewer_rows()

    assert block["tools"] == "read"


def test_the_rule_reviewers_run_on_the_standard_tier_and_the_bug_hunters_on_the_deep_tier() -> None:
    block, rows = reviewer_rows()

    assert block["tier"] == "{{ item.tier | default('') }}"
    assert {name: row.get("tier") for name, row in rows.items()} == {
        "correctness": "deep",
        "tests": "standard",
        "completeness": None,
        "conventions": "standard",
        "docs": "standard",
        "critical-bugs": "deep",
    }


LAST_ROUNDS = {"correctness": 4, "completeness": 3, "docs": 3, "tests": 2, "conventions": 2}
TABLE_ROW = re.compile(r"^ *# \| (?P<name>[a-z-]+) +\| (?P<last>\d+|critical) +\|", re.MULTILINE)


def runs(name: str, round_number: int = 1, code_paths: list[str] | None = None, critical: bool = False) -> bool:
    """Whether the row of a reviewer runs in a round, by its `when` as the runner computes it."""
    _, rows = reviewer_rows()
    context = {
        "inputs": {"round": round_number, "critical": critical},
        "steps": {"read_pr": {"json": {"code_paths": ["src/app.py"] if code_paths is None else code_paths}}},
    }
    return bool(compute(rows[name]["when"], context))


@pytest.mark.parametrize(("name", "last"), LAST_ROUNDS.items())
def test_each_reviewer_runs_from_round_1_to_its_last_round(name: str, last: int) -> None:
    assert [round_number for round_number in range(1, 6) if runs(name, round_number)] == list(range(1, last + 1))


def test_the_table_comment_lists_the_last_round_of_every_reviewer() -> None:
    text = (SKILLS_FOLDER / SKILL / "skill.yaml").read_text(encoding="utf-8")

    table = {match["name"]: match["last"] for match in TABLE_ROW.finditer(text)}

    assert table == {**{name: str(last) for name, last in LAST_ROUNDS.items()}, "critical-bugs": "critical"}


@pytest.mark.parametrize("round_number", [1, 2, 3, 4, 5])
def test_a_critical_round_runs_only_critical_bugs_whatever_its_number(round_number: int) -> None:
    _, rows = reviewer_rows()

    assert [name for name in rows if runs(name, round_number, critical=True)] == ["critical-bugs"]


def test_critical_bugs_runs_in_no_other_round() -> None:
    assert not any(runs("critical-bugs", round_number) for round_number in range(1, 6))


@pytest.mark.parametrize("name", ["correctness", "tests", "critical-bugs"])
def test_a_change_of_docs_only_skips_the_code_reviewers_in_every_round(name: str) -> None:
    assert not any(
        runs(name, round_number, code_paths=[], critical=critical)
        for round_number in range(1, 5)
        for critical in (False, True)
    )


def test_the_focus_of_critical_bugs_is_the_critical_bar() -> None:
    _, rows = reviewer_rows()

    assert rows["critical-bugs"]["focus"].startswith(
        "Critical bugs: only what the new code of this pull request breaks"
    )


FOCUS_TERMS = [
    "each changed entry point (a route, a command, a public function), query, export, or stored shape",
    "dates and time zones",
    "changed exit or status codes",
]


def test_the_focus_of_critical_bugs_names_generic_entry_points_and_failures() -> None:
    _, rows = reviewer_rows()
    focus = " ".join(rows["critical-bugs"]["focus"].split())

    assert [term for term in FOCUS_TERMS if term not in focus] == []
    assert "5xx" not in focus


def review_text(round_number: int = 1, **inputs: Any) -> str:
    """The instruction of the review block, as a reviewer of a round gets it."""
    template = (SKILLS_FOLDER / SKILL / "instructions" / "review.md").read_text(encoding="utf-8")
    context = {
        "inputs": {
            "pr": 9,
            "round": round_number,
            "critical": False,
            "scope_sha": "",
            "dismissed": [],
            "reported": [],
            **inputs,
        },
        "item": {"name": "correctness", "focus": "Correctness."},
        "steps": {"checkout": {"outputs": {"head_sha": "abc", "base": "main", "plan_file": ""}}},
        "skill": {"dir": ".pskill/skills/review-round"},
    }
    return render_text(template, context)


@pytest.mark.parametrize("round_number", [1, 2, 3, 4])
def test_every_round_reviews_the_whole_pull_request_at_the_head_commit(round_number: int) -> None:
    text = review_text(round_number)

    assert "Review the whole pull request" in text
    assert "`git diff origin/main...abc`" in text
    assert "the scope commit is `abc`, the head commit" in text
    assert "own fixes" not in text


ROUND_2_BAR = "**Only required findings:**"
ROUND_3_BAR = "**The round 3 bar:**"
CRITICAL_BAR = "**The critical bar:**"


@pytest.mark.parametrize(
    ("round_number", "critical", "bar"),
    [
        (1, False, None),
        (2, False, ROUND_2_BAR),
        (3, False, ROUND_3_BAR),
        (4, False, CRITICAL_BAR),
        (5, False, CRITICAL_BAR),
        (1, True, CRITICAL_BAR),
        (3, True, CRITICAL_BAR),
    ],
)
def test_each_round_gets_its_own_bar(round_number: int, critical: bool, bar: str | None) -> None:
    text = review_text(round_number, critical=critical)

    assert [name for name in (ROUND_2_BAR, ROUND_3_BAR, CRITICAL_BAR) if name in text] == ([bar] if bar else [])


def test_the_round_3_bar_keeps_broken_code_false_texts_and_missing_deliverables_only() -> None:
    text = review_text(3)

    assert (
        "only these: a wrong result, a crash, data loss, a security hole, a broken contract for a caller, a type"
        " error, a text (doc, comment, ADR, message) that the change makes false, or a deliverable that the issue or"
        " the plan asks for and the pull request does not build." in text
    )
    assert "Skip style, pattern, convention, and test findings." in text


def test_the_critical_bar_asks_for_every_failure_path_with_its_input() -> None:
    text = review_text(4)

    assert "Report only what the new code of this pull request breaks" in text
    assert "Each finding names the input or call that reaches the line and the wrong outcome" in text
    assert "Report every failure path that you find in this one report." in text
    assert "Every finding is `required`." in text
    assert "Out of scope: only a failure that the base branch already shows through the same entry point." in text


def test_the_critical_bar_names_generic_failures() -> None:
    text = review_text(4)

    assert "a crash or an error answer" in text
    assert "a broken contract for an existing caller of each changed entry point (a route, a command, a public" in text
    assert "5xx" not in text


@pytest.mark.parametrize("round_number", [2, 3])
def test_in_rounds_2_and_3_a_wrong_outcome_is_never_a_suggestion(round_number: int) -> None:
    assert "A wrong outcome is never a suggestion." in review_text(round_number)


SIBLING_RULE = (
    "List every sibling site of the same problem (the same entry point, the same input shape, the same helper) in"
    " the same finding; keep none back for a later round."
)


@pytest.mark.parametrize(("round_number", "critical"), [(1, False), (2, False), (3, False), (4, False), (1, True)])
def test_every_round_lists_every_sibling_site_in_the_same_finding(round_number: int, critical: bool) -> None:
    assert review_text(round_number, critical=critical).count(SIBLING_RULE) == 1


def test_a_round_with_no_earlier_finding_has_no_earlier_findings_text() -> None:
    assert "**Earlier findings:**" not in review_text(2)


@pytest.mark.parametrize(
    "inputs",
    [
        {"dismissed": [{"reviewer": "docs", "title": "Stale", "reason": "Not stale."}]},
        {"reported": [{"reviewer": "tests", "file": "a.py", "line": 3, "title": "No test", "severity": "required"}]},
    ],
)
def test_earlier_findings_are_listed_only_so_that_the_reviewers_skip_them(inputs: dict[str, Any]) -> None:
    text = review_text(2, **inputs)

    assert "the lists below name earlier findings only so that you skip them" in text
    assert (
        "Review every changed function of the whole diff, the fix commits included, as for the first time;"
        " skip only the exact problems listed." in text
    )
    assert "not the last fix commits" not in text
    assert "The same finding means the same wrong outcome at the same place" in text
    assert "a test, text, or convention finding at a line does not cover a bug at that line" in text
    assert (
        "A listed suggestion was never fixed, and it never covers a wrong outcome: when its problem is a wrong"
        " outcome under the bar of this round, report it as `required`." in text
    )


def test_each_earlier_finding_is_listed_with_its_severity_and_its_reviewer() -> None:
    text = review_text(
        2,
        reported=[{"reviewer": "tests", "file": "a.py", "line": 3, "title": "No test", "severity": "suggestion"}],
        dismissed=[
            {"reviewer": "docs", "title": "Stale", "severity": "required", "reason": "Not stale."},
            {"reviewer": "correctness", "title": "Null role", "reason": "The route checks it."},
        ],
    )

    assert '- [suggestion] "No test" at `a.py:3` (tests reviewer)' in text
    assert '- [required] "Stale" (docs reviewer): Not stale.' in text
    assert '- "Null role" (correctness reviewer): The route checks it.' in text


DISMISSED = [{"reviewer": "correctness", "title": "Null role", "reason": "The route checks it."}]
NEW_EVIDENCE = (
    "a concrete failure path (its input and its wrong outcome) that the reason does not answer is new evidence"
)


def test_in_a_critical_round_a_failure_path_that_a_dismissal_does_not_answer_is_new_evidence() -> None:
    assert NEW_EVIDENCE in review_text(1, critical=True, dismissed=DISMISSED)


def test_in_a_review_round_a_dismissal_stands_against_a_different_opinion() -> None:
    text = review_text(4, dismissed=DISMISSED)

    assert "A different opinion on a dismissal reason is not new evidence." in text
    assert NEW_EVIDENCE not in text


def test_the_round_has_no_delta_commit_and_an_optional_scope_commit() -> None:
    skill = yaml.safe_load((SKILLS_FOLDER / "review-round" / "skill.yaml").read_text(encoding="utf-8"))

    assert "since_sha" not in skill["inputs"]
    assert (skill["inputs"]["scope_sha"]["optional"], skill["inputs"]["scope_sha"]["default"]) == (True, "")
    assert "scope_sha" not in skill["outputs"]


@pytest.mark.parametrize("critical", [False, True])
def test_a_pinned_scope_commit_ends_the_acceptance_scope_but_the_round_reviews_the_whole_diff(critical: bool) -> None:
    text = review_text(3, critical=critical, scope_sha="s1")

    assert "`git diff origin/main...abc`" in text
    assert "the scope commit is `s1`, the head of the first review round" in text
    assert (
        "The commits after `s1` are the pull request's own fixes: their lines are in scope, but an older function"
        " that they touch does not bring its older problems into scope." in text
    )
