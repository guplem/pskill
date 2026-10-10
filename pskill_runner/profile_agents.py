"""Profile agents: the harness agents that `pskill sync` writes for the tool profiles that skills use.

A profile agent holds tools only: no prompt and no model (SPEC.md 6.3). Only Claude Code gets them; a Codex
agent file cannot limit the sandbox or the MCP servers. `sync` never touches a file without the generated
marker, the same rule as for stubs.
"""

from pathlib import Path

from pskill_runner import claude_code
from pskill_runner.project import Project
from pskill_runner.skill_model import TOOL_PROFILES, ParallelBlock, SkillCatalog
from pskill_runner.stubs import StubChange, StubError, is_generated


def used_profiles(catalog: SkillCatalog) -> list[str]:
    """The profiles that some parallel block asks for. A computed value can be any profile."""
    values = {
        block.tools
        for skill in catalog.skills.values()
        for block in skill.blocks.values()
        if isinstance(block, ParallelBlock) and block.tools is not None
    }
    if any("{{" in value for value in values):
        return list(TOOL_PROFILES)
    return [profile for profile in TOOL_PROFILES if profile in values]


def wanted_agents(project: Project, catalog: SkillCatalog) -> dict[Path, str]:
    """Agent file path -> its text, for each used profile, when pskill sets up Claude Code."""
    if "claude-code" not in project.config.permissions:
        return {}
    folder = project.root / claude_code.AGENTS_RELATIVE_FOLDER
    return {
        folder / f"pskill-{profile}.md": claude_code.profile_agent_text(profile) for profile in used_profiles(catalog)
    }


def sync_profile_agents(project: Project, catalog: SkillCatalog, check_only: bool) -> list[StubChange]:
    """Bring the profile agents in line with the skills. With check_only, report the changes only."""
    wanted = wanted_agents(project, catalog)
    changes = []
    for path, text in wanted.items():
        if not path.exists():
            changes.append(StubChange(path, "created", path.stem))
        elif not is_generated(path):
            raise StubError(f"{path} is a hand-written file with the name of a pskill profile agent. Rename it.")
        elif path.read_text(encoding="utf-8") != text:
            changes.append(StubChange(path, "updated", path.stem))
    folder = project.root / claude_code.AGENTS_RELATIVE_FOLDER
    for path in sorted(folder.glob("pskill-*.md")):
        if path not in wanted and is_generated(path):
            changes.append(StubChange(path, "deleted", path.stem))
    if not check_only:
        apply_changes(changes, wanted)
    return changes


def apply_changes(changes: list[StubChange], wanted: dict[Path, str]) -> None:
    for change in changes:
        if change.action == "deleted":
            change.path.unlink()
            continue
        change.path.parent.mkdir(parents=True, exist_ok=True)
        change.path.write_text(wanted[change.path], encoding="utf-8", newline="\n")
