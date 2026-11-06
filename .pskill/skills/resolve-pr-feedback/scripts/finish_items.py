# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Reply to each comment with its verdict, and record the decision of each item.

Usage: uv run finish_items.py, with {"pr", "branch", "items", "decisions"} on stdin: the branch of the pull request,
the queue of collect_items.py, and one {verdict, reason, commit} per item, in the same order. `commit` names the
commit of a fix.
Prints {"decisions": [{kind, reviewer, title, verdict, reason}], "left", "head_sha"}: `left` counts the items at the
end of the queue that got no decision, and `head_sha` is the head of the branch on GitHub after every push of the
task, so a caller compares heads to know whether the task pushed. It is read first: a failed read posts no reply.

A reply ends with the marker `<!-- resolve-pr-feedback-reply: <id> -->`, so collect_items.py never lists the comment
or the reply again. An inline comment gets its reply in its thread, through the thread's first comment: GitHub
accepts a reply only to that comment. A review or conversation comment gets a new conversation comment that quotes
its first line. The block has no retries: a second try would post the reply twice.
"""

import json
import subprocess
import sys
from typing import Any

TITLE_LENGTH = 80


def run(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


def reply_body(item: dict[str, Any], decision: dict[str, Any]) -> str:
    verdict = (
        f"**Fixed** in {decision.get('commit') or 'this pull request'}."
        if decision["verdict"] == "fixed"
        else "**Dismissed**."
    )
    # Quote only the first line, to name the comment: the reply stays short.
    first_line = next((line.strip() for line in str(item["body"]).splitlines() if line.strip()), "")
    quote = "" if item["comment_kind"] == "inline" else f"> {first_line[:200]}\n\n"
    return f"{quote}{verdict} {decision['reason']}\n\n<!-- resolve-pr-feedback-reply: {item['id']} -->"


def post_reply(pr_number: str, item: dict[str, Any], decision: dict[str, Any]) -> None:
    endpoint = (
        f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/comments/{item['thread_id']}/replies"
        if item["comment_kind"] == "inline"
        else f"repos/{{owner}}/{{repo}}/issues/{pr_number}/comments"
    )
    run(["gh", "api", endpoint, "-f", f"body={reply_body(item, decision)}"])


def title_of(item: dict[str, Any]) -> str:
    if item["kind"] == "finding":
        return str(item["title"])
    first_line = next((line for line in str(item["body"]).splitlines() if line.strip()), "")
    return first_line[:TITLE_LENGTH]


def finish(pr_number: str, item: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Reply to a comment, and return the record of the item's decision."""
    if item["kind"] == "comment":
        post_reply(pr_number, item, decision)
    return {
        "kind": item["kind"],
        "reviewer": item.get("reviewer") or "",  # empty for a comment
        "title": title_of(item),
        "verdict": decision["verdict"],
        "reason": decision["reason"],
    }


def remote_head(branch: str) -> str:
    """The head commit of the branch on origin."""
    return run(["git", "ls-remote", "origin", f"refs/heads/{branch}"]).split()[0]


def main() -> None:
    script_input = json.load(sys.stdin)
    head_sha = remote_head(str(script_input["branch"]))
    items: list[dict[str, Any]] = script_input["items"]
    decisions: list[dict[str, Any]] = script_input["decisions"][: len(items)]
    # The items past the last decision get no reply: they are left for a later run.
    answered = items[: len(decisions)]
    records = [
        finish(str(script_input["pr"]), item, decision) for item, decision in zip(answered, decisions, strict=True)
    ]
    print(json.dumps({"decisions": records, "left": len(items) - len(records), "head_sha": head_sha}))


if __name__ == "__main__":
    main()
