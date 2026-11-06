# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Join the findings of every reviewer of one review round, and keep only the findings with a real quote.

Usage: uv run collect_findings.py, with {"results", "head_sha", "base", "round", "critical"} on stdin: the results of
the review block, one {reviewer, findings} per reviewer, and the round number and whether it is a critical round.
Prints {"findings": [{reviewer, file, line, severity, title, summary, quote}], "count", "dropped": [{reviewer, title}]}.

No quote, no finding: a finding stays only when every line of its quote appears in its file at the head commit, or
in the base version of a file that the change deletes. The reviewer name lets the next round give each dismissed
finding back to the reviewer that reported it.

From round 2 on, and in a critical round, a round reports required findings only, so every suggestion is left out,
also when a reviewer gave one against its instruction.

The findings are sorted by file and line, so the findings of several reviewers on one line come one after another.
They are not merged: two findings on one line can be two different problems, and each one gets its own verdict.
"""

import json
import subprocess
import sys
from typing import Any


def run(command: list[str]) -> str:
    return subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True
    ).stdout.strip()


def file_lines(path: str, head_sha: str, base: str) -> set[str]:
    """The stripped lines of a file at the head commit, or at the base when the change deletes it."""
    for revision in (head_sha, f"origin/{base}"):
        try:
            return {line.strip() for line in run(["git", "show", f"{revision}:{path}"]).splitlines()}
        except subprocess.CalledProcessError:
            continue
    return set()


def has_real_quote(finding: dict[str, Any], head_sha: str, base: str) -> bool:
    quote_lines = [line.strip() for line in str(finding.get("quote", "")).splitlines() if line.strip()]
    if not quote_lines:
        return False
    known_lines = file_lines(str(finding["file"]), head_sha, base)
    return all(line in known_lines for line in quote_lines)


def reports_suggestions(script_input: dict[str, Any]) -> bool:
    """Only round 1 of the review phase reports suggestions; a critical round never does."""
    return not script_input["critical"] and int(script_input["round"]) == 1


def main() -> None:
    script_input = json.load(sys.stdin)
    head_sha, base = str(script_input["head_sha"]), str(script_input["base"])
    results: list[dict[str, Any]] = script_input["results"]
    joined = [{"reviewer": result["reviewer"], **finding} for result in results for finding in result["findings"]]
    if not reports_suggestions(script_input):
        joined = [finding for finding in joined if finding["severity"] == "required"]
    findings = [finding for finding in joined if has_real_quote(finding, head_sha, base)]
    findings.sort(key=lambda finding: (finding["file"], finding["line"]))
    dropped = [
        {"reviewer": finding["reviewer"], "title": finding["title"]} for finding in joined if finding not in findings
    ]
    print(json.dumps({"findings": findings, "count": len(findings), "dropped": dropped}))


if __name__ == "__main__":
    main()
