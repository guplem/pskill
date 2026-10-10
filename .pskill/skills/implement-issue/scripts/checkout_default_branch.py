# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Switch the checkout to the latest commit of the repository's default branch, so the work is understood on fresh code.

Usage: uv run checkout_default_branch.py
Prints {"ok": true, "default_branch"}. It changes nothing and prints {"ok": false, "reason"} when the checkout has
uncommitted changes (they belong to the user) or when the default branch cannot be fetched.
"""

import json
import subprocess

from github_rest import gh_api


def run(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


def succeeds(command: list[str]) -> bool:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False).returncode == 0


def uncommitted_files() -> str:
    """The first changed files of the checkout, or an empty text when it has no change."""
    status = run(["git", "status", "--porcelain"])
    # The strip in run() removes the leading space of the first status line, so split instead of slicing.
    return ", ".join(line.split(maxsplit=1)[-1] for line in status.splitlines()[:5])


def main() -> None:
    files = uncommitted_files()
    if files:
        print(json.dumps({"ok": False, "reason": f"The checkout has uncommitted changes: {files}"}))
        return
    default_branch = str(gh_api("repos/{owner}/{repo}")["default_branch"])
    if not succeeds(["git", "fetch", "--quiet", "origin", default_branch]):
        print(json.dumps({"ok": False, "reason": f"The branch {default_branch} cannot be fetched from GitHub."}))
        return
    run(["git", "switch", "--quiet", "--detach", f"origin/{default_branch}"])
    print(json.dumps({"ok": True, "default_branch": default_branch}))


if __name__ == "__main__":
    main()
