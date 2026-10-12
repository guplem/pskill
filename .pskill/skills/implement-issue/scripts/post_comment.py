# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Post the pause comment of a run on an issue or a pull request, from a file. Safe to run twice.

Usage: uv run post_comment.py, with {"number", "run_id", "body_file"} on stdin: body_file holds the comment's Markdown.
Prints {"comment_url", "updated"}.

The comment ends with the marker `<!-- implement-issue-pause: <run_id> -->`. When a comment with the marker exists,
the script updates it instead of posting a second one, so a run keeps one pause comment that says its latest pause.
The body goes from the file to the REST call with no shell in between, so its backticks, `$`, and quotes stay text.
"""

import json
import sys
from typing import Any

from github_rest import gh_api, gh_api_pages


def pause_marker(run_id: str) -> str:
    return f"<!-- implement-issue-pause: {run_id} -->"


def comment_of_run(number: int, marker: str) -> dict[str, Any] | None:
    comments: list[dict[str, Any]] = gh_api_pages(f"repos/{{owner}}/{{repo}}/issues/{number}/comments")
    return next((comment for comment in comments if marker in (comment.get("body") or "")), None)


def main() -> None:
    script_input = json.load(sys.stdin)
    # newline="" keeps the line endings of the file as they are.
    with open(script_input["body_file"], encoding="utf-8", newline="") as body_file:
        marker = pause_marker(str(script_input["run_id"]))
        body = f"{body_file.read().rstrip()}\n\n{marker}"
    existing = comment_of_run(script_input["number"], marker)
    if existing is None:
        path, method = f"repos/{{owner}}/{{repo}}/issues/{script_input['number']}/comments", "POST"
    else:
        path, method = f"repos/{{owner}}/{{repo}}/issues/comments/{existing['id']}", "PATCH"
    comment = gh_api(path, method, {"body": body})
    print(json.dumps({"comment_url": comment["html_url"], "updated": existing is not None}))


if __name__ == "__main__":
    main()
