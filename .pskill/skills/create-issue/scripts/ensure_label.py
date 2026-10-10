# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Make sure that the repository has the label for issues that no human checked yet.

Usage: uv run ensure_label.py, with {"repo"} on stdin: the repository as owner/name.
Prints {"label"}. It creates the label, and keeps a label of that name that already exists.
"""

import json
import sys

from github_rest import gh_api_call

LABEL = {
    "name": "waiting-for-human-check",
    "color": "D93F0B",
    "description": "No human has verified this yet: direct AI output",
}


def main() -> None:
    repo = str(json.load(sys.stdin)["repo"])
    result = gh_api_call(f"repos/{repo}/labels", "POST", LABEL)
    if result.returncode != 0 and "already_exists" not in result.stderr + result.stdout:
        sys.exit(f"The label {LABEL['name']} could not be created in {repo}: {result.stderr.strip()}")
    print(json.dumps({"label": LABEL["name"]}))


if __name__ == "__main__":
    main()
