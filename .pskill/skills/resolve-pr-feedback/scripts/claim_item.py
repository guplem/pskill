# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Mark a comment with the eyes reaction as its work starts, so no other run picks it up.

Usage: uv run claim_item.py, with {"item"} on stdin: one item of collect_items.py. Prints {"claimed": true|false}.
A finding needs no mark. A review body cannot take a reaction on GitHub, so its reply marker alone marks it as
addressed.
"""

import json
import subprocess
import sys
from typing import Any

REACTION_ENDPOINTS = {
    "inline": "repos/{{owner}}/{{repo}}/pulls/comments/{id}/reactions",
    "conversation": "repos/{{owner}}/{{repo}}/issues/comments/{id}/reactions",
}


def run(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


def main() -> None:
    item: dict[str, Any] = json.load(sys.stdin)["item"]
    endpoint = REACTION_ENDPOINTS.get(item.get("comment_kind", "")) if item["kind"] == "comment" else None
    if endpoint is not None:
        run(["gh", "api", endpoint.format(id=item["id"]), "-f", "content=eyes"])
    print(json.dumps({"claimed": endpoint is not None}))


if __name__ == "__main__":
    main()
