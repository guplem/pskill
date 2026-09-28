"""`pskill sync`: bring the stubs and the harness settings in line with the project (SPEC.md 9.2 and 9.3)."""

from pskill_runner.claude_code import SETTINGS_RELATIVE_PATH, sync_claude_settings
from pskill_runner.codex import HOOKS_RELATIVE_PATH, sync_codex_settings
from pskill_runner.project import Project
from pskill_runner.skill_loader import load_catalog
from pskill_runner.stubs import sync_stubs


def sync_project(project: Project, check_only: bool) -> list[str]:
    """Write (or, with check_only, only list) every change. Return one line per changed file."""
    catalog = load_catalog(project.skills_folder, project.agents_folder)
    verb = "is out of date" if check_only else "was"
    lines = [
        f"{change.path.relative_to(project.root).as_posix()} {verb}{'' if check_only else ' ' + change.action}"
        for change in sync_stubs(project, catalog, check_only)
    ]
    if "claude-code" in project.config.harnesses and sync_claude_settings(project.root, check_only):
        lines.append(f"{SETTINGS_RELATIVE_PATH.as_posix()} {verb}{'' if check_only else ' updated'}")
    if "codex" in project.config.harnesses and sync_codex_settings(project.root, check_only):
        lines.append(
            f"{HOOKS_RELATIVE_PATH.parent.as_posix()}/ (hooks and rules) {verb}{'' if check_only else ' updated'}"
        )
    return lines
