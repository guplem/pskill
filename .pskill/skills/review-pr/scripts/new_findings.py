# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Keep the findings of the last round that repeat no finding of an earlier round of the run.

Usage: uv run new_findings.py, with {"findings", "reported"} on stdin: the findings of the last round, and the
findings of every earlier round of the run.
Prints {"new", "required"}: the new findings, and how many of them are required.

A finding repeats an earlier one only when it is at the same file and line and has the same title or the same
reviewer: another reviewer's finding with another title at that line is a different problem, such as a bug at the line
of a docs finding. A round whose findings all repeat earlier ones counts as clean, so the review moves on.
"""

import json
import sys
from typing import Any


def repeats(finding: dict[str, Any], earlier: dict[str, Any]) -> bool:
    same_place: bool = earlier["file"] == finding["file"] and earlier["line"] == finding["line"]
    same_problem: bool = earlier["title"] == finding["title"] or earlier["reviewer"] == finding["reviewer"]
    return same_place and same_problem


def is_repeat(finding: dict[str, Any], reported: list[dict[str, Any]]) -> bool:
    return any(repeats(finding, earlier) for earlier in reported)


def new_findings(findings: list[dict[str, Any]], reported: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [finding for finding in findings if not is_repeat(finding, reported)]


def main() -> None:
    script_input: dict[str, Any] = json.load(sys.stdin)
    new = new_findings(script_input["findings"], script_input["reported"])
    required = sum(1 for finding in new if finding["severity"] == "required")
    print(json.dumps({"new": new, "required": required}))


if __name__ == "__main__":
    main()
