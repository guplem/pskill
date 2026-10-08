# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Reply to a comment with its verdict, and record the decision of one item.

Usage: uv run finish_item.py, with {"pr", "item", "decision"} on stdin: one item of collect_items.py, and
{verdict, reason}.
Prints {"replied": true|false, "decision": {kind, reviewer, title, verdict, reason}}.

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


def reply_body(item: dict[str, Any], decision: dict[str, Any], head_sha: str) -> str:
    verdict = f"**Fixed** in {head_sha}." if decision["verdict"] == "fixed" else "**Dismissed**."
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
    head_sha = run(["git", "rev-parse", "--short", "HEAD"]) if decision["verdict"] == "fixed" else ""
    run(["gh", "api", endpoint, "-f", f"body={reply_body(item, decision, head_sha)}"])


def title_of(item: dict[str, Any]) -> str:
    if item["kind"] == "finding":
        return str(item["title"])
    first_line = next((line for line in str(item["body"]).splitlines() if line.strip()), "")
    return first_line[:TITLE_LENGTH]


def main() -> None:
    script_input = json.load(sys.stdin)
    item: dict[str, Any] = script_input["item"]
    decision: dict[str, Any] = script_input["decision"]
    is_comment = item["kind"] == "comment"
    if is_comment:
        post_reply(str(script_input["pr"]), item, decision)
    record = {
        "kind": item["kind"],
        "reviewer": item.get("reviewer") or "",  # empty for a comment
        "title": title_of(item),
        "verdict": decision["verdict"],
        "reason": decision["reason"],
    }
    print(json.dumps({"replied": is_comment, "decision": record}))


if __name__ == "__main__":
    main()
