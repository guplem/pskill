"""Worktree runs: a run that works in its own git worktree (SPEC.md section 7.8).

Such a run never switches the branch of the checkout that other agent sessions share. The runner makes the
worktree and never removes it: the run folder, the only record of the run, lives inside it.
"""

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pskill_runner.engine import RunError, startable_skill
from pskill_runner.inline_executor import RealExecutor
from pskill_runner.project import PSKILL_FOLDER_NAME, Config, Project, ProjectError, find_project

WORKTREE_VARIABLE = "PSKILL_RUN_IN_WORKTREE"
SETUP_ERROR_LINES = 20  # the last lines of a failed setup's output that the error shows


def worktree_mode(flag: bool, environment: Mapping[str, str]) -> bool:
    """On with `start --worktree`, else when PSKILL_RUN_IN_WORKTREE is `true` or `1`, in any case."""
    return flag or environment.get(WORKTREE_VARIABLE, "").strip().lower() in ("true", "1")


def run_worktree(
    project: Project, skill_id: str, raw_inputs: dict[str, Any], run_id: str
) -> tuple[Project, Path | None]:
    """The project that a worktree run starts in, and the worktree made for it.

    A project that already sits in a linked worktree uses it: (project, None). Else the runner makes a
    detached worktree at HEAD, named `<skill>-<run>`. A failure after that names the worktree to remove.
    """
    if in_linked_worktree(project.root):
        return project, None
    startable_skill(project, skill_id, raw_inputs)  # a wrong skill id or input fails before any worktree exists
    tree = worktree_folder(project) / f"{skill_id}-{run_id}"
    try:
        add_worktree(project.root, tree)
        tree_project = project_in_worktree(project, tree)
        startable_skill(tree_project, skill_id, raw_inputs)  # the skill as committed: the worktree starts at HEAD
        run_setup(project.config, tree_project.root)
    except (RunError, ProjectError) as error:
        raise RunError(
            f"{error}\nNo run started. If the worktree `{tree.as_posix()}` exists, remove it with: "
            f"`git worktree remove --force {tree.as_posix()}`"
        ) from error
    return tree_project, tree


def in_linked_worktree(root: Path) -> bool:
    """True in a worktree made by `git worktree add`, False in the main checkout.

    Git prints each path absolute or relative to `root` (in a subfolder, `--git-common-dir` prints `../.git`), so
    both resolve from `root`. Not `--path-format=absolute`: git before 2.31 prints that option back and exits 0.
    """
    git_dir = root / git(root, "rev-parse", "--git-dir")
    common_dir = root / git(root, "rev-parse", "--git-common-dir")
    return git_dir.resolve() != common_dir.resolve()


def worktree_folder(project: Project) -> Path:
    """The folder of the worktrees. When this start makes it, it ignores itself, so git status stays clean."""
    folder = project.root / project.config.worktree_folder
    try:
        folder.mkdir(parents=True)
    except OSError as error:
        if folder.is_dir():  # made before: by the user, or by another start at the same moment
            return folder
        raise RunError(f"pskill could not make the worktree folder `{folder.as_posix()}`: {error}") from error
    (folder / ".gitignore").write_text("*\n", encoding="utf-8", newline="\n")
    return folder


def add_worktree(checkout: Path, tree: Path) -> None:
    """A detached worktree at HEAD, with no git hook: a hook would run in a tree with no dependencies yet."""
    git(checkout, "-c", f"core.hooksPath={os.devnull}", "worktree", "add", "--detach", str(tree), "HEAD")


def project_in_worktree(project: Project, tree: Path) -> Project:
    """The project in the worktree, in the same subfolder as in the checkout."""
    root = tree / git(project.root, "rev-parse", "--show-prefix")
    if not (root / PSKILL_FOLDER_NAME).is_dir():  # find_project would walk up to the checkout's own project
        raise RunError(
            f"The worktree has no {PSKILL_FOLDER_NAME} folder at {root.as_posix()}. A worktree starts at the last "
            f"commit: commit {PSKILL_FOLDER_NAME} first."
        )
    return find_project(root)


def run_setup(config: Config, folder: Path) -> None:
    """Run `worktree_setup` in the project folder of the new worktree, like a script block: no shell, same timeout."""
    command = config.worktree_setup
    if not command:
        return
    shown = " ".join(command)
    try:
        result = RealExecutor().run_script("worktree_setup", command, folder, dict(os.environ), config.script_timeout_s)
    except OSError as error:  # RealExecutor turns only a missing command into a problem
        raise RunError(f"The worktree setup `{shown}` did not start: {error}") from error
    if result.problem is not None:
        raise RunError(f"The worktree setup `{shown}` failed: {result.problem}.")
    if result.exit_code != 0:
        failure = f"The worktree setup `{shown}` failed with exit code {result.exit_code}"
        output = (result.stderr.strip() or result.stdout.strip()).splitlines()[-SETUP_ERROR_LINES:]
        raise RunError(f"{failure}:\n" + "\n".join(output) if output else f"{failure}.")


def check_run_is_here(project: Project, run_id: str) -> None:
    """Name the worktree that holds a run that is not in this project.

    No silent redirect: the agent's own file edits must happen in that worktree too. Outside git, or when no
    worktree holds the run, do nothing, so the command gives its own error.
    """
    if (project.runs_folder / run_id / "run.json").is_file():
        return
    try:
        prefix = git(project.root, "rev-parse", "--show-prefix")
        listing = git(project.root, "worktree", "list", "--porcelain")
    except RunError:
        return
    for line in listing.splitlines():
        if not line.startswith("worktree "):
            continue
        root = Path(line.removeprefix("worktree ")) / prefix
        if (root / PSKILL_FOLDER_NAME / "runs" / run_id / "run.json").is_file():
            raise RunError(f"Run {run_id} lives in `{root.as_posix()}`: run this command from that folder.")


def git(folder: Path, *arguments: str) -> str:
    """Run one git command in `folder` and return its output, or raise RunError with git's message."""
    shown = " ".join(["git", *arguments])
    try:
        result = subprocess.run(
            ["git", *arguments], cwd=folder, capture_output=True, text=True, encoding="utf-8", check=False
        )
    except OSError as error:
        raise RunError(f"pskill could not run git: {error}") from error
    if result.returncode != 0:
        raise RunError(f"`{shown}` failed: {result.stderr.strip()}")
    return result.stdout.strip()
