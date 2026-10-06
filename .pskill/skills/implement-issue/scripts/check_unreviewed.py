# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Find the commits after the last review that hold code that no review saw.

Usage: uv run check_unreviewed.py, with {"pr", "last_reviewed", "plan_file"} on stdin.
Prints unreviewed (true when such a commit exists), commits (their short hashes), and head_sha (the head commit on
GitHub). A commit needs no review when the agent wrote no code in it: it only deletes the plan file, or it is a
merge with no conflict resolution.
"""

import json
import subprocess
import sys


def run(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


def only_deletes(commit: str, path: str) -> bool:
    changes = run(["git", "diff-tree", "--no-commit-id", "--name-status", "-r", commit]).splitlines()
    return changes == [f"D\t{path}"]


def is_clean_merge(commit: str) -> bool:
    is_merge = len(run(["git", "rev-list", "--parents", "-n", "1", commit]).split()) > 2
    # `--cc` shows only the lines that differ from every parent: a conflict resolution, or code added in the merge.
    return is_merge and run(["git", "show", "--cc", "--format=", commit]) == ""


def unreviewed_commits(last_reviewed: str, head: str, plan_file: str) -> list[str]:
    # `--first-parent` skips the commits that a merge brings in from the base branch.
    commits = run(["git", "rev-list", "--reverse", "--first-parent", f"{last_reviewed}..{head}"]).split()
    return [commit[:10] for commit in commits if not only_deletes(commit, plan_file) and not is_clean_merge(commit)]


def main() -> None:
    script_input = json.load(sys.stdin)
    pr_number = str(script_input["pr"])
    branch = run(["gh", "pr", "view", pr_number, "--json", "headRefName", "--jq", ".headRefName"])
    head_sha = run(["gh", "pr", "view", pr_number, "--json", "headRefOid", "--jq", ".headRefOid"])
    run(["git", "fetch", "--quiet", "origin", branch])
    commits = unreviewed_commits(str(script_input["last_reviewed"]), head_sha, str(script_input["plan_file"]))
    print(json.dumps({"unreviewed": bool(commits), "commits": commits, "head_sha": head_sha}))


if __name__ == "__main__":
    main()
