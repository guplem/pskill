# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Name each limit that cut the work of the run short, once, for the finish edge, its instruction, and the report.

Usage: uv run list_limits.py, with {"build_done", "ready_runs", "ci_runs", "critical_rounds", "last_critical_findings",
"pushed_since_ready", "items_left"} on stdin. `pushed_since_ready` is true when the last comment round left a head
other than the one that ready pushed.
Prints {"limits": [...], "unreviewed_push"}. The limits come in this order, each one that applies:
- implement_step: the build stopped before the plan was done.
- get_ci_green: CI stopped at its visit cap, so CI did not run on the head commit.
- critical: the critical rounds stopped at their cap. Either the last round was not clean (its findings were fixed
  with no review, or got no fix), or the safety cap of the critical block stopped the round of a push.
- resolve_items: a feedback round stopped at its item cap.
`unreviewed_push` is true when that safety cap stopped the round of a push.
"""

import json
import sys
from typing import Any

CRITICAL_ROUNDS = 6  # keep equal to the edge from critical_resolve in skill.yaml
CRITICAL_VISITS = 13  # keep equal to max_visits of the critical block in skill.yaml


def unreviewed_push(state: dict[str, Any]) -> bool:
    """The safety cap of the critical block stopped the round of a push: only the comment round leads there."""
    return state["critical_rounds"] >= CRITICAL_VISITS and state["pushed_since_ready"] is True


def list_limits(state: dict[str, Any]) -> list[str]:
    limits: list[str] = []
    if not state["build_done"]:
        limits.append("implement_step")
    if state["ready_runs"] > state["ci_runs"]:
        limits.append("get_ci_green")
    # A round with findings always has another round after it, unless the cap sent its resolution to CI.
    last_round_not_clean = state["critical_rounds"] >= CRITICAL_ROUNDS and state["last_critical_findings"] > 0
    if last_round_not_clean or unreviewed_push(state):
        limits.append("critical")
    if state["items_left"] > 0:
        limits.append("resolve_items")
    return limits


def main() -> None:
    state = json.load(sys.stdin)
    print(json.dumps({"limits": list_limits(state), "unreviewed_push": unreviewed_push(state)}))


if __name__ == "__main__":
    main()
