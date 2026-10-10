"""The example skills reach GitHub only through calls that work in a Claude Code cloud session.

Why: in a Claude Code cloud session, `gh` reaches GitHub through a proxy. That proxy refuses GraphQL (HTTP 403), the
search API, and the next-page link of `gh api --paginate` (and `--slurp`). Most `gh pr`, `gh issue`, `gh repo`, and
`gh label` commands use GraphQL. So the skills use only `gh api` with REST paths (paged by number, through each
skill's `scripts/github_rest.py`), `gh pr diff`, `gh run`, and `gh workflow`.

This is a restriction of Claude Code, not a rule of pskill. When the proxy allows GraphQL, the search API, and
`--paginate`, delete this test, and the skills can use the plain `gh` commands again.

The test reads the code of each script (its `gh` command lists and its github_rest helper calls, not its
docstrings), and the full text of each instruction, brief, reference, agent, and `skill.yaml`.
"""

import re
from pathlib import Path

import pytest

from tests.skill_scripts import SKILLS_FOLDER

AGENTS_FOLDER = SKILLS_FOLDER.parent / "agents"
ALLOWED_COMMANDS = {("api", None), ("pr", "diff"), ("run", None), ("workflow", None)}
# The proxy refuses the GraphQL endpoint and the search API.
REFUSED_API_PATHS = {"graphql", "search"}
# mark_ready.py tries `gh pr ready` first, then the route that only the cloud proxy has.
ALLOWED_EXCEPTIONS = {("implement-issue/scripts/mark_ready.py", "gh pr ready")}
REFUSED_OPTIONS = ("--paginate", "--slurp")

# `"gh", "pr", "view"` in Python, `[gh, pr, view]` in YAML, and `gh pr view` in text. Each pattern skips a method
# flag (`-X GET`, `--method GET`) before the second word, because the second word of `gh api` is its path.
PYTHON_GH_COMMAND = re.compile(
    r'"gh",\s*"(?P<command>[\w-]+)"(?:,\s*"(?:-X|--method)",\s*"\w+")?(?:,\s*f?"(?P<subcommand>[\w-]+))?'
)
YAML_GH_COMMAND = re.compile(
    r"""\[\s*["']?gh["']?,\s*["']?(?P<command>[\w-]+)["']?"""
    r"""(?:,\s*["']?(?:-X|--method)["']?,\s*["']?\w+["']?)?(?:,\s*["']?(?P<subcommand>[\w-]+))?"""
)
TEXT_GH_COMMAND = re.compile(r"\bgh\s+(?P<command>[\w-]+)(?:\s+(?:-X|--method)\s+\w+)?(?:\s+(?P<subcommand>[\w-]+))?")
# `gh_api("<path>")`, `gh_api_pages(...)`, and `gh_api_call(...)`: the github_rest helper runs `gh api <path>`.
PYTHON_HELPER_CALL = re.compile(r'\bgh_api(?:_pages|_call)?\(\s*f?"(?P<subcommand>[\w-]+)')


def is_allowed(command: str, subcommand: str | None) -> bool:
    if command == "api":
        # The second word of a `gh api` call is the first word of its path.
        return subcommand not in REFUSED_API_PATHS
    return (command, None) in ALLOWED_COMMANDS or (command, subcommand) in ALLOWED_COMMANDS


def refused_calls(text: str, is_python: bool) -> list[str]:
    """Each `gh` call in the text that the cloud proxy refuses, and each refused option."""
    patterns = [PYTHON_GH_COMMAND, PYTHON_HELPER_CALL] if is_python else [YAML_GH_COMMAND, TEXT_GH_COMMAND]
    calls = [
        (match.groupdict().get("command") or "api", match.group("subcommand"))
        for pattern in patterns
        for match in pattern.finditer(text)
    ]
    found = [
        f"gh {command} {subcommand or ''}".strip()
        for command, subcommand in calls
        if not is_allowed(command, subcommand)
    ]
    for option in REFUSED_OPTIONS:
        if (f'"{option}"' if is_python else option) in text:
            found.append(option)
    return found


def skill_files() -> list[Path]:
    patterns = ["*/scripts/*.py", "*/instructions/*.md", "*/briefs/*.md", "*/references/*.md", "*/skill.yaml"]
    return sorted(path for pattern in patterns for path in SKILLS_FOLDER.glob(pattern))


def test_the_scan_reads_every_kind_of_skill_file() -> None:
    kinds = {path.parent.name if path.suffix != ".yaml" else "skill.yaml" for path in skill_files()}

    assert {"scripts", "instructions", "references", "skill.yaml"} <= kinds


@pytest.mark.parametrize("path", [*skill_files(), *sorted(AGENTS_FOLDER.glob("*.md"))], ids=str)
def test_a_skill_file_uses_no_github_call_that_the_cloud_proxy_refuses(path: Path) -> None:
    relative = path.relative_to(SKILLS_FOLDER.parent).as_posix().removeprefix("skills/")
    calls = refused_calls(path.read_text(encoding="utf-8"), is_python=path.suffix == ".py")

    refused = [call for call in calls if (relative, call) not in ALLOWED_EXCEPTIONS]

    assert refused == [], f"{relative} uses GitHub calls that a Claude Code cloud session refuses: {refused}"


@pytest.mark.parametrize(
    ("text", "is_python", "refused"),
    [
        ('run(["gh", "pr", "view", pr_number])', True, ["gh pr view"]),
        ('run(["gh", "api", "user"])', True, []),
        ('run(["gh", "api", "graphql", "-f", "query=x"])', True, ["gh api graphql"]),
        ('run(["gh", "api", path, "--paginate"])', True, ["--paginate"]),
        ('"""`gh pr view` once ran here."""', True, []),
        ("run: [gh, issue, create, --title, x]", False, ["gh issue create"]),
        ('run: [gh, "pr", view, "7"]', False, ["gh pr view"]),
        ("run: ['gh', pr, 'view']", False, ["gh pr view"]),
        ('run: [gh, api, "repos/{owner}/{repo}"]', False, []),
        ('run: [gh, api, "search/issues?q=x"]', False, ["gh api search"]),
        ("Search with `gh api search/issues?q=x`.", False, ["gh api search"]),
        ('run(["gh", "api", "search/issues?q=x"])', True, ["gh api search"]),
        ('run(["gh", "api", f"search/issues?q={terms}"])', True, ["gh api search"]),
        ('gh_api(f"search/issues?q={terms}")', True, ["gh api search"]),
        ('gh_api("graphql", "POST", {"query": "x"})', True, ["gh api graphql"]),
        ('gh_api_pages("search/issues?q=x", "items")', True, ["gh api search"]),
        ('gh_api_call("repos/{owner}/{repo}/labels", "POST", LABEL)', True, []),
        ('gh_api(f"repos/{{owner}}/{{repo}}/pulls/{pr_number}")', True, []),
        ('run(["gh", "api", "--method", "GET", "search/issues"])', True, ["gh api search"]),
        ("Search with `gh api -X GET search/issues`.", False, ["gh api search"]),
        ('run: [gh, api, --method, GET, "search/issues"]', False, ["gh api search"]),
        ("Read it with `gh issue view 7 --comments`.", False, ["gh issue view"]),
        ("Compare it with `gh pr diff 7`, then `gh run view 1 --log-failed`.", False, []),
        ("Read every page: `gh api repos/{owner}/{repo}/pulls --paginate --slurp`.", False, ["--paginate", "--slurp"]),
    ],
)
def test_the_scan_finds_each_refused_call(text: str, is_python: bool, refused: list[str]) -> None:
    assert refused_calls(text, is_python) == refused
