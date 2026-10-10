# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Find the existing issues that could be duplicates: the ones that hold the most search words.

Usage: uv run search_issues.py, with {"repo", "terms"} on stdin: the repository as owner/name, and the search words.
Prints [{"number", "title", "state", "url"}]: at most 30 issues, open or closed, with the most matching words first.

It reads the newest 1,000 issues and pull requests, leaves out the pull requests, and counts the whole words (any
case) in each title and body. The Claude Code cloud GitHub proxy refuses the search API, so the script searches
by itself.
"""

import json
import re
import sys
from typing import Any

from github_rest import gh_api_pages

MAX_PAGES_READ = 10
MAX_RESULTS = 30


def matching_issues(repo: str, terms: list[str]) -> list[dict[str, Any]]:
    pages_read = 0

    def enough(page: list[Any]) -> bool:
        nonlocal pages_read
        pages_read += 1
        return pages_read >= MAX_PAGES_READ

    # The list is newest first, so the early stop keeps the newest issues.
    items = gh_api_pages(f"repos/{repo}/issues?state=all", stop=enough)
    words = [term.lower() for term in terms]
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in items:
        if "pull_request" in item:
            continue
        text = f"{item['title']} {item['body'] or ''}".lower()
        # Whole words only: "ci" must not match "decision".
        score = sum(bool(re.search(rf"\b{re.escape(word)}\b", text)) for word in words)
        if score:
            scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], -pair[1]["number"]))
    return [
        {"number": item["number"], "title": item["title"], "state": item["state"], "url": item["html_url"]}
        for _, item in scored[:MAX_RESULTS]
    ]


def main() -> None:
    script_input = json.load(sys.stdin)
    print(json.dumps(matching_issues(str(script_input["repo"]), [str(term) for term in script_input["terms"]])))


if __name__ == "__main__":
    main()
