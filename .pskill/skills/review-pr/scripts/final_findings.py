# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Build the final list of findings that the review posts: the triage findings, plus each doubt that is kept.

Usage: uv run final_findings.py, with {"findings", "still_open", "doubts", "verdicts"} on stdin: the triage output and
the verdict of each settled doubt, in the order of the doubts.
Prints {"findings", "has_required"}.

A doubt takes its verdict as its severity, and the verdict "drop" leaves it out. A doubt with no verdict (an
autonomous run asks no doubt, and the safety cap can stop the questions) takes the recommendation of the triage.
has_required also counts a still-open required finding of an earlier review: the review does not post it again,
but it still requests changes.
"""

import json
import sys
from typing import Any


def final_findings(
    findings: list[dict[str, Any]], doubts: list[dict[str, Any]], verdicts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    kept_doubts: list[dict[str, Any]] = []
    for index, doubt in enumerate(doubts):
        verdict = verdicts[index]["verdict"] if index < len(verdicts) else doubt["recommendation"]
        if verdict != "drop":
            kept_doubts.append({**doubt["finding"], "severity": verdict})
    return [*findings, *kept_doubts]


def main() -> None:
    script_input: dict[str, Any] = json.load(sys.stdin)
    findings = final_findings(script_input["findings"], script_input["doubts"], script_input["verdicts"])
    has_required = any(finding["severity"] == "required" for finding in [*findings, *script_input["still_open"]])
    print(json.dumps({"findings": findings, "has_required": has_required}))


if __name__ == "__main__":
    main()
