# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""List what a pull request changes, for the `when` of each reviewer.

Usage: uv run read_pr.py, with {"base", "head_sha", "plan_file"} on stdin, from the checkout-pr skill. An empty
plan_file means no plan.
Prints {"paths", "code_paths"}: every changed path, and the ones that are not documentation.

The checkout is at the head commit, so a local diff against the base gives the changes. GitHub's data can lag a push,
and its file list stops at 100 files. The plan file does not count: it leaves the branch before the pull request is
ready. The reviewers and their conditions live in the `review` block of skill.yaml; this script decides nothing.
"""

import json
import subprocess
import sys

DOCUMENTATION_SUFFIXES = (".md", ".mdx", ".rst", ".txt")
DOCUMENTATION_FOLDERS = ("docs/", "doc/")


def run(command: list[str]) -> str:
    return subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True
    ).stdout.strip()


def is_documentation(path: str) -> bool:
    return path.lower().endswith(DOCUMENTATION_SUFFIXES) or path.startswith(DOCUMENTATION_FOLDERS)


def main() -> None:
    script_input = json.load(sys.stdin)
    base, head_sha, plan_file = str(script_input["base"]), str(script_input["head_sha"]), str(script_input["plan_file"])
    output = run(["git", "diff", "--name-only", f"origin/{base}...{head_sha}"])
    paths = [path for path in output.splitlines() if path and path != plan_file]
    print(json.dumps({"paths": paths, "code_paths": [path for path in paths if not is_documentation(path)]}))


if __name__ == "__main__":
    main()
