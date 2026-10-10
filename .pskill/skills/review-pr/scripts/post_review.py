# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Post one GitHub review on the pull request, with its findings as inline comments where GitHub allows them.

Usage: uv run post_review.py, with {"pr", "commit", "body", "findings", "has_required"} on stdin: the findings and
has_required come from final_findings.py.
Prints {"result", "review_url", "inline", "in_body", "fallback"}.

The event is REQUEST_CHANGES when has_required is true, and APPROVE otherwise. GitHub refuses both on the user's own
pull request, so there the event is COMMENT. Each finding is found again at the commit by its quote, because an
earlier round can report a line of an older head. A finding goes inline when the diff shows its line, and into the
body otherwise. GitHub refuses the whole review when one inline comment is on a line that the diff does not show
(HTTP 422). When GitHub still refuses it, every finding goes into the body, and `fallback` is true. The body carries a
marker with a hash of the review and its commit, so a resumed run finds the review that it posted and never posts it
twice, while a later run on a new commit posts its own. read_earlier_reviews.py finds the earlier reviews by the same
marker prefix. The block has no retries.
"""

import hashlib
import json
import re
import subprocess
import sys
from typing import Any

from github_rest import gh_api, gh_api_pages

HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
REVIEW_MARKER_PREFIX = "<!-- pr-review: "
RESULT_OF_EVENT = {"REQUEST_CHANGES": "changes_requested", "APPROVE": "approved", "COMMENT": "commented"}
TAG_OF_SEVERITY = {"required": "`[Required]`", "suggestion": "`[Suggestion]`"}


def run(command: list[str], stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    # errors="replace": a diff of a file that is not valid UTF-8 must not crash the last step of the review.
    return subprocess.run(
        command, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )


def run_checked(command: list[str]) -> str:
    result = run(command)
    if result.returncode != 0:
        sys.exit(f"`{' '.join(command)}` failed: {result.stderr.strip()}")
    return result.stdout.strip()


def lines_shown_by_diff(diff: str) -> set[tuple[str, int]]:
    """Every (file, line) that the diff shows on its right side: the added and the context lines."""
    lines: set[tuple[str, int]] = set()
    path = ""
    for diff_line in diff.splitlines():
        if diff_line.startswith("+++ "):
            path = diff_line.removeprefix("+++ ").removeprefix("b/")
        elif match := HUNK_HEADER.match(diff_line):
            start, count = int(match.group(1)), int(match.group(2) or "1")
            lines.update((path, line) for line in range(start, start + count))
    return lines


def anchored_line(finding: dict[str, Any], file_lines: list[str]) -> int | None:
    """The line of the finding at the commit: its own line when the quote is still there, else the one line that
    holds the quote. None when the quote is on no line, or on several."""
    quote = str(finding["quote"]).strip()
    line = int(finding["line"])
    if not quote or (0 < line <= len(file_lines) and quote in file_lines[line - 1]):
        return line
    matches = [number for number, text in enumerate(file_lines, start=1) if quote in text]
    return matches[0] if len(matches) == 1 else None


def code_span(text: str) -> str:
    """Inline code that survives backticks inside the text: the fence is longer than its longest backtick run."""
    longest_run = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest_run + 1)
    padding = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{padding}{text}{padding}{fence}"


def comment_body(finding: dict[str, Any]) -> str:
    return (
        f"**{TAG_OF_SEVERITY[finding['severity']]} {finding['title']}**\n\n"
        f"{finding['summary']}\n\nQuote: {code_span(finding['quote'])}"
    )


def review_body(body: str, in_body: list[dict[str, Any]], marker: str, fallback: bool) -> str:
    if not in_body:
        return f"{body}\n\n{marker}"
    heading = "Findings:" if fallback else "Findings on lines that the diff does not show:"
    lines = [
        f"- **{TAG_OF_SEVERITY[finding['severity']]} {finding['title']}** at `{finding['file']}:{finding['line']}`: "
        f"{finding['summary']}"
        for finding in in_body
    ]
    return f"{body}\n\n{heading}\n\n" + "\n".join(lines) + f"\n\n{marker}"


def review_event(has_required: bool, own_pull_request: bool) -> str:
    if own_pull_request:
        return "COMMENT"
    return "REQUEST_CHANGES" if has_required else "APPROVE"


def split_findings(
    findings: list[dict[str, Any]], shown_lines: set[tuple[str, int]], file_lines: dict[str, list[str]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(inline, in_body): each finding at its line at the commit, inline when the diff shows that line."""
    inline: list[dict[str, Any]] = []
    in_body: list[dict[str, Any]] = []
    for finding in findings:
        line = anchored_line(finding, file_lines.get(finding["file"], []))
        if line is None:
            in_body.append(finding)
        elif (finding["file"], line) in shown_lines:
            inline.append({**finding, "line": line})
        else:
            in_body.append({**finding, "line": line})
    return inline, in_body


def lines_at_commit(commit: str, paths: set[str]) -> dict[str, list[str]]:
    """The lines of each file at the commit. A file that the commit does not have gets no lines."""
    return {path: run(["git", "show", f"{commit}:{path}"]).stdout.splitlines() for path in paths}


def posted_review_url(pr_number: str, marker: str) -> str:
    """The URL of the review that carries this marker, or an empty text when there is none."""
    reviews = gh_api_pages(f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/reviews")
    return next((str(review["html_url"]) for review in reviews if marker in (review["body"] or "")), "")


def post(pr_number: str, review: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    endpoint = f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/reviews"
    return run(["gh", "api", endpoint, "--method", "POST", "--input", "-", "--jq", ".html_url"], json.dumps(review))


def main() -> None:
    script_input: dict[str, Any] = json.load(sys.stdin)
    pr_number, commit, body = str(script_input["pr"]), str(script_input["commit"]), str(script_input["body"])
    findings: list[dict[str, Any]] = script_input["findings"]
    pull_request = gh_api(f"repos/{{owner}}/{{repo}}/pulls/{pr_number}")
    viewer = gh_api("user")["login"]
    event = review_event(bool(script_input["has_required"]), own_pull_request=pull_request["user"]["login"] == viewer)

    review_key = json.dumps([commit, body, findings, event], sort_keys=True)
    marker = f"{REVIEW_MARKER_PREFIX}{hashlib.sha256(review_key.encode()).hexdigest()[:12]} -->"
    diff = run_checked(["git", "diff", "--unified=3", f"origin/{pull_request['base']['ref']}...{commit}"])
    file_lines = lines_at_commit(commit, {finding["file"] for finding in findings})
    inline, in_body = split_findings(findings, lines_shown_by_diff(diff), file_lines)
    fallback = False

    review_url = posted_review_url(pr_number, marker)
    if not review_url:
        comments = [
            {"path": finding["file"], "line": finding["line"], "side": "RIGHT", "body": comment_body(finding)}
            for finding in inline
        ]
        review = {"commit_id": commit, "event": event, "body": review_body(body, in_body, marker, fallback)}
        result = post(pr_number, {**review, "comments": comments})
        if result.returncode != 0 and "HTTP 422" in result.stderr and comments:
            inline, in_body, fallback = [], [*inline, *in_body], True
            result = post(pr_number, {**review, "body": review_body(body, in_body, marker, fallback)})
        if result.returncode != 0:
            sys.exit(f"The review of pull request #{pr_number} could not be posted: {result.stderr.strip()}")
        review_url = result.stdout.strip()

    print(
        json.dumps(
            {
                "result": RESULT_OF_EVENT[event],
                "review_url": review_url,
                "inline": len(inline),
                "in_body": len(in_body),
                "fallback": fallback,
            }
        )
    )


if __name__ == "__main__":
    main()
