# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Find the commits after the reviewed commit that change the pull request.

Usage: uv run check_head.py, with {"pr", "reviewed_sha"} on stdin.
Prints {"head_sha", "commits"}: the head commit on GitHub, and the short hashes of the new commits. A clean merge of
the base branch changes nothing in the pull request, so it is left out.
"""

import json
import subprocess
import sys
from typing import Any

from github_rest import gh_api


def run(command: list[str]) -> str:
    return subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True
    ).stdout.strip()


def is_clean_merge(commit: str) -> bool:
    parents = run(["git", "rev-list", "--parents", "-n", "1", commit]).split()[1:]
    if len(parents) < 2:
        return False
    # Clean only when git's own merge of the parents gives the same tree. `git show --cc` is not enough: a conflict
    # resolved by taking the base side prints nothing there, yet it drops the change of the pull request.
    try:
        merged_tree = run(["git", "merge-tree", "--write-tree", *parents]).split()[0]
    except subprocess.CalledProcessError:  # git merge-tree exits 1 when the parents conflict
        return False
    return merged_tree == run(["git", "rev-parse", f"{commit}^{{tree}}"])


def new_commits(reviewed_sha: str, head_sha: str) -> list[str]:
    # `--first-parent` skips the commits that a merge brings in from the base branch.
    commits = run(["git", "rev-list", "--reverse", "--first-parent", f"{reviewed_sha}..{head_sha}"]).split()
    return [commit[:10] for commit in commits if not is_clean_merge(commit)]


def main() -> None:
    script_input = json.load(sys.stdin)
    pr_number, reviewed_sha = str(script_input["pr"]), str(script_input["reviewed_sha"])
    head: dict[str, Any] = gh_api(f"repos/{{owner}}/{{repo}}/pulls/{pr_number}")["head"]
    head_sha = str(head["sha"])
    commits: list[str] = []
    if head_sha != reviewed_sha:
        run(["git", "fetch", "--quiet", "origin", head["ref"]])
        commits = new_commits(reviewed_sha, head_sha)
    print(json.dumps({"head_sha": head_sha, "commits": commits}))


if __name__ == "__main__":
    main()
