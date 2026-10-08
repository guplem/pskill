# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Check out the branch of a pull request at its latest commit on GitHub.

Usage: uv run checkout_pr.py, with {"pr"} on stdin.
Prints {"branch", "base", "head_sha", "plan_file"}. plan_file is the implementation plan file that the branch added,
or "" when it added none. The script finds it in the branch history, so it also finds a plan that left the branch.

It changes nothing when the checkout is already on the branch at the latest commit. It only switches branches and
fast-forwards, so it never discards a change. It changes nothing, prints the reason on stderr, and exits 1 (the run
pauses until the user fixes the cause and resumes) when:
- the pull request is closed, is merged, or comes from a fork (this checkout cannot push to it),
- the checkout has uncommitted changes (they belong to the user),
- a branch cannot be fetched,
- the local branch has commits that GitHub does not have,
- the branch has no `.pskill/` yet: switching to it would delete the runner of this run.
"""

import json
import subprocess
import sys
from typing import Any

PLAN_FILE_PATTERN = "implementation-plan-*.md"


def run(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


def succeeds(command: list[str]) -> bool:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False).returncode == 0


def has_local_branch(branch: str) -> bool:
    return succeeds(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"])


def uncommitted_files() -> str:
    """The first changed files of the checkout, or an empty text when it has no change."""
    status = run(["git", "status", "--porcelain"])
    # The strip in run() removes the leading space of the first status line, so split instead of slicing.
    return ", ".join(line.split(maxsplit=1)[-1] for line in status.splitlines()[:5])


def blocking_reason(pr_number: str, pr: dict[str, Any]) -> str | None:
    branch, base = pr["headRefName"], pr["baseRefName"]
    if pr["state"] != "OPEN":
        return f"Pull request #{pr_number} is {pr['state'].lower()}."
    if pr["isCrossRepository"]:
        return f"Pull request #{pr_number} comes from a fork, so this checkout cannot push to it."
    files = uncommitted_files()
    if files:
        return f"The checkout has uncommitted changes: {files}"
    if not succeeds(["git", "fetch", "--quiet", "origin", branch, base]):
        return f"The branches {branch} and {base} cannot be fetched from GitHub."
    if has_local_branch(branch) and not succeeds(["git", "merge-base", "--is-ancestor", branch, f"origin/{branch}"]):
        return f"The local branch {branch} has commits that GitHub does not have: push or remove them."
    if not succeeds(["git", "cat-file", "-e", f"origin/{branch}:.pskill/pskill.py"]):
        return f"The branch {branch} has no .pskill/ yet: merge {base} into it first."
    return None


def switch_to(branch: str) -> None:
    if not has_local_branch(branch):
        run(["git", "switch", "--quiet", "--create", branch, "--track", f"origin/{branch}"])
        return
    if run(["git", "branch", "--show-current"]) != branch:
        run(["git", "switch", "--quiet", branch])
    run(["git", "merge", "--quiet", "--ff-only", f"origin/{branch}"])


def plan_file(base: str) -> str:
    """The newest plan file that a commit of the branch added."""
    added = run(
        ["git", "log", "--diff-filter=A", "--name-only", "--format=", f"origin/{base}..HEAD", "--", PLAN_FILE_PATTERN]
    )
    return next((path for path in added.splitlines() if path), "")


def main() -> None:
    pr_number = str(json.load(sys.stdin)["pr"])
    pr: dict[str, Any] = json.loads(
        run(["gh", "pr", "view", pr_number, "--json", "state,headRefName,baseRefName,isCrossRepository"])
    )
    reason = blocking_reason(pr_number, pr)
    if reason:
        print(reason, file=sys.stderr)
        sys.exit(1)
    switch_to(pr["headRefName"])
    print(
        json.dumps(
            {
                "branch": pr["headRefName"],
                "base": pr["baseRefName"],
                "head_sha": run(["git", "rev-parse", "HEAD"]),
                "plan_file": plan_file(pr["baseRefName"]),
            }
        )
    )


if __name__ == "__main__":
    main()
