# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Keep only the findings whose quote really appears in the pull request diff: no quote, no finding.

Usage: uv run verify_quotes.py <pr-number>
Reads the triaged findings from the run state (PSKILL_STATE_FILE) and prints {"findings": [...]}.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def diff_lines(diff_text: str) -> set[str]:
    """Every code line of a unified diff, without its +, -, or space marker, stripped."""
    lines = set()
    for line in diff_text.splitlines():
        if line.startswith(("+++", "---", "@@", "diff ")):
            continue
        if line[:1] in ("+", "-", " "):
            lines.add(line[1:].strip())
    return lines


def findings_with_real_quotes(findings: list[dict[str, Any]], diff_text: str) -> list[dict[str, Any]]:
    """Keep a finding only when every non-empty line of its quote appears in the diff."""
    known_lines = diff_lines(diff_text)
    kept = []
    for finding in findings:
        quote_lines = [line.strip() for line in str(finding.get("quote", "")).splitlines() if line.strip()]
        if quote_lines and all(line in known_lines for line in quote_lines):
            kept.append(finding)
    return kept


def main() -> None:
    pr_number = sys.argv[1]
    state = json.loads(Path(os.environ["PSKILL_STATE_FILE"]).read_text(encoding="utf-8"))
    findings = state["steps"]["triage"]["findings"]
    diff_text = subprocess.run(
        ["gh", "pr", "diff", pr_number], capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout
    print(json.dumps({"findings": findings_with_real_quotes(findings, diff_text)}))


if __name__ == "__main__":
    main()
