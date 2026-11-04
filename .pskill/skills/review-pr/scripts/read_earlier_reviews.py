# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""List the findings that earlier runs of review-pr already posted on the pull request, with their replies.

Usage: uv run read_earlier_reviews.py, with {"pr"} on stdin.
Prints {"dismissed": [{reviewer, title, severity, reason}], "count", "since_sha", "full_review_reason"}. `dismissed`
has the shape of the `dismissed` input of review-round, so that no round reports a posted finding again. The triage
reads the severity, because a required finding that the head does not fix still requests changes.

`since_sha` is the commit that the last earlier review covered, so that a follow-up review reviews only the code
changed since then. It is empty for a first review, and when that commit is no longer in the branch history (a
force-push): then `full_review_reason` says why the review covers the whole pull request.

An earlier review is one whose body carries the marker of post_review.py, whoever posted it. Its findings are its
inline comments and the findings listed in its body. The reason of each finding names where it was posted, and
quotes the replies under its comment, so that the triage can see what a human already answered.
"""

import json
import re
import sys
from collections.abc import Callable
from typing import Any

from github_rest import gh_api, gh_api_call, gh_api_pages

REVIEW_MARKER_PREFIX = "<!-- pr-review: "
# The tag of the current format (**`[Required]` title**) or of the first one (**required: title** (x reviewer)).
FINDING_TITLE = re.compile(
    r"^\*\*(?:`\[(?P<tag>Required|Suggestion)\]` |(?P<old_tag>required|suggestion): )(?P<title>.+?)\*\*"
)
BODY_FINDING = re.compile(r"^- (?P<head>\*\*.+?\*\*) at `(?P<location>[^`]+)`")
REPLY_LIMIT = 300


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


def in_branch_history(commit: str, head_sha: str) -> bool:
    """True when the head contains the commit: the head is ahead of it, or it is the same commit."""
    result = gh_api_call(f"repos/{{owner}}/{{repo}}/compare/{commit}...{head_sha}")
    return result.returncode == 0 and json.loads(result.stdout)["status"] in ("ahead", "identical")


def delta_start(
    reviews: list[dict[str, Any]], head_sha: str, in_history: Callable[[str, str], bool]
) -> tuple[str, str]:
    """(since_sha, full_review_reason): where a follow-up review starts, or why it reviews the whole pull request."""
    marked_reviews = [review for review in reviews if REVIEW_MARKER_PREFIX in (review.get("body") or "")]
    if not marked_reviews:
        return "", ""
    last_commit = str(marked_reviews[-1]["commit_id"])
    if in_history(last_commit, head_sha):
        return last_commit, ""
    return "", (
        f"The commit `{last_commit[:7]}` of the last review is no longer in the branch history (a force-push), "
        "so this review covers the whole pull request."
    )


def main() -> None:
    pr_number = str(json.load(sys.stdin)["pr"])
    reviews = gh_api_pages(f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/reviews")
    comments = gh_api_pages(f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/comments")
    head_sha = str(gh_api(f"repos/{{owner}}/{{repo}}/pulls/{pr_number}")["head"]["sha"])
    dismissed = earlier_findings(reviews, comments)
    since_sha, full_review_reason = delta_start(reviews, head_sha, in_branch_history)
    result = {"dismissed": dismissed, "count": len(dismissed), "since_sha": since_sha}
    print(json.dumps({**result, "full_review_reason": full_review_reason}))


if __name__ == "__main__":
    main()
