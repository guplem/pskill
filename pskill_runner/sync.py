"""`pskill sync`: bring the stubs and the app settings in line with the project (SPEC.md 9.2 and 9.3)."""

import subprocess
from typing import Any

from pskill_runner import claude_code, codex
from pskill_runner.hook_settings import SHARED_HOOKS, remove_pskill_hooks, sync_hook_file
from pskill_runner.project import Project
from pskill_runner.skill_loader import load_catalog
from pskill_runner.stubs import sync_stubs

# Each app's own hooks file gets that app's own commands. Any other file gets the shared commands.
APP_HOOKS: dict[str, dict[str, dict[str, Any]]] = {
    claude_code.SETTINGS_RELATIVE_PATH.as_posix(): claude_code.PSKILL_HOOKS,
    codex.HOOKS_RELATIVE_PATH.as_posix(): codex.PSKILL_HOOKS,
}


def sync_project(project: Project, check_only: bool) -> list[str]:
    """Write (or, with check_only, only list) every change. Return one line per changed file."""
    catalog = load_catalog(project.skills_folder, project.agents_folder)
    verb = "is out of date" if check_only else "was"
    lines = [
        f"{change.path.relative_to(project.root).as_posix()} {verb}{'' if check_only else ' ' + change.action}"
        for change in sync_stubs(project, catalog, check_only)
    ]
    changed_files = hook_file_changes(project, check_only) + permission_changes(project, check_only)
    lines += [f"{path} {verb}{'' if check_only else ' updated'}" for path in dict.fromkeys(changed_files)]
    return lines


def hook_file_changes(project: Project, check_only: bool) -> list[str]:
    """Put the hooks into every file in `hook_files`, and take them out of the app files that are not listed."""
    changed = []
    for relative_path in project.config.hook_files:
        hooks = APP_HOOKS.get(relative_path, SHARED_HOOKS)
        if sync_hook_file(project.root / relative_path, hooks, check_only):
            changed.append(relative_path)
    for relative_path in APP_HOOKS:
        if relative_path not in project.config.hook_files and remove_pskill_hooks(
            project.root / relative_path, check_only
        ):
            changed.append(relative_path)
    return changed


def permission_changes(project: Project, check_only: bool) -> list[str]:
    """Write the rule that lets each app in `permissions` run pskill without asking."""
    changed = []
    if "claude-code" in project.config.permissions and claude_code.sync_claude_permission(project.root, check_only):
        changed.append(claude_code.SETTINGS_RELATIVE_PATH.as_posix())
    if "codex" in project.config.permissions and codex.sync_codex_rules(project.root, check_only):
        changed.append(codex.RULES_RELATIVE_PATH.as_posix())
    return changed


def sync_with_the_installed_runner(project: Project) -> tuple[list[str], bool]:
    """Run `sync` in a new process, with the runner that `.pskill/pskill.py` pins.

    Return its lines, and whether it worked.

    `update` needs this: it moves the pin, but its own process still runs the old code.
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
