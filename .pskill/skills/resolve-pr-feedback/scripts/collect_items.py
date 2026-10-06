# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""List the items to resolve on a pull request: the given findings, then every comment that nobody addressed yet.

Usage: uv run collect_items.py, with {"pr", "findings"} on stdin. Prints {"queue": [item, ...], "count"}. Each item
has a `kind`:
- finding: reviewer, file, line, severity, title, summary, quote.
- comment: id, comment_kind (inline, review, or conversation), author, path, line, thread_id, body.

A comment is addressed, and so left out, when a reply names its id with the marker
`<!-- resolve-pr-feedback-reply: <id> -->`, when it carries the eyes reaction (someone is working on it), or when it
is such a reply itself. The comments of `github-actions[bot]` are CI output, and a Copilot review that says it was
unable to review is a quota notice: neither is review, so they never count.
"""

import json
import re
import subprocess
import sys
from typing import Any

REPLY_MARKER = re.compile(r"<!-- resolve-pr-feedback-reply: (\d+) -->")
CI_NOTICE_AUTHOR = "github-actions[bot]"
COPILOT_REVIEWER = "copilot-pull-request-reviewer[bot]"


def run(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


def all_pages(endpoint: str) -> list[dict[str, Any]]:
    """Every item of a paginated REST endpoint (`--slurp` gives one list per page)."""
    pages: list[list[dict[str, Any]]] = json.loads(run(["gh", "api", endpoint, "--paginate", "--slurp"]))
    return [item for page in pages for item in page]


def answered_ids(bodies: list[str]) -> set[int]:
    return {int(match) for body in bodies for match in REPLY_MARKER.findall(body)}


def is_copilot_notice(review: dict[str, Any]) -> bool:
    return review["user"]["login"] == COPILOT_REVIEWER and "unable to review" in str(review["body"] or "")


def comment_item(comment: dict[str, Any], comment_kind: str) -> dict[str, Any]:
    inline = comment_kind == "inline"
    return {
        "kind": "comment",
        "id": comment["id"],
        "comment_kind": comment_kind,
        "author": comment["user"]["login"],
        "path": comment.get("path") if inline else None,
        "line": (comment.get("line") or comment.get("original_line")) if inline else None,
        "thread_id": (comment.get("in_reply_to_id") or comment["id"]) if inline else None,
        "body": comment["body"],
    }


def is_unaddressed(comment: dict[str, Any], answered: set[int]) -> bool:
    body = str(comment["body"] or "")
    has_eyes = (comment.get("reactions") or {}).get("eyes", 0) > 0  # a review body has no reactions
    return bool(body.strip()) and comment["id"] not in answered and not REPLY_MARKER.search(body) and not has_eyes


def unaddressed_comments(pr_number: str) -> list[dict[str, Any]]:
    inline = all_pages(f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/comments")
    reviews = [
        review
        for review in all_pages(f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/reviews")
        if not is_copilot_notice(review)
    ]
    conversation = [
        comment
        for comment in all_pages(f"repos/{{owner}}/{{repo}}/issues/{pr_number}/comments")
        if comment["user"]["login"] != CI_NOTICE_AUTHOR
    ]
    answered = answered_ids([str(comment["body"] or "") for comment in [*inline, *conversation]])
    return [
        comment_item(comment, comment_kind)
        for comment_kind, comments in (("inline", inline), ("review", reviews), ("conversation", conversation))
        for comment in comments
        if is_unaddressed(comment, answered)
    ]


def main() -> None:
    script_input = json.load(sys.stdin)
    findings: list[dict[str, Any]] = script_input["findings"]
    queue = [{"kind": "finding", **finding} for finding in findings] + unaddressed_comments(str(script_input["pr"]))
    print(json.dumps({"queue": queue, "count": len(queue)}))


if __name__ == "__main__":
    main()
