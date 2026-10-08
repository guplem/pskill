"""Tests for the create-issue skill: every GitHub command targets the repository that the run resolved."""

from pathlib import Path

from pskill_runner.skill_loader import load_skill
from pskill_runner.skill_model import ScriptBlock

SKILL_FOLDER = Path(__file__).resolve().parent.parent / ".pskill" / "skills" / "create-issue"
RESOLVED_REPOSITORY = "{{ steps.resolve_repo.json.nameWithOwner }}"


def gh_commands() -> dict[str, list[str]]:
    """The `run` list of each script block that calls `gh`, by block id."""
    skill = load_skill(SKILL_FOLDER)
    return {
        block_id: [str(part) for part in block.run]
        for block_id, block in skill.blocks.items()
        if isinstance(block, ScriptBlock) and block.run[0] == "gh"
    }


def test_the_run_first_resolves_the_repository_from_the_repo_input() -> None:
    skill = load_skill(SKILL_FOLDER)

    assert [edge.to for edge in skill.entry] == ["resolve_repo"]
    assert gh_commands()["resolve_repo"] == ["gh", "repo", "view", "{{ inputs.repo }}", "--json", "nameWithOwner"]


def test_every_other_gh_command_names_the_resolved_repository() -> None:
    commands = {block_id: run for block_id, run in gh_commands().items() if block_id != "resolve_repo"}

    assert sorted(commands) == ["create", "ensure_label", "label_issue", "search_duplicates"]
    for block_id, run in commands.items():
        assert run[run.index("--repo") + 1] == RESOLVED_REPOSITORY, block_id
