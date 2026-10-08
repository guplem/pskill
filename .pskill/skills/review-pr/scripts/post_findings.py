# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Post the findings of a review round on the pull request, so that a person or resolve-pr-feedback sees them.

Usage: uv run post_findings.py, with {"pr", "head_sha", "findings"} on stdin: the findings of collect_findings.py.
Prints {"inline", "in_conversation", "already_posted"}: how many findings went to each place, and how many an
earlier try of a resumed run already posted.

Each finding becomes an inline comment on its line at the head commit. GitHub refuses an inline comment on a line
that the diff does not show (HTTP 422), so those findings go together into one conversation comment. Any other
failure stops the script. Each posted finding carries a marker with its key, so a resumed run, which runs the
block again, skips the findings that the pull request already shows. The block has no retries.
"""

import hashlib
import json
import re
import subprocess
import sys
from typing import Any

FINDING_MARKER = re.compile(r"<!-- review-pr-finding: ([0-9a-f]+) -->")


def run(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


def succeeds(command: list[str]) -> bool:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False).returncode == 0


def marker(finding: dict[str, Any]) -> str:
    key = hashlib.sha256(f"{finding['file']}:{finding['line']}:{finding['title']}".encode()).hexdigest()[:12]
    return f"<!-- review-pr-finding: {key} -->"


def posted_markers(pr_number: str) -> set[str]:
    """The markers of the findings that the pull request already shows, inline or in the conversation."""
    bodies = [
        run(["gh", "api", f"repos/{{owner}}/{{repo}}/{endpoint}", "--paginate", "--jq", ".[].body"])
        for endpoint in (f"pulls/{pr_number}/comments", f"issues/{pr_number}/comments")
    ]
    return {f"<!-- review-pr-finding: {key} -->" for body in bodies for key in FINDING_MARKER.findall(body)}


def inline_body(finding: dict[str, Any]) -> str:
    return (
        f"**{finding['severity']}: {finding['title']}** ({finding['reviewer']} reviewer)\n\n"
        f"{finding['summary']}\n\nQuote: `{finding['quote']}`\n\n{marker(finding)}"
    )


def post_inline(pr_number: str, head_sha: str, finding: dict[str, Any]) -> bool:
    """Post a finding on its line. False when GitHub refuses it with HTTP 422: the diff does not show the line."""
    fields = {"body": inline_body(finding), "commit_id": head_sha, "path": finding["file"], "side": "RIGHT"}
    text_fields = [part for name, value in fields.items() for part in ("-f", f"{name}={value}")]
    endpoint = f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/comments"
    try:
        run(["gh", "api", endpoint, *text_fields, "-F", f"line={finding['line']}"])
    except subprocess.CalledProcessError as error:
        if "HTTP 422" in str(error.stderr):
            return False
        raise
    return True


def conversation_body(findings: list[dict[str, Any]]) -> str:
    lines = [
        f"- **{finding['severity']}: {finding['title']}** at `{finding['file']}:{finding['line']}` "
        f"({finding['reviewer']} reviewer): {finding['summary']}"
        for finding in findings
    ]
    markers = "".join(marker(finding) for finding in findings)
    return "Review findings on lines outside the diff:\n\n" + "\n".join(lines) + "\n\n" + markers


def main() -> None:
    script_input: dict[str, Any] = json.load(sys.stdin)
    pr_number, head_sha = str(script_input["pr"]), str(script_input["head_sha"])
    already_posted = posted_markers(pr_number)
    findings = [finding for finding in script_input["findings"] if marker(finding) not in already_posted]
    skipped = len(script_input["findings"]) - len(findings)
    outside_diff = [finding for finding in findings if not post_inline(pr_number, head_sha, finding)]
    if outside_diff:
        endpoint = f"repos/{{owner}}/{{repo}}/issues/{pr_number}/comments"
        if not succeeds(["gh", "api", endpoint, "-f", f"body={conversation_body(outside_diff)}"]):
            sys.exit(f"The conversation comment with {len(outside_diff)} findings could not be posted.")
    counts = {"inline": len(findings) - len(outside_diff), "in_conversation": len(outside_diff)}
    print(json.dumps({**counts, "already_posted": skipped}))


if __name__ == "__main__":
    main()
