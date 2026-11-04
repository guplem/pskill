# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Post the suggestion findings that the run does not fix, as one comment on the pull request.

Usage: uv run post_suggestions.py, with {"pr", "suggestions"} on stdin: the suggestion findings of collect_items.py.
Prints {"comment_url"}. The comment ends with `<!-- resolve-pr-feedback-suggestions -->`, so collect_items.py never
takes it for a comment to resolve.
"""

import json
import sys
from typing import Any

from github_rest import gh_api

SUGGESTIONS_MARKER = "<!-- resolve-pr-feedback-suggestions -->"


def suggestion_line(suggestion: dict[str, Any]) -> str:
    reviewer = f" ({suggestion['reviewer']})" if suggestion.get("reviewer") else ""
    return f"- **{suggestion['title']}** at `{suggestion['file']}:{suggestion['line']}`{reviewer}: {suggestion['summary']}"


def main() -> None:
    script_input = json.load(sys.stdin)
    lines = "\n".join(suggestion_line(suggestion) for suggestion in script_input["suggestions"])
    body = (
        "The review also made these suggestions. This pull request does not apply them; "
        f"each one is for a person to take or leave:\n\n{lines}\n\n{SUGGESTIONS_MARKER}"
    )
    comment = gh_api(f"repos/{{owner}}/{{repo}}/issues/{script_input['pr']}/comments", "POST", {"body": body})
    print(json.dumps({"comment_url": comment["html_url"]}))


if __name__ == "__main__":
    main()
