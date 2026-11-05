# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Read every CI check of the head commit of a pull request, and wait while one is still running.

Usage: uv run read_checks.py, with {"pr", "wait_s"} on stdin. `wait_s` is the most seconds to wait (at most 6900,
115 minutes: the skill runs it as a background script block that the runner stops after 7140 seconds).
Prints {"head_sha", "state", "mergeable", "draft", "checks", "failed_checks"}.
- `state` is `passed` (every check passed, or no check exists and nothing stops CI), `failed`, or `closed` (the
  pull request is merged or closed, so no wait or fix is needed).
- `checks` is [{"name", "state", "link"}], with the state `pending`, `failed`, or `passed`. A skipped check passed.
- `failed_checks` is ["<name>: <link>"]. The link of a check run holds the `/actions/runs/<run id>/` of its workflow.
  A check still running when the wait ends is "<name> (still running after <n> minutes): <link>". With no check,
  it is ["merge conflict"] or ["draft"]: neither starts CI.
- `mergeable` is GitHub's answer: false means a merge conflict, null means GitHub did not compute it yet.
- `draft` is true for a draft pull request.

It polls every 30 seconds and returns when no check is pending. While no check exists, it waits at most 300 seconds
for one to start, and longer while `mergeable` is null. A read that fails (GitHub or git) is skipped, and the next
poll tries again; only a failed last read at the end of the wait exits with an error. The head commit is the one on
origin, because GitHub can serve an old head for minutes after a push. Both the check runs and the commit statuses
count. The newest run of each check wins, so a run that a rerun cancelled or replaced does not count, and the newest
status of each context wins. It replaces `gh pr checks --watch`, which uses GraphQL: the Claude Code cloud GitHub
proxy refuses that.
"""

import json
import subprocess
import sys
import time
from collections.abc import Callable
from typing import Any

from github_rest import gh_api, gh_api_pages, is_cross_repository

POLL_SECONDS = 30
MAX_WAIT_SECONDS = 6900
NO_CHECK_WAIT_SECONDS = 300
PASSING_CONCLUSIONS = {"success", "skipped", "neutral"}
STATE_OF_COMMIT_STATUS = {"success": "passed", "pending": "pending"}


def run(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


def remote_head(branch: str) -> str:
    """The head commit of the branch on origin, or an empty text when origin has no such branch."""
    output = run(["git", "ls-remote", "origin", f"refs/heads/{branch}"]).split()
    return output[0] if output else ""


def check_rows(check_runs: list[dict[str, Any]], statuses: list[dict[str, Any]]) -> list[dict[str, str]]:
    """One row per check run, and one per status context, from the raw replies of GitHub."""
    rows: list[dict[str, str]] = []
    newest_run: dict[str, dict[str, Any]] = {}
    for check_run in check_runs:
        if check_run["name"] not in newest_run or check_run.get("id", 0) > newest_run[check_run["name"]].get("id", 0):
            newest_run[check_run["name"]] = check_run
    for check_run in newest_run.values():
        if check_run["status"] != "completed":
            state = "pending"
        else:
            state = "passed" if check_run["conclusion"] in PASSING_CONCLUSIONS else "failed"
        link = check_run.get("details_url") or check_run.get("html_url") or ""
        rows.append({"name": check_run["name"], "state": state, "link": link})
    newest_status: dict[str, dict[str, Any]] = {}
    for status in statuses:
        if status["context"] not in newest_status or status["id"] > newest_status[status["context"]]["id"]:
            newest_status[status["context"]] = status
    for status in newest_status.values():
        state = STATE_OF_COMMIT_STATUS.get(status["state"], "failed")
        rows.append({"name": status["context"], "state": state, "link": status.get("target_url") or ""})
    return rows


def overall_state(rows: list[dict[str, str]]) -> str:
    states = {row["state"] for row in rows}
    if not states:
        return "none"
    if "pending" in states:
        return "pending"
    return "failed" if "failed" in states else "passed"


def read_once(pr_number: int) -> dict[str, Any]:
    pull_request: dict[str, Any] = gh_api(f"repos/{{owner}}/{{repo}}/pulls/{pr_number}")
    # A fork branch is not on origin: then the head of GitHub is the only one.
    origin_head = "" if is_cross_repository(pull_request) else remote_head(pull_request["head"]["ref"])
    head_sha = origin_head or pull_request["head"]["sha"]
    check_runs = gh_api_pages(f"repos/{{owner}}/{{repo}}/commits/{head_sha}/check-runs", "check_runs")
    statuses = gh_api_pages(f"repos/{{owner}}/{{repo}}/commits/{head_sha}/statuses")
    rows = check_rows(check_runs, statuses)
    return {
        "head_sha": head_sha,
        "state": "closed" if pull_request.get("state") == "closed" else overall_state(rows),
        "mergeable": pull_request["mergeable"],
        "draft": pull_request["draft"],
        "checks": rows,
        "failed_checks": [f"{row['name']}: {row['link']}" for row in rows if row["state"] == "failed"],
    }


def try_read_once(pr_number: int) -> dict[str, Any] | None:
    """One read, or None when GitHub or git failed: a short outage must not end a wait of up to 2 hours."""
    try:
        return read_once(pr_number)
    except (SystemExit, subprocess.CalledProcessError, ValueError) as error:
        print(f"A read of the checks failed; the next poll tries again: {error}", file=sys.stderr)
        return None


def read_checks(
    pr_number: int,
    wait_s: int,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    wait_seconds = min(wait_s, MAX_WAIT_SECONDS)
    started = clock()
    # One poll at a time: each poll decides whether another one is needed.
    while True:
        result = try_read_once(pr_number)
        elapsed = clock() - started
        remaining = wait_seconds - elapsed
        if result is None:
            if remaining <= 0:
                sys.exit("The last read of the checks failed at the end of the wait: see the errors above.")
            sleep(min(POLL_SECONDS, remaining))
            continue
        if result["state"] in ("passed", "failed", "closed"):
            return result
        # While GitHub still computes `mergeable`, a conflict (which starts no CI) can still show up.
        if result["state"] == "none" and elapsed >= NO_CHECK_WAIT_SECONDS and result["mergeable"] is not None:
            return result
        if remaining <= 0:
            return result
        sleep(min(POLL_SECONDS, remaining))


def final_result(result: dict[str, Any], wait_s: int) -> dict[str, Any]:
    """The result with a `state` of passed, failed, or closed: what the skill acts on after the wait."""
    if result["state"] == "pending":
        minutes = min(wait_s, MAX_WAIT_SECONDS) // 60
        still_running = [
            f"{row['name']} (still running after {minutes} minutes): {row['link']}"
            for row in result["checks"]
            if row["state"] == "pending"
        ]
        return {**result, "state": "failed", "failed_checks": result["failed_checks"] + still_running}
    if result["state"] != "none":
        return result
    # No check exists: a conflict or a draft starts no CI; otherwise the repository runs none on this pull request.
    if result["mergeable"] is False:
        return {**result, "state": "failed", "failed_checks": ["merge conflict"]}
    if result["draft"]:
        return {**result, "state": "failed", "failed_checks": ["draft"]}
    return {**result, "state": "passed"}


def main() -> None:
    script_input = json.load(sys.stdin)
    wait_s = int(script_input.get("wait_s", MAX_WAIT_SECONDS))
    print(json.dumps(final_result(read_checks(int(script_input["pr"]), wait_s), wait_s)))


if __name__ == "__main__":
    main()
