# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Mark the pull request ready for review, then remove the implementation plan from the branch.

Usage: uv run mark_ready.py, with {"pr", "plan_file"} on stdin.
Prints {"head_sha"}, the head commit after the push. A second run changes nothing: the pull request is ready, the
plan is gone, and the push has nothing to send.

The pull request becomes ready before the push, so CI runs on the final head commit of a ready pull request. A CI
workflow that cancels older runs of the same branch drops the run that marking it ready started.
"""

import json
import subprocess
import sys


def run(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


def succeeds(command: list[str]) -> bool:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False).returncode == 0


def main() -> None:
    script_input = json.load(sys.stdin)
    pr_number, plan_file = str(script_input["pr"]), str(script_input["plan_file"])

    if run(["gh", "pr", "view", pr_number, "--json", "isDraft", "--jq", ".isDraft"]) == "true":
        run(["gh", "pr", "ready", pr_number])
    if succeeds(["git", "ls-files", "--error-unmatch", "--", plan_file]):
        run(["git", "rm", "--quiet", plan_file])
        run(["git", "commit", "--quiet", "-m", "Remove the implementation plan"])
    # Always push: a run that stopped after the commit has to send it now.
    run(["git", "push", "--quiet"])

    print(json.dumps({"head_sha": run(["git", "rev-parse", "HEAD"])}))


if __name__ == "__main__":
    main()
