# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""List the findings that earlier runs of review-pr already posted on the pull request, with their replies.

Usage: uv run read_earlier_reviews.py, with {"pr"} on stdin.
Prints {"dismissed": [{reviewer, title, severity, reason}], "count"}, in the shape of the `dismissed` input of
review-round, so that no round reports a posted finding again. The triage reads the severity, because a
required finding that the head does not fix still requests changes.

An earlier review is one whose body carries the marker of post_review.py, whoever posted it. Its findings are its
inline comments and the findings listed in its body. The reason of each finding names where it was posted, and
quotes the replies under its comment, so that the triage can see what a human already answered.
"""

import json
import re
import subprocess
import sys
from typing import Any

REVIEW_MARKER_PREFIX = "<!-- pr-review: "
# The tag of the current format (**`[Required]` title**) or of the first one (**required: title** (x reviewer)).
FINDING_TITLE = re.compile(
    r"^\*\*(?:`\[(?P<tag>Required|Suggestion)\]` |(?P<old_tag>required|suggestion): )(?P<title>.+?)\*\*"
)
BODY_FINDING = re.compile(r"^- (?P<head>\*\*.+?\*\*) at `(?P<location>[^`]+)`")
REPLY_LIMIT = 300


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)


def gh_list(endpoint: str) -> list[dict[str, Any]]:
    result = run(["gh", "api", endpoint, "--paginate", "--jq", ".[]"])
    if result.returncode != 0:
        sys.exit(f"`gh api {endpoint}` failed: {result.stderr.strip()}")
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def finding_head(text: str) -> tuple[str, str] | None:
    """(severity, title) of a finding comment or body line, or None when the text is not a finding."""
    match = FINDING_TITLE.match(text.strip())
    if not match:
        return None
    return (match.group("tag") or match.group("old_tag")).lower(), match.group("title")


def earlier_findings(reviews: list[dict[str, Any]], comments: list[dict[str, Any]]) -> list[dict[str, str]]:
    marked_reviews = [review for review in reviews if REVIEW_MARKER_PREFIX in (review.get("body") or "")]
    review_ids = {review["id"] for review in marked_reviews}
    replies: dict[int, list[str]] = {}
    for comment in comments:
        if comment.get("in_reply_to_id"):
            reply = " ".join(comment["body"].split())[:REPLY_LIMIT]
            replies.setdefault(comment["in_reply_to_id"], []).append(f"{comment['user']['login']}: {reply}")

    dismissed: list[dict[str, str]] = []
    for comment in comments:
        head = finding_head(comment["body"])
        if comment.get("pull_request_review_id") not in review_ids or comment.get("in_reply_to_id") or not head:
            continue
        location = f"{comment['path']}:{comment.get('line') or comment.get('original_line')}"
        thread = replies.get(comment["id"], [])
        answered = f" Replies: {' | '.join(thread)}" if thread else " It has no reply."
        dismissed.append(posted(*head, location, answered))
    for review in marked_reviews:
        for line in review["body"].splitlines():
            match = BODY_FINDING.match(line)
            head = finding_head(match.group("head")) if match else None
            if match and head:
                dismissed.append(posted(*head, match.group("location"), " It is in the review body."))
    return dismissed


def posted(severity: str, title: str, location: str, answered: str) -> dict[str, str]:
    return {
        "reviewer": "earlier review",
        "title": title,
        "severity": severity,
        "reason": f"An earlier review of this pull request already posted it at `{location}`.{answered}",
    }


def main() -> None:
    pr_number = str(json.load(sys.stdin)["pr"])
    reviews = gh_list(f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/reviews")
    comments = gh_list(f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/comments")
    dismissed = earlier_findings(reviews, comments)
    print(json.dumps({"dismissed": dismissed, "count": len(dismissed)}))


if __name__ == "__main__":
    main()
