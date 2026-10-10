# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Call the GitHub REST API through `gh api`, and read every page of a list.

One of six identical copies, in the scripts/ folder of checkout-pr, fix-ci, implement-issue, resolve-pr-feedback,
review-head-check and review-pr. Change all six together: tests/test_skill_github_rest.py
fails when they differ.

Why REST only: in a Claude Code cloud session, `gh` reaches GitHub through a proxy. That proxy refuses GraphQL
(HTTP 403), which most `gh pr` and `gh issue` commands use, and it refuses the next-page link of
`gh api --paginate`. This is a restriction of Claude Code, not a rule of pskill: when the proxy allows both,
the plain `gh` commands can come back (tests/test_skills_github_calls.py holds the rule).
"""

import json
import subprocess
import sys
from collections.abc import Callable
from typing import Any

MAX_PAGES = 50
PAGE_SIZE = 100


def gh_api_call(path: str, method: str = "GET", body: Any = None) -> subprocess.CompletedProcess[str]:
    """Run one `gh api` call and return the result, whatever its exit code. A body goes as JSON on stdin."""
    command: list[str] = ["gh", "api", "--method", method, path]
    if body is not None:
        command += ["--input", "-"]
    return subprocess.run(
        command,
        input=json.dumps(body) if body is not None else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def gh_api(path: str, method: str = "GET", body: Any = None) -> Any:
    """Return the parsed JSON reply (None for an empty reply), or exit with the error of `gh`."""
    result = gh_api_call(path, method, body)
    if result.returncode != 0:
        sys.exit(f"`gh api --method {method} {path}` failed: {result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def is_cross_repository(pull_request: dict[str, Any]) -> bool:
    """True when the head branch of a pull request reply is not in its base repository: a fork, or a deleted one."""
    head_repo = pull_request["head"]["repo"]
    return head_repo is None or head_repo["full_name"] != pull_request["base"]["repo"]["full_name"]


def item_key(item: Any) -> Any:
    """The identity of a list item, so a page that moved during the read does not give the item twice."""
    if isinstance(item, dict):
        return item.get("number", item.get("id"))
    return None


def gh_api_pages(path: str, key: str | None = None, stop: Callable[[list[Any]], bool] | None = None) -> list[Any]:
    """Read `<path>?per_page=100&page=N` from page 1 until a page holds fewer than 100 items.

    `key` names the list inside an object reply (`check_runs`). `stop` gets each page and ends the loop when it
    returns true.
    """
    separator = "&" if "?" in path else "?"
    items: list[Any] = []
    seen: set[Any] = set()
    # One page at a time: the items of a page decide whether a next page exists.
    for page in range(1, MAX_PAGES + 1):
        reply: Any = gh_api(f"{path}{separator}per_page={PAGE_SIZE}&page={page}")
        page_items: list[Any] = reply[key] if key is not None else reply
        for item in page_items:
            identity = item_key(item)
            if identity is None or identity not in seen:
                seen.add(identity)
                items.append(item)
        if len(page_items) < PAGE_SIZE or (stop is not None and stop(page_items)):
            return items
    sys.exit(f"`gh api {path}` has more than {MAX_PAGES} pages of {PAGE_SIZE} items.")
