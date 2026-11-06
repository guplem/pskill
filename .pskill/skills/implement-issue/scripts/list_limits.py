# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Name each limit that cut the work of the run short, once, for the finish edge, its instruction, and the report.

Usage: uv run list_limits.py, with {"build_done", "ready_runs", "ci_runs", "critical_rounds", "last_critical_findings",
"last_critical_fixed", "items_left"} on stdin.
Prints {"limits": [...]}, in this order, with each limit that applies:
- implement_step: the build stopped before the plan was done.
- get_ci_green: CI stopped at its visit cap, so CI did not run on the head commit.
- critical: the critical rounds used their rounds, and the fix of the last round's findings got no review.
- resolve_items: a feedback round stopped at its item cap.
"""

import json
import sys
from typing import Any

CRITICAL_ROUNDS = 6  # keep equal to the edge from critical_resolve in skill.yaml


def list_limits(state: dict[str, Any]) -> list[str]:
    limits: list[str] = []
    if not state["build_done"]:
        limits.append("implement_step")
    if state["ready_runs"] > state["ci_runs"]:
        limits.append("get_ci_green")
    # The last round always has a review after it, unless the cap sent its fix straight to CI.
    last_fix_unreviewed = state["last_critical_findings"] > 0 and state["last_critical_fixed"] > 0
    if state["critical_rounds"] >= CRITICAL_ROUNDS and last_fix_unreviewed:
        limits.append("critical")
    if state["items_left"] > 0:
        limits.append("resolve_items")
    return limits


def main() -> None:
    print(json.dumps({"limits": list_limits(json.load(sys.stdin))}))


if __name__ == "__main__":
    main()
