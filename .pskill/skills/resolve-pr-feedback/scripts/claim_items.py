# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Mark every comment to resolve with the eyes reaction as the work starts, so no other run picks one up.

Usage: uv run claim_items.py, with {"items"} on stdin: the queue of collect_items.py. Prints {"claimed": <count>}.
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


def claim(item: dict[str, Any]) -> bool:
    """Add the eyes reaction to the item when it can take one, and say whether it did."""
    endpoint = REACTION_ENDPOINTS.get(item.get("comment_kind", "")) if item["kind"] == "comment" else None
    if endpoint is None:
        return False
    run(["gh", "api", endpoint.format(id=item["id"]), "-f", "content=eyes"])
    return True


def main() -> None:
    items: list[dict[str, Any]] = json.load(sys.stdin)["items"]
    print(json.dumps({"claimed": sum(claim(item) for item in items)}))


if __name__ == "__main__":
    main()
