"""`pskill sync`: bring the stubs and the harness settings in line with the project (SPEC.md 9.2 and 9.3)."""

import subprocess

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


def sync_with_the_vendored_runner(project: Project) -> tuple[list[str], bool]:
    """Run `sync` in a new process, with the runner in `.pskill/`. Return its lines, and whether it worked.

    `update` needs this: it replaces the runner files, but its own process still runs the old code.
    `uv run` also installs the dependencies that the new version declares.
    """
    entry_script = project.pskill_folder / "pskill.py"
    result = subprocess.run(
        ["uv", "run", str(entry_script), "sync"],
        cwd=project.root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    lines = [line for line in result.stdout.splitlines() if line and line != "Everything is up to date."]
    if result.returncode != 0:
        lines.append(f"The sync after the update failed. Run `uv run .pskill/pskill.py sync`. {result.stderr.strip()}")
    return lines, result.returncode == 0
