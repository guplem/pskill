"""Tests for the review-pr skill: its scripts, and the copies of the finding acceptance rules."""

import io
import json
import subprocess
from typing import Any

import pytest

from tests.skill_scripts import SKILLS_FOLDER, FakeShell, install_shell, load_skill_script, run_main

SKILL = "review-pr"
final_findings = load_skill_script(SKILL, "final_findings")
post_review = load_skill_script(SKILL, "post_review")
read_earlier_reviews = load_skill_script(SKILL, "read_earlier_reviews")
ACCEPTANCE_READERS = ["review-round", "review-pr", "review-doubt", "resolve-pr-feedback"]


def test_every_reader_has_the_same_finding_acceptance_rules() -> None:
    copies = {
        reader: (SKILLS_FOLDER / reader / "references" / "finding-acceptance.md").read_bytes()
        for reader in ACCEPTANCE_READERS
    }

    assert len(set(copies.values())) == 1, f"The copies differ: {sorted(copies)}. Change all four together."


def finding(
    title: str, severity: str = "required", file: str = "a.py", line: int = 2, quote: str = "b"
) -> dict[str, Any]:
    return {
        "reviewer": "r",
        "file": file,
        "line": line,
        "severity": severity,
        "title": title,
        "summary": "S",
        "quote": quote,
    }


class TestFinalFindings:
    def test_each_verdict_lands_on_its_own_doubt(self) -> None:
        doubts = [
            {"finding": finding("first"), "recommendation": "required"},
            {"finding": finding("second"), "recommendation": "required"},
        ]
        verdicts = [{"verdict": "drop"}, {"verdict": "suggestion"}]
        result = final_findings.final_findings([finding("kept")], doubts, verdicts)
        assert [(item["title"], item["severity"]) for item in result] == [
            ("kept", "required"),
            ("second", "suggestion"),
        ]

    def test_a_doubt_with_no_verdict_takes_the_recommendation(self) -> None:
        doubts = [
            {"finding": finding("asked"), "recommendation": "required"},
            {"finding": finding("not asked"), "recommendation": "suggestion"},
            {"finding": finding("not asked, dropped"), "recommendation": "drop"},
        ]
        result = final_findings.final_findings([], doubts, [{"verdict": "required"}])
        assert [(item["title"], item["severity"]) for item in result] == [
            ("asked", "required"),
            ("not asked", "suggestion"),
        ]

    def test_a_still_open_required_finding_of_an_earlier_review_counts_as_required(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        still_open = [{"title": "Earlier", "severity": "required", "location": "a.py:2"}]
        script_input = {"findings": [finding("new", severity="suggestion")], "doubts": [], "verdicts": []}
        printed: list[dict[str, Any]] = []
        for open_findings in (still_open, []):
            monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({**script_input, "still_open": open_findings})))
            output = io.StringIO()
            monkeypatch.setattr("sys.stdout", output)
            final_findings.main()
            printed.append(json.loads(output.getvalue()))
        assert [item["has_required"] for item in printed] == [True, False]
        assert [item["title"] for item in printed[0]["findings"]] == ["new"]


class TestPlacement:
    DIFF = "\n".join(
        [
            "diff --git a/a.py b/a.py",
            "--- a/a.py",
            "+++ b/a.py",
            "@@ -1,2 +1,3 @@",
            " a",
            "+b",
            " c",
            "diff --git a/gone.py b/gone.py",
            "--- a/gone.py",
            "+++ /dev/null",
            "@@ -1,1 +0,0 @@",
            "-x",
        ]
    )

    def test_the_diff_shows_added_and_context_lines_only(self) -> None:
        assert post_review.lines_shown_by_diff(self.DIFF) == {("a.py", 1), ("a.py", 2), ("a.py", 3)}

    def test_a_finding_keeps_its_line_while_the_quote_is_there(self) -> None:
        assert post_review.anchored_line(finding("t", line=2, quote="b"), ["a", "b", "c"]) == 2

    def test_a_finding_moves_to_the_one_line_that_holds_its_quote(self) -> None:
        assert post_review.anchored_line(finding("t", line=2, quote="moved"), ["a", "b", "x = moved"]) == 3

    def test_a_quote_on_no_line_or_on_several_lines_has_no_anchor(self) -> None:
        assert post_review.anchored_line(finding("t", line=2, quote="none"), ["a", "b"]) is None
        assert post_review.anchored_line(finding("t", line=9, quote="b"), ["b", "b"]) is None

    def test_a_finding_goes_inline_only_where_the_diff_shows_its_line(self) -> None:
        findings = [finding("shown", line=2), finding("moved", line=1, quote="c"), finding("lost", quote="zzz")]
        inline, in_body = post_review.split_findings(
            findings, post_review.lines_shown_by_diff(self.DIFF), {"a.py": ["a", "b", "c"]}
        )
        assert [(item["title"], item["line"]) for item in inline] == [("shown", 2), ("moved", 3)]
        assert [item["title"] for item in in_body] == ["lost"]

    def test_a_finding_that_moves_off_the_diff_keeps_its_new_line_in_the_body(self) -> None:
        file_lines = {"a.py": ["a", "b", "c", "d", "e", "x = moved"]}
        inline, in_body = post_review.split_findings(
            [finding("moved", line=2, quote="moved")], post_review.lines_shown_by_diff(self.DIFF), file_lines
        )
        assert inline == [] and [(item["title"], item["line"]) for item in in_body] == [("moved", 6)]


class TestText:
    def test_a_comment_starts_with_the_review_tag_and_names_no_reviewer(self) -> None:
        body = post_review.comment_body(finding("Retry has no cap", severity="suggestion"))
        assert body.startswith("**`[Suggestion]` Retry has no cap**")
        assert "reviewer" not in body

    def test_a_quote_with_backticks_keeps_its_code_span(self) -> None:
        assert post_review.code_span("a `b` c") == "``a `b` c``"
        assert post_review.code_span("`x`") == "`` `x` ``"
        assert post_review.code_span("plain") == "`plain`"

    def test_the_body_heading_names_the_diff_only_when_the_diff_is_the_reason(self) -> None:
        normal = post_review.review_body("B", [finding("t")], "<!-- m -->", fallback=False)
        refused = post_review.review_body("B", [finding("t")], "<!-- m -->", fallback=True)
        assert "Findings on lines that the diff does not show:" in normal
        assert "Findings:" in refused and "diff" not in refused

    def test_the_event_follows_has_required_except_on_the_own_pull_request(self) -> None:
        assert post_review.review_event(True, own_pull_request=False) == "REQUEST_CHANGES"
        assert post_review.review_event(False, own_pull_request=False) == "APPROVE"
        assert post_review.review_event(True, own_pull_request=True) == "COMMENT"


class TestPost:
    def run_main(
        self,
        monkeypatch: pytest.MonkeyPatch,
        author: str,
        post_results: list[tuple[int, str]],
        posted_url: str = "",
        commit: str = "c1",
        findings: list[dict[str, Any]] | None = None,
        has_required: bool = True,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        sent: list[dict[str, Any]] = []
        replies = {
            "repos/{owner}/{repo}/pulls/7": {"user": {"login": author}, "base": {"ref": "main"}},
            "user": {"login": "me"},
        }

        def fake_post(pr_number: str, review: dict[str, Any]) -> subprocess.CompletedProcess[str]:
            sent.append(review)
            code, stderr = post_results[len(sent) - 1]
            return subprocess.CompletedProcess([], code, stdout="https://review" if code == 0 else "", stderr=stderr)

        monkeypatch.setattr(post_review, "gh_api", lambda path: replies[path])
        monkeypatch.setattr(post_review, "run_checked", lambda command: TestPlacement.DIFF)
        monkeypatch.setattr(post_review, "lines_at_commit", lambda commit, paths: {"a.py": ["a", "b", "c"]})
        monkeypatch.setattr(post_review, "posted_review_url", lambda pr_number, marker: posted_url)
        monkeypatch.setattr(post_review, "post", fake_post)
        script_input = {
            "pr": 7,
            "commit": commit,
            "body": "B",
            "findings": findings if findings is not None else [finding("shown"), finding("lost", quote="zzz")],
            "has_required": has_required,
        }
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(script_input)))
        output = io.StringIO()
        monkeypatch.setattr("sys.stdout", output)
        post_review.main()
        return json.loads(output.getvalue()), sent

    def test_a_refused_review_is_posted_again_with_every_finding_in_the_body(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        printed, sent = self.run_main(monkeypatch, "author", [(1, "HTTP 422"), (0, "")])
        assert len(sent[0]["comments"]) == 1 and "comments" not in sent[1]
        assert "**`[Required]` shown** at `a.py:2`" in sent[1]["body"]
        assert "**`[Required]` lost** at `a.py:2`" in sent[1]["body"]
        assert printed == {
            "result": "changes_requested",
            "review_url": "https://review",
            "inline": 0,
            "in_body": 2,
            "fallback": True,
        }

    def test_a_refused_review_keeps_the_new_line_of_a_moved_finding(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, sent = self.run_main(
            monkeypatch, "author", [(1, "HTTP 422"), (0, "")], findings=[finding("moved", line=1, quote="c")]
        )
        assert sent[0]["comments"][0]["line"] == 3
        assert "**`[Required]` moved** at `a.py:3`" in sent[1]["body"]

    def test_a_still_open_required_finding_requests_changes_when_only_suggestions_are_new(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        printed, sent = self.run_main(
            monkeypatch, "author", [(0, "")], findings=[finding("new", severity="suggestion")], has_required=True
        )
        assert sent[0]["event"] == "REQUEST_CHANGES" and printed["result"] == "changes_requested"

    def test_the_own_pull_request_gets_a_comment_review(self, monkeypatch: pytest.MonkeyPatch) -> None:
        printed, sent = self.run_main(monkeypatch, "me", [(0, "")])
        assert sent[0]["event"] == "COMMENT"
        assert printed["result"] == "commented" and printed["inline"] == 1 and not printed["fallback"]

    def test_another_refusal_stops_the_script(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(SystemExit):
            self.run_main(monkeypatch, "author", [(1, "HTTP 403")])

    def test_a_review_that_is_already_posted_is_not_posted_again(self, monkeypatch: pytest.MonkeyPatch) -> None:
        printed, sent = self.run_main(monkeypatch, "author", [], posted_url="https://earlier")
        assert sent == [] and printed["review_url"] == "https://earlier"

    def test_the_same_review_on_a_new_commit_gets_a_new_marker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, first = self.run_main(monkeypatch, "author", [(0, "")], commit="c1")
        _, second = self.run_main(monkeypatch, "author", [(0, "")], commit="c2")
        markers = [sent[0]["body"].rsplit(post_review.REVIEW_MARKER_PREFIX, 1)[1] for sent in (first, second)]
        assert markers[0] != markers[1]

    def test_the_posted_review_is_the_one_whose_body_holds_the_marker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        reviews: list[dict[str, Any]] = [
            {"body": None, "html_url": "u1"},
            {"body": "B <!-- pr-review: abc -->", "html_url": "u2"},
        ]
        paths: list[str] = []

        def fake_gh_api_pages(path: str) -> list[dict[str, Any]]:
            paths.append(path)
            return reviews

        monkeypatch.setattr(post_review, "gh_api_pages", fake_gh_api_pages)

        assert post_review.posted_review_url("7", "<!-- pr-review: abc -->") == "u2"
        assert post_review.posted_review_url("7", "<!-- pr-review: other -->") == ""
        assert paths[0] == "repos/{owner}/{repo}/pulls/7/reviews"


class TestEarlierReviews:
    MARKER = "<!-- pr-review: abc -->"

    def test_the_reader_parses_the_text_that_post_review_writes(self) -> None:
        marker = f"{post_review.REVIEW_MARKER_PREFIX}abc -->"
        body_finding = finding("In body", severity="suggestion", file="b.py", line=4)
        reviews = [{"id": 1, "body": post_review.review_body("B", [body_finding], marker, fallback=False)}]
        comments = [
            {
                "id": 10,
                "pull_request_review_id": 1,
                "path": "a.py",
                "line": 2,
                "body": post_review.comment_body(finding("Inline")),
                "user": {"login": "bot"},
            }
        ]
        dismissed = read_earlier_reviews.earlier_findings(reviews, comments)
        assert [(item["title"], item["severity"]) for item in dismissed] == [
            ("Inline", "required"),
            ("In body", "suggestion"),
        ]
        assert "`b.py:4`" in dismissed[1]["reason"]

    def test_findings_of_marked_reviews_come_back_with_their_replies(self) -> None:
        reviews = [
            {"id": 1, "body": f"Changes needed.\n\n- **`[Required]` In body** at `b.py:4`: S\n\n{self.MARKER}"},
            {"id": 2, "body": "A human review."},
        ]
        comments = [
            {
                "id": 10,
                "pull_request_review_id": 1,
                "path": "a.py",
                "line": 3,
                "body": "**`[Suggestion]` New format**\n\nS",
                "user": {"login": "bot"},
            },
            {
                "id": 11,
                "pull_request_review_id": 1,
                "path": "a.py",
                "line": None,
                "original_line": 5,
                "body": "**required: Old format** (x reviewer)\n\nS",
                "user": {"login": "bot"},
            },
            {
                "id": 12,
                "pull_request_review_id": 1,
                "in_reply_to_id": 10,
                "path": "a.py",
                "body": "Fixed in   abc.",
                "user": {"login": "dev"},
            },
            {
                "id": 13,
                "pull_request_review_id": 2,
                "path": "a.py",
                "line": 1,
                "body": "**`[Required]` Human**",
                "user": {"login": "human"},
            },
        ]
        dismissed = read_earlier_reviews.earlier_findings(reviews, comments)
        assert [(item["title"], item["severity"]) for item in dismissed] == [
            ("New format", "suggestion"),
            ("Old format", "required"),
            ("In body", "required"),
        ]
        assert "`a.py:3`" in dismissed[0]["reason"] and "dev: Fixed in abc." in dismissed[0]["reason"]
        assert "`a.py:5`" in dismissed[1]["reason"] and "no reply" in dismissed[1]["reason"]
        assert "`b.py:4`" in dismissed[2]["reason"]

    def test_the_reader_reads_every_page_of_reviews_and_comments(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        reviews = [{"id": 1, "body": f"B\n\n- **`[Required]` In body** at `b.py:4`: S\n\n{self.MARKER}"}]
        outputs = {
            "gh api GET repos/{owner}/{repo}/pulls/7/reviews": json.dumps(reviews),
            "gh api GET repos/{owner}/{repo}/pulls/7/comments": "[]",
        }
        install_shell(monkeypatch, read_earlier_reviews, FakeShell(outputs))

        printed = run_main(monkeypatch, capsys, read_earlier_reviews, {"pr": 7})

        assert printed["count"] == 1 and printed["dismissed"][0]["title"] == "In body"
