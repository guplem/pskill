# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Post the findings of a review round on the pull request, so that a person or resolve-pr-feedback sees them.

Usage: uv run post_findings.py, with {"pr", "head_sha", "findings"} on stdin: the findings of collect_findings.py.
Prints {"inline", "in_conversation"}: how many findings went to each place.

Each finding becomes an inline comment on its line at the head commit. GitHub refuses an inline comment on a line
that the diff does not show, so those findings go together into one conversation comment. The block has no
retries: a second try would post the comments twice.
"""

import json
import subprocess
import sys
from typing import Any


def run(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


def succeeds(command: list[str]) -> bool:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False).returncode == 0


def inline_body(finding: dict[str, Any]) -> str:
    return (
        f"**{finding['severity']}: {finding['title']}** ({finding['reviewer']} reviewer)\n\n"
        f"{finding['summary']}\n\nQuote: `{finding['quote']}`"
    )


def post_inline(pr_number: str, head_sha: str, finding: dict[str, Any]) -> bool:
    """Post a finding on its line. False when GitHub refuses it: the diff does not show the line."""
    fields = {"body": inline_body(finding), "commit_id": head_sha, "path": finding["file"], "side": "RIGHT"}
    text_fields = [part for name, value in fields.items() for part in ("-f", f"{name}={value}")]
    endpoint = f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/comments"
    return succeeds(["gh", "api", endpoint, *text_fields, "-F", f"line={finding['line']}"])


def conversation_body(findings: list[dict[str, Any]]) -> str:
    lines = [
        f"- **{finding['severity']}: {finding['title']}** at `{finding['file']}:{finding['line']}` "
        f"({finding['reviewer']} reviewer): {finding['summary']}"
        for finding in findings
    ]
    return "Review findings on lines outside the diff:\n\n" + "\n".join(lines)


def main() -> None:
    script_input: dict[str, Any] = json.load(sys.stdin)
    pr_number, head_sha = str(script_input["pr"]), str(script_input["head_sha"])
    findings: list[dict[str, Any]] = script_input["findings"]
    outside_diff = [finding for finding in findings if not post_inline(pr_number, head_sha, finding)]
    if outside_diff:
        endpoint = f"repos/{{owner}}/{{repo}}/issues/{pr_number}/comments"
        if not succeeds(["gh", "api", endpoint, "-f", f"body={conversation_body(outside_diff)}"]):
            sys.exit(f"The conversation comment with {len(outside_diff)} findings could not be posted.")
    print(json.dumps({"inline": len(findings) - len(outside_diff), "in_conversation": len(outside_diff)}))


if __name__ == "__main__":
    main()
