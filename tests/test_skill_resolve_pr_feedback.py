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
) -> dict[str, Any]:
    script = load_skill_script(SKILL, "collect_items")
    outputs = {
        "gh api repos/{owner}/{repo}/pulls/9/comments": json.dumps([inline]),
        "gh api repos/{owner}/{repo}/pulls/9/reviews": json.dumps([reviews]),
        "gh api repos/{owner}/{repo}/issues/9/comments": json.dumps([conversation]),
    }
    install_shell(monkeypatch, script, FakeShell(outputs))
    printed: dict[str, Any] = run_main(monkeypatch, capsys, script, {"pr": 9, "findings": [FINDING]})
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
        comment(5, "Someone works on it.", path="a.py", line=8, reactions={"eyes": 1}),
    ]
    reviews = [comment(2, "")]
    conversation = [comment(6, "CI passed.", user={"login": "github-actions[bot]"})]

    printed = collect(monkeypatch, capsys, inline, reviews, conversation)

    assert printed["queue"] == [{"kind": "finding", **FINDING}]


def test_collect_items_leaves_out_a_copilot_notice_but_keeps_a_copilot_review(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    copilot = {"login": "copilot-pull-request-reviewer[bot]"}
    notice = comment(7, "Copilot was unable to review this pull request because of a quota limit.", user=copilot)
    review = comment(8, "The guard misses None.", user=copilot)

    printed = collect(monkeypatch, capsys, [], [notice, review], [])

    assert [item.get("id") for item in printed["queue"]] == [None, 8]


def test_claim_item_adds_the_eyes_reaction_to_a_comment_that_can_take_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "claim_item")
    shell = install_shell(monkeypatch, script, FakeShell())

    printed = run_main(
        monkeypatch, capsys, script, {"item": {"kind": "comment", "id": 5, "comment_kind": "conversation"}}
    )

    assert printed == {"claimed": True}
    assert shell.commands == ["gh api repos/{owner}/{repo}/issues/comments/5/reactions -f content=eyes"]


@pytest.mark.parametrize("item", [{"kind": "finding"}, {"kind": "comment", "id": 2, "comment_kind": "review"}])
def test_claim_item_leaves_a_finding_and_a_review_body_alone(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], item: dict[str, Any]
) -> None:
    script = load_skill_script(SKILL, "claim_item")
    shell = install_shell(monkeypatch, script, FakeShell())

    assert run_main(monkeypatch, capsys, script, {"item": item}) == {"claimed": False}
    assert shell.commands == []


def test_finish_item_replies_in_the_thread_of_an_inline_comment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "finish_item")
    shell = install_shell(monkeypatch, script, FakeShell({"git rev-parse --short HEAD": "abc"}))
    item = {"kind": "comment", "id": 7, "comment_kind": "inline", "author": "ana", "thread_id": 1, "body": "Rename it."}

    printed = run_main(
        monkeypatch, capsys, script, {"pr": 9, "item": item, "decision": {"verdict": "fixed", "reason": "Renamed."}}
    )

    assert printed == {
        "replied": True,
        "decision": {
            "kind": "comment",
            "reviewer": "",
            "title": "Rename it.",
            "verdict": "fixed",
            "reason": "Renamed.",
        },
    }
    assert shell.commands[-1] == (
        "gh api repos/{owner}/{repo}/pulls/9/comments/1/replies "
        "-f body=**Fixed** in abc. Renamed.\n\n<!-- resolve-pr-feedback-reply: 7 -->"
    )


def test_finish_item_quotes_a_review_comment_in_a_new_conversation_comment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "finish_item")
    shell = install_shell(monkeypatch, script, FakeShell())
    item = {"kind": "comment", "id": 2, "comment_kind": "review", "author": "ana", "body": "\nNice.\nThanks."}

    printed = run_main(
        monkeypatch, capsys, script, {"pr": 9, "item": item, "decision": {"verdict": "dismissed", "reason": "Thanks!"}}
    )

    assert printed["decision"]["title"] == "Nice."
    assert shell.commands[-1] == (
        "gh api repos/{owner}/{repo}/issues/9/comments "
        "-f body=> \n> Nice.\n> Thanks.\n\n**Dismissed**. Thanks!\n\n<!-- resolve-pr-feedback-reply: 2 -->"
    )


def test_finish_item_only_records_a_finding(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "finish_item")
    shell = install_shell(monkeypatch, script, FakeShell())

    printed = run_main(
        monkeypatch,
        capsys,
        script,
        {"pr": 9, "item": {"kind": "finding", **FINDING}, "decision": {"verdict": "fixed", "reason": "Added."}},
    )

    assert printed == {
        "replied": False,
        "decision": {
            "kind": "finding",
            "reviewer": "tests",
            "title": "No test",
            "verdict": "fixed",
            "reason": "Added.",
        },
    }
    assert shell.commands == []
