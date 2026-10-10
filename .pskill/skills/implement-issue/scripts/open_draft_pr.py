# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Push the plan file on a new branch, and open a draft pull request with it.

Usage: uv run open_draft_pr.py, with {"branch", "base", "plan_file", "title", "issue"} on stdin. An issue of 0 means
no issue.
Prints {"pr_number", "pr_url"}.

The checkout is at the latest base commit, with the plan file written and not committed yet. A second run finishes
the work of a first run that stopped halfway: it reuses the branch, the commit, and an open pull request of the branch.
"""

import json
import subprocess
import sys
from typing import Any

from github_rest import gh_api


def run(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


def succeeds(command: list[str]) -> bool:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False).returncode == 0


def switch_to_new_branch(branch: str) -> None:
    if run(["git", "branch", "--show-current"]) == branch:
        return
    if succeeds(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"]):
        run(["git", "switch", "--quiet", branch])
    else:
        run(["git", "switch", "--quiet", "--create", branch])


def commit_plan(plan_file: str) -> None:
    if run(["git", "status", "--porcelain", "--", plan_file]):
        run(["git", "add", "--", plan_file])
        run(["git", "commit", "--quiet", "-m", "Add the implementation plan"])


def pull_request_body(plan_file: str, issue: str) -> str:
    closes = f"Closes #{issue}\n\n" if issue else ""
    return f"{closes}The plan is in `{plan_file}`. The description follows with the code."


def open_pull_request(script_input: dict[str, Any], issue: str) -> dict[str, Any]:
    """The open pull request of the branch, or a new draft one, assigned to the logged-in user."""
    branch = str(script_input["branch"])
    existing: list[dict[str, Any]] = gh_api(f"repos/{{owner}}/{{repo}}/pulls?head={{owner}}:{branch}&state=open")
    if existing:
        return existing[0]
    new_pull_request = {
        "title": str(script_input["title"]),
        "head": branch,
        "base": str(script_input["base"]),
        "body": pull_request_body(str(script_input["plan_file"]), issue),
        "draft": True,
    }
    created: dict[str, Any] = gh_api("repos/{owner}/{repo}/pulls", "POST", new_pull_request)
    login = str(gh_api("user")["login"])
    gh_api(f"repos/{{owner}}/{{repo}}/issues/{created['number']}/assignees", "POST", {"assignees": [login]})
    return created


def main() -> None:
    script_input: dict[str, Any] = json.load(sys.stdin)
    branch = str(script_input["branch"])
    issue = str(script_input["issue"]) if script_input["issue"] else ""

    switch_to_new_branch(branch)
    commit_plan(str(script_input["plan_file"]))
    run(["git", "push", "--quiet", "--set-upstream", "origin", branch])
    pull_request = open_pull_request(script_input, issue)
    print(json.dumps({"pr_number": pull_request["number"], "pr_url": pull_request["html_url"]}))


if __name__ == "__main__":
    main()
