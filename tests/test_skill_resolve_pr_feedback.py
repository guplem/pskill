"""Tests for the resolve-pr-feedback skill's scripts."""

import json
from typing import Any

import pytest

from tests.skill_scripts import FakeShell, install_shell, load_skill_script, run_main

SKILL = "resolve-pr-feedback"
FINDING = {
    "reviewer": "tests",
    "file": "a.py",
    "line": 3,
    "severity": "required",
    "title": "No test",
    "summary": "S",
    "quote": "q",
}


def comment(comment_id: int, body: str, **changes: Any) -> dict[str, Any]:
    return {"id": comment_id, "user": {"login": "ana"}, "body": body, **changes}


def collect(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    inline: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    conversation: list[dict[str, Any]],
    findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    script = load_skill_script(SKILL, "collect_items")
    outputs = {
        "gh api GET repos/{owner}/{repo}/pulls/9/comments": json.dumps(inline),
        "gh api GET repos/{owner}/{repo}/pulls/9/reviews": json.dumps(reviews),
        "gh api GET repos/{owner}/{repo}/issues/9/comments": json.dumps(conversation),
        "gh api GET user": json.dumps({"login": "me"}),
        "gh api GET repos/{owner}/{repo}/pulls/comments/5/reactions?content=eyes": json.dumps(
            [{"user": {"login": "me"}}]
        ),
        "gh api GET repos/{owner}/{repo}/pulls/comments/7/reactions?content=eyes": json.dumps(
            [{"user": {"login": "bea"}}]
        ),
    }
    install_shell(monkeypatch, script, FakeShell(outputs))
    script_input = {"pr": 9, "findings": [FINDING] if findings is None else findings}
    printed: dict[str, Any] = run_main(monkeypatch, capsys, script, script_input)
    return printed


def test_collect_items_lists_the_findings_then_every_kind_of_comment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inline = [comment(1, "Rename this.", path="a.py", line=4, in_reply_to_id=None)]
    printed = collect(monkeypatch, capsys, inline, [comment(2, "Looks good overall.")], [comment(3, "Add docs?")])

    assert printed["count"] == 4
    assert printed["queue"][0] == {"kind": "finding", **FINDING}
    assert printed["queue"][1] == {
        "kind": "comment",
        "id": 1,
        "comment_kind": "inline",
        "author": "ana",
        "path": "a.py",
        "line": 4,
        "thread_id": 1,
        "body": "Rename this.",
    }
    assert [item["comment_kind"] for item in printed["queue"][2:]] == ["review", "conversation"]
    assert printed["queue"][2]["path"] is None


def test_collect_items_leaves_out_the_addressed_comments(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    reply = "**Fixed** in abc. Done.\n\n<!-- resolve-pr-feedback-reply: 1 -->"
    inline = [
        comment(1, "Rename this.", path="a.py", line=4),
        comment(4, reply, path="a.py", line=4, in_reply_to_id=1),
        comment(5, "A run of mine works on it.", path="a.py", line=8, reactions={"eyes": 1}),
    ]
    reviews = [comment(2, "")]
    conversation = [comment(6, "CI passed.", user={"login": "github-actions[bot]"})]

    printed = collect(monkeypatch, capsys, inline, reviews, conversation)

    assert printed["queue"] == [{"kind": "finding", **FINDING}]


SUGGESTION = {**FINDING, "severity": "suggestion", "title": "Shorter name"}


def test_collect_items_queues_only_required_findings_and_lists_the_suggestions_apart(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    printed = collect(monkeypatch, capsys, [], [], [], findings=[SUGGESTION, FINDING])

    assert printed["queue"] == [{"kind": "finding", **FINDING}]
    assert printed["count"] == 1
    assert printed["suggestions"] == [SUGGESTION]


def test_collect_items_leaves_out_the_suggestions_comment_of_a_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    posted = comment(8, "Suggestions.\n\n<!-- resolve-pr-feedback-suggestions -->")

    printed = collect(monkeypatch, capsys, [], [], [posted], findings=[])

    assert printed["queue"] == []


def test_post_suggestions_posts_them_in_one_comment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "post_suggestions")
    path = "gh api POST repos/{owner}/{repo}/issues/9/comments"
    shell = install_shell(monkeypatch, script, FakeShell({path: json.dumps({"html_url": "https://x/9#c1"})}))

    printed = run_main(monkeypatch, capsys, script, {"pr": 9, "suggestions": [SUGGESTION]})

    assert printed == {"comment_url": "https://x/9#c1"}
    body = (
        "The review also made these suggestions. This pull request does not apply them; "
        "each one is for a person to take or leave:\n\n"
        "- **Shorter name** at `a.py:3` (tests): S\n\n<!-- resolve-pr-feedback-suggestions -->"
    )
    assert shell.ran(f"{path} {json.dumps({'body': body})}")


def test_collect_items_keeps_a_comment_with_the_eyes_of_another_person(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inline = [comment(7, "Rename this.", path="a.py", line=4, reactions={"eyes": 1})]

    printed = collect(monkeypatch, capsys, inline, [], [])

    assert [item.get("id") for item in printed["queue"]] == [None, 7]


def test_collect_items_leaves_out_a_copilot_notice_but_keeps_a_copilot_review(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    copilot = {"login": "copilot-pull-request-reviewer[bot]"}
    notice = comment(7, "Copilot was unable to review this pull request because of a quota limit.", user=copilot)
    review = comment(8, "The guard misses None.", user=copilot)

    printed = collect(monkeypatch, capsys, [], [notice, review], [])

    assert [item.get("id") for item in printed["queue"]] == [None, 8]


def test_claim_items_adds_the_eyes_reaction_to_each_comment_that_can_take_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "claim_items")
    shell = install_shell(monkeypatch, script, FakeShell())
    items = [
        {"kind": "finding"},
        {"kind": "comment", "id": 5, "comment_kind": "conversation"},
        {"kind": "comment", "id": 2, "comment_kind": "review"},
        {"kind": "comment", "id": 6, "comment_kind": "inline"},
    ]

    printed = run_main(monkeypatch, capsys, script, {"items": items})

    assert printed == {"claimed": 2}
    assert shell.commands == [
        "gh api repos/{owner}/{repo}/issues/comments/5/reactions -f content=eyes",
        "gh api repos/{owner}/{repo}/pulls/comments/6/reactions -f content=eyes",
    ]


INLINE = {"kind": "comment", "id": 7, "comment_kind": "inline", "author": "ana", "thread_id": 1, "body": "Rename it."}


READ_HEAD = "git ls-remote origin refs/heads/42-fix-save"


def finish(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    items: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> tuple[dict[str, Any], FakeShell]:
    script = load_skill_script(SKILL, "finish_items")
    shell = install_shell(monkeypatch, script, FakeShell({READ_HEAD: "def456\trefs/heads/42-fix-save"}))
    script_input = {"pr": 9, "branch": "42-fix-save", "items": items, "decisions": decisions}
    printed = run_main(monkeypatch, capsys, script, script_input)
    return printed, shell


def test_finish_items_replies_in_the_thread_of_an_inline_comment_with_the_commit_of_its_fix(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    printed, shell = finish(
        monkeypatch, capsys, [INLINE], [{"verdict": "fixed", "reason": "Renamed.", "commit": "abc"}]
    )

    assert printed == {
        "decisions": [
            {"kind": "comment", "reviewer": "", "title": "Rename it.", "verdict": "fixed", "reason": "Renamed."}
        ],
        "left": 0,
        "head_sha": "def456",
    }
    assert shell.commands == [
        READ_HEAD,
        "gh api repos/{owner}/{repo}/pulls/9/comments/1/replies "
        "-f body=**Fixed** in abc. Renamed.\n\n<!-- resolve-pr-feedback-reply: 7 -->",
    ]


def test_finish_items_quotes_a_review_comment_in_a_new_conversation_comment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    item = {"kind": "comment", "id": 2, "comment_kind": "review", "author": "ana", "body": "\nNice.\nThanks."}

    printed, shell = finish(monkeypatch, capsys, [item], [{"verdict": "dismissed", "reason": "Thanks!"}])

    assert printed["decisions"][0]["title"] == "Nice."
    assert shell.commands == [
        READ_HEAD,
        "gh api repos/{owner}/{repo}/issues/9/comments "
        "-f body=> Nice.\n\n**Dismissed**. Thanks!\n\n<!-- resolve-pr-feedback-reply: 2 -->",
    ]


def test_finish_items_cuts_a_long_first_line_of_the_quoted_comment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    item = {"kind": "comment", "id": 3, "comment_kind": "conversation", "author": "ana", "body": "x" * 250}

    _, shell = finish(monkeypatch, capsys, [item], [{"verdict": "dismissed", "reason": "No."}])

    assert shell.commands[-1].startswith(
        "gh api repos/{owner}/{repo}/issues/9/comments -f body=> " + "x" * 200 + "\n\n"
    )


def test_finish_items_only_records_a_finding_and_counts_the_items_with_no_decision(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    items = [{"kind": "finding", **FINDING}, INLINE]

    printed, shell = finish(monkeypatch, capsys, items, [{"verdict": "fixed", "reason": "Added.", "commit": "abc"}])

    assert printed == {
        "decisions": [
            {"kind": "finding", "reviewer": "tests", "title": "No test", "verdict": "fixed", "reason": "Added."}
        ],
        "left": 1,
        "head_sha": "def456",
    }
    # The head is read before any reply: a failed read posts nothing, and the block has no retries.
    assert shell.commands == [READ_HEAD]
