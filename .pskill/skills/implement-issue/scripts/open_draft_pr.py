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


def open_pull_request(script_input: dict[str, Any], issue: str) -> str:
    branch = str(script_input["branch"])
    existing = run(["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "url", "--jq", ".[0].url"])
    if existing:
        return existing
    body = pull_request_body(str(script_input["plan_file"]), issue)
    command = ["gh", "pr", "create", "--draft", "--base", str(script_input["base"]), "--title"]
    return run([*command, str(script_input["title"]), "--assignee", "@me", "--body", body])


def main() -> None:
    script_input: dict[str, Any] = json.load(sys.stdin)
    branch = str(script_input["branch"])
    issue = str(script_input["issue"]) if script_input["issue"] else ""

    switch_to_new_branch(branch)
    commit_plan(str(script_input["plan_file"]))
    run(["git", "push", "--quiet", "--set-upstream", "origin", branch])
    pr_url = open_pull_request(script_input, issue).splitlines()[-1]
    print(json.dumps({"pr_number": int(pr_url.rstrip("/").rsplit("/", 1)[-1]), "pr_url": pr_url}))


if __name__ == "__main__":
    main()
