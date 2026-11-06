# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Keep the findings of the last round that repeat no finding of an earlier round of the run.

Usage: uv run new_findings.py, with {"findings", "reported"} on stdin: the findings of the last round, and the
findings of every earlier round of the run.
Prints {"new", "required"}: the new findings, and how many of them are required.

A finding repeats an earlier one when it has its title, or its file and line. A round whose findings all repeat
earlier ones counts as clean, so the review moves on.
"""

import json
import sys
from typing import Any


def is_repeat(finding: dict[str, Any], reported: list[dict[str, Any]]) -> bool:
    return any(
        earlier["title"] == finding["title"]
        or (earlier["file"] == finding["file"] and earlier["line"] == finding["line"])
        for earlier in reported
    )


def new_findings(findings: list[dict[str, Any]], reported: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [finding for finding in findings if not is_repeat(finding, reported)]


def main() -> None:
    script_input: dict[str, Any] = json.load(sys.stdin)
    new = new_findings(script_input["findings"], script_input["reported"])
    required = sum(1 for finding in new if finding["severity"] == "required")
    print(json.dumps({"new": new, "required": required}))


if __name__ == "__main__":
    main()
