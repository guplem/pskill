# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Post one comment on an issue or a pull request, from a file.

Usage: uv run post_comment.py, with {"number", "body_file"} on stdin: body_file holds the comment's Markdown.
Prints {"comment_url"}.

The body goes from the file to the REST call with no shell in between, so its backticks, `$`, and quotes stay text.
"""

import json
import sys

from github_rest import gh_api


def main() -> None:
    script_input = json.load(sys.stdin)
    # newline="" keeps the line endings of the file as they are.
    with open(script_input["body_file"], encoding="utf-8", newline="") as body_file:
        body = body_file.read()
    comment = gh_api(f"repos/{{owner}}/{{repo}}/issues/{script_input['number']}/comments", "POST", {"body": body})
    print(json.dumps({"comment_url": comment["html_url"]}))


if __name__ == "__main__":
    main()
