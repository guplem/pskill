# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Name each limit that cut the work of the run short, once, for the finish edge, its instruction, and the report.

Usage: uv run list_limits.py, with {"build_done", "resolve_rounds", "last_fixed", "ready_runs", "ci_runs",
"unreviewed", "items_left"} on stdin.
Prints {"limits": [...]}, in this order, with each limit that applies:
- implement_step: the build stopped before the plan was done.
- review: the review loop used its rounds, and its last round still fixed code.
- get_ci_green: CI stopped at its visit cap, so CI did not run on the head commit.
- final_review: the required-only rounds used their rounds, and a commit after them has no review.
- resolve_items: a feedback round stopped at its item cap.
"""

import json
import sys
from typing import Any

REVIEW_ROUNDS = 3  # keep equal to the edge from resolve in skill.yaml


def list_limits(state: dict[str, Any]) -> list[str]:
    limits: list[str] = []
    if not state["build_done"]:
        limits.append("implement_step")
    if state["resolve_rounds"] >= REVIEW_ROUNDS and state["last_fixed"] > 0:
        limits.append("review")
    if state["ready_runs"] > state["ci_runs"]:
        limits.append("get_ci_green")
    if state["unreviewed"]:
        limits.append("final_review")
    if state["items_left"] > 0:
        limits.append("resolve_items")
    return limits


def main() -> None:
    print(json.dumps({"limits": list_limits(json.load(sys.stdin))}))


if __name__ == "__main__":
    main()
