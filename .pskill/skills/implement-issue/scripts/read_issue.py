# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Read an issue with everything the plan needs, and say whether the work may start.

Usage: uv run read_issue.py, with {"request"} on stdin: an issue number, "#123", or an issue link.
Prints number, title, body, labels, comments, cross_references, hold_reason, existing_branches.
`hold_reason` says why the work must not start, or is null: the issue is closed, is a parent issue, is assigned to
someone else, or has a `waiting-for-*` label (it waits for something, such as a decision or a check).
"""

import json
import re
import subprocess
import sys
from typing import Any

BLOCKING_LABEL_PREFIX = "waiting-for-"


def run(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


def cross_references(number: str) -> list[dict[str, Any]]:
    """The issues and pull requests that mention this issue, each one once."""
    pages = json.loads(
        run(["gh", "api", f"repos/{{owner}}/{{repo}}/issues/{number}/timeline", "--paginate", "--slurp"])
    )
    references: dict[int, dict[str, Any]] = {}
    for event in (event for page in pages for event in page):
        source = (event.get("source") or {}).get("issue")
        if event.get("event") == "cross-referenced" and source:
            references[source["number"]] = {"number": source["number"], "title": source["title"]}
    return list(references.values())


def existing_branches(number: str) -> list[str]:
    output = run(["git", "ls-remote", "--heads", "origin", f"{number}-*"])
    return [line.split("refs/heads/", 1)[1] for line in output.splitlines() if "refs/heads/" in line]


def hold_reason(issue: dict[str, Any], sub_issues: int, me: str) -> str | None:
    owners = [assignee["login"] for assignee in issue["assignees"] if assignee["login"] != me]
    blocking_labels = [label["name"] for label in issue["labels"] if label["name"].startswith(BLOCKING_LABEL_PREFIX)]
    if issue["state"] != "OPEN":
        return "is closed"
    if sub_issues:
        return f"is a parent issue with {sub_issues} sub-issues: implement each sub-issue instead"
    if owners:
        return f"is assigned to {', '.join(owners)}, who owns the work"
    if blocking_labels:
        return f"has the blocking labels {', '.join(blocking_labels)}"
    return None


def main() -> None:
    number = re.findall(r"[0-9]+", str(json.load(sys.stdin)["request"]))[-1]
    fields = "number,title,body,labels,comments,state,assignees"
    issue: dict[str, Any] = json.loads(run(["gh", "issue", "view", number, "--json", fields]))
    sub_issues = int(
        run(["gh", "api", f"repos/{{owner}}/{{repo}}/issues/{number}", "--jq", ".sub_issues_summary.total // 0"]) or 0
    )
    me = run(["gh", "api", "user", "--jq", ".login"])
    print(
        json.dumps(
            {
                "number": issue["number"],
                "title": issue["title"],
                "body": issue["body"],
                "labels": [label["name"] for label in issue["labels"]],
                "comments": [
                    {"author": comment["author"]["login"], "body": comment["body"]} for comment in issue["comments"]
                ],
                "cross_references": cross_references(number),
                "hold_reason": hold_reason(issue, sub_issues, me),
                "existing_branches": existing_branches(number),
            }
        )
    )


if __name__ == "__main__":
    main()
