# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Read an issue with everything the plan needs, and say whether the work may start.

Usage: uv run read_issue.py, with {"request"} on stdin: an issue number, "#123", or an issue link.
Prints number, title, body, labels, comments, cross_references, hold_reason, existing_branches.
`hold_reason` says why the work must not start, or is null: the issue is closed, is a pull request (the REST issue
path answers for one too), is a parent issue, is assigned to someone else, or has a `waiting-for-*` label (it waits
for something, such as a decision or a check). A link to an
issue of another repository is held before any read: the same number in this repository is another issue.
"""

import json
import re
import subprocess
import sys
from typing import Any

from github_rest import gh_api, gh_api_pages

BLOCKING_LABEL_PREFIX = "waiting-for-"
ISSUE_LINK = re.compile(r"github[.]com/([^/ ]+/[^/ ]+)/issues/[0-9]+")


def run(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


def cross_references(number: str) -> list[dict[str, Any]]:
    """The issues and pull requests that mention this issue, each one once."""
    references: dict[int, dict[str, Any]] = {}
    for event in gh_api_pages(f"repos/{{owner}}/{{repo}}/issues/{number}/timeline"):
        source = (event.get("source") or {}).get("issue")
        if event.get("event") == "cross-referenced" and source:
            references[source["number"]] = {"number": source["number"], "title": source["title"]}
    return list(references.values())


def existing_branches(number: str) -> list[str]:
    output = run(["git", "ls-remote", "--heads", "origin", f"{number}-*"])
    return [line.split("refs/heads/", 1)[1] for line in output.splitlines() if "refs/heads/" in line]


def hold_reason(issue: dict[str, Any], me: str) -> str | None:
    sub_issues = (issue.get("sub_issues_summary") or {}).get("total", 0)
    owners = [assignee["login"] for assignee in issue["assignees"] if assignee["login"] != me]
    blocking_labels = [label["name"] for label in issue["labels"] if label["name"].startswith(BLOCKING_LABEL_PREFIX)]
    if issue["state"] != "open":
        return "is closed"
    if "pull_request" in issue:
        return "is a pull request, not an issue"
    if sub_issues:
        return f"is a parent issue with {sub_issues} sub-issues: implement each sub-issue instead"
    if owners:
        return f"is assigned to {', '.join(owners)}, who owns the work"
    if blocking_labels:
        return f"has the blocking labels {', '.join(blocking_labels)}"
    return None


def linked_repository(request: str) -> str | None:
    """The owner/name of an issue link, or None for a plain issue number."""
    link = ISSUE_LINK.search(request)
    return link.group(1) if link else None


def held_elsewhere(number: str, linked: str, current: str) -> dict[str, Any]:
    reason = f"is in the repository {linked}, not in {current}: start the skill from a checkout of {linked}"
    empty: dict[str, Any] = {"title": "", "body": "", "labels": [], "comments": [], "cross_references": []}
    return {"number": int(number), **empty, "hold_reason": reason, "existing_branches": []}


def main() -> None:
    request = str(json.load(sys.stdin)["request"])
    number = re.findall(r"[0-9]+", request)[-1]
    linked = linked_repository(request)
    if linked is not None:
        current = str(gh_api("repos/{owner}/{repo}")["full_name"])
        if linked.lower() != current.lower():
            print(json.dumps(held_elsewhere(number, linked, current)))
            return
    issue: dict[str, Any] = gh_api(f"repos/{{owner}}/{{repo}}/issues/{number}")
    comments = gh_api_pages(f"repos/{{owner}}/{{repo}}/issues/{number}/comments")
    me = str(gh_api("user")["login"])
    print(
        json.dumps(
            {
                "number": issue["number"],
                "title": issue["title"],
                "body": issue["body"] or "",
                "labels": [label["name"] for label in issue["labels"]],
                "comments": [{"author": comment["user"]["login"], "body": comment["body"]} for comment in comments],
                "cross_references": cross_references(number),
                "hold_reason": hold_reason(issue, me),
                "existing_branches": existing_branches(number),
            }
        )
    )


if __name__ == "__main__":
    main()
