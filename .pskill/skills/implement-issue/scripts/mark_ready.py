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

`gh pr ready` uses GraphQL, which the Claude Code cloud GitHub proxy refuses. There the script calls the route that
only that proxy has, `POST .../pulls/<n>/ccr/ready_for_review`. tests/test_skills_github_calls.py allows this one
GraphQL command.
"""

import json
import subprocess
import sys

from github_rest import gh_api

GRAPHQL_REFUSED = "GitHub GraphQL is not available"


def run(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


def succeeds(command: list[str]) -> bool:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False).returncode == 0


def gh_pr_ready(pr_number: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", "pr", "ready", pr_number],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def mark_ready_for_review(pr_number: str) -> None:
    pull_request_path = f"repos/{{owner}}/{{repo}}/pulls/{pr_number}"
    if not gh_api(pull_request_path)["draft"]:
        return
    result = gh_pr_ready(pr_number)
    if result.returncode == 0:
        return
    if GRAPHQL_REFUSED not in result.stderr:
        sys.exit(f"`gh pr ready {pr_number}` failed: {result.stderr.strip()}")
    gh_api(f"{pull_request_path}/ccr/ready_for_review", "POST")


def main() -> None:
    script_input = json.load(sys.stdin)
    pr_number, plan_file = str(script_input["pr"]), str(script_input["plan_file"])

    mark_ready_for_review(pr_number)
    if succeeds(["git", "ls-files", "--error-unmatch", "--", plan_file]):
        run(["git", "rm", "--quiet", plan_file])
        run(["git", "commit", "--quiet", "-m", "Remove the implementation plan"])
    # Always push: a run that stopped after the commit has to send it now.
    run(["git", "push", "--quiet"])

    print(json.dumps({"head_sha": run(["git", "rev-parse", "HEAD"])}))


if __name__ == "__main__":
    main()
