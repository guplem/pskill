# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Switch the checkout to the latest commit of the base branch, claim the issue, and name the branch and plan file.

Usage: uv run checkout_base.py, with {"base", "slug", "issue"} on stdin. An issue of 0 means no issue.
Prints {"ok": true, "base", "branch", "plan_file"}. The branch is `<issue>-<slug>`, or `<slug>` with no issue. It
assigns the issue to the logged-in user, the person who started the run. open_draft_pr.py creates the branch later.
It changes nothing and prints {"ok": false, "reason"} when the branch already exists or when the base branch cannot
be fetched. checkout_default_branch.py already stopped the run on uncommitted changes.
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


def blocking_reason(base: str, branch: str) -> str | None:
    if run(["git", "ls-remote", "--heads", "origin", f"refs/heads/{branch}"]):
        return f"The branch {branch} already exists on GitHub."
    if succeeds(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"]):
        return f"The branch {branch} already exists in this checkout."
    if not succeeds(["git", "fetch", "--quiet", "origin", base]):
        return f"The base branch {base} cannot be fetched from GitHub."
    return None


def main() -> None:
    script_input: dict[str, Any] = json.load(sys.stdin)
    base = str(script_input["base"]).removeprefix("origin/")
    slug = str(script_input["slug"])
    issue = str(script_input["issue"]) if script_input["issue"] else ""
    branch = f"{issue}-{slug}" if issue else slug

    reason = blocking_reason(base, branch)
    if reason:
        print(json.dumps({"ok": False, "reason": reason}))
        return

    run(["git", "switch", "--quiet", "--detach", f"origin/{base}"])
    if issue:
        login = str(gh_api("user")["login"])
        gh_api(f"repos/{{owner}}/{{repo}}/issues/{issue}/assignees", "POST", {"assignees": [login]})
    plan_file = f"implementation-plan-{issue or slug}.md"
    print(json.dumps({"ok": True, "base": base, "branch": branch, "plan_file": plan_file}))


if __name__ == "__main__":
    main()
