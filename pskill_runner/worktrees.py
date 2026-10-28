"""Worktree runs: a run that works in its own git worktree (SPEC.md section 7.8).

Such a run never switches the branch of the checkout that other agent sessions share. The runner makes the
worktree and never removes the worktree of a run: the run folder, the only record of the run, lives inside it.
Only a start that fails before its run exists removes its worktree.
"""

import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pskill_runner.engine import RunError, list_runs, startable_skill
from pskill_runner.galtea import KEY_FILE_NAME as GALTEA_KEY_FILE
from pskill_runner.inline_executor import RealExecutor
from pskill_runner.project import PSKILL_FOLDER_NAME, Config, Project, ProjectError, find_project
from pskill_runner.run_records import UNFINISHED_STATUSES, RunInfo

WORKTREE_VARIABLE = "PSKILL_RUN_IN_WORKTREE"
SETUP_ERROR_LINES = 20  # the last lines of a failed setup's output that the error shows
REMOVED_NOTE = "No run started. pskill removed the worktree that it made for it."
UNCOMMITTED_NOTE = (
    f"The checkout has uncommitted changes in `{PSKILL_FOLDER_NAME}/`. This run does not use them: its worktree "
    "starts at the last commit. Tell the user."
)


def worktree_mode(flag: bool, environment: Mapping[str, str]) -> bool:
    """On with `start --worktree`, else when PSKILL_RUN_IN_WORKTREE is `true` or `1`, in any case."""
    return flag or environment.get(WORKTREE_VARIABLE, "").strip().lower() in ("true", "1")


def run_worktree(
    project: Project, skill_id: str, raw_inputs: dict[str, Any], run_id: str
) -> tuple[Project, Path | None, str]:
    """The project that a worktree run starts in, the worktree made for it, and a note for the first packet.

    A project that already sits in a linked worktree uses it: (project, None, ""). Else the runner makes a
    detached worktree at HEAD, named `<skill>-<run>`, and copies the checkout's Galtea key file, which git ignores.
    A failure after that removes the worktree: no run lives in it yet. The note says when the checkout's
    `.pskill/` has uncommitted changes, which the worktree does not have.
    """
    try:
        linked = in_linked_worktree(project.root)
    except RunError as error:
        raise RunError(
            f"A worktree run needs git: {error}\nWorktree runs are on through `start --worktree` or "
            f"{WORKTREE_VARIABLE}. With neither, the run works in this folder."
        ) from error
    if linked:
        return project, None, ""
    startable_skill(project, skill_id, raw_inputs)  # a wrong skill id or input fails before any worktree exists
    changes = git(project.root, "status", "--porcelain", "--", PSKILL_FOLDER_NAME)
    tree = worktree_folder(project) / f"{skill_id}-{run_id}"
    try:
        add_worktree(project.root, tree)
        tree_project = project_in_worktree(project, tree)
        startable_skill(tree_project, skill_id, raw_inputs)  # the skill as committed: the worktree starts at HEAD
        copy_galtea_key(project, tree_project)
        run_setup(project.config, tree_project.root)
    except (RunError, ProjectError) as error:
        raise RunError(f"{error}\n{remove_failed_worktree(project.root, tree)}") from error
    return tree_project, tree, UNCOMMITTED_NOTE if changes else ""


def remove_failed_worktree(checkout: Path, tree: Path) -> str:
    """Remove the worktree of a start that failed, and return the last line of its error.

    No run lives in it yet, so nothing is lost. Git refuses a folder that is not a worktree (one that was in the
    way of `worktree add`): the line then names the command, and the folder stays.
    """
    try:
        git(checkout, "worktree", "remove", "--force", str(tree))
    except RunError:
        return (
            f"No run started. If the worktree `{tree.as_posix()}` is yours to drop, remove it with: "
            f'`git worktree remove --force "{tree.as_posix()}"`'
        )
    return REMOVED_NOTE


def copy_galtea_key(project: Project, tree_project: Project) -> None:
    """Copy `.pskill/galtea.env` into the worktree: git ignores it, so `worktree add` leaves it out."""
    key_file = project.pskill_folder / GALTEA_KEY_FILE
    if key_file.is_file():
        shutil.copyfile(key_file, tree_project.pskill_folder / GALTEA_KEY_FILE)


def in_linked_worktree(root: Path) -> bool:
    """True in a worktree made by `git worktree add`, False in the main checkout.

    Git prints each path absolute or relative to `root` (in a subfolder, `--git-common-dir` prints `../.git`), so
    both resolve from `root`. Not `--path-format=absolute`: git before 2.31 prints that option back and exits 0.
    """
    git_dir = root / git(root, "rev-parse", "--git-dir")
    common_dir = root / git(root, "rev-parse", "--git-common-dir")
    return git_dir.resolve() != common_dir.resolve()


def worktree_folder(project: Project) -> Path:
    """The folder of the worktrees. It ignores itself, so git status stays clean.

    The `.gitignore` is written whenever it is missing: a folder made by hand, or cleaned by `git clean -fdx`,
    would else show the worktrees as uncommitted changes. A `.gitignore` that exists is kept.
    """
    folder = project.root / project.config.worktree_folder
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise RunError(f"pskill could not make the worktree folder `{folder.as_posix()}`: {error}") from error
    ignore_file = folder / ".gitignore"
    if not ignore_file.exists():
        try:
            ignore_file.write_text("*\n", encoding="utf-8", newline="\n")
        except OSError as error:
            raise RunError(f"pskill could not write `{ignore_file.as_posix()}`: {error}") from error
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
        last_lines = (result.stderr.strip() or result.stdout.strip()).splitlines()[-SETUP_ERROR_LINES:]
        output = "\n".join(last_lines)
        raise RunError(f"{failure}:\n{output}" if output else f"{failure}.")


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


def worktree_projects(project: Project) -> list[Project]:
    """The projects in the worktrees of `project.config.worktree_folder`, for the Stop hook of the checkout.

    Git runs only when that folder exists, so a project with no worktree run pays nothing. A worktree whose
    project does not load (a broken config.yaml) is left out: it must not break the hook.
    """
    folder = project.root / project.config.worktree_folder
    if not folder.is_dir():
        return []
    try:
        prefix = git(project.root, "rev-parse", "--show-prefix")
    except RunError:
        return []
    projects: list[Project] = []
    for tree in sorted(folder.iterdir()):
        root = tree / prefix
        if not (root / PSKILL_FOLDER_NAME).is_dir():  # the folder's .gitignore, or a worktree being made
            continue
        try:
            projects.append(find_project(root))
        except ProjectError:
            continue
    return projects


def worktree_runs(project: Project) -> list[tuple[Project, RunInfo]]:
    """The runs in the worktrees of the project, each with the project in its worktree, newest first."""
    runs = [(tree_project, info) for tree_project in worktree_projects(project) for info in list_runs(tree_project)]
    return sorted(runs, key=lambda pair: pair[1]["updated_at"], reverse=True)


def check_newest_run_is_here(project: Project) -> None:
    """With no unfinished run here, name the worktree of the newest unfinished worktree run, if any.

    For `current` with no run id: else it says that there is no unfinished run, and the agent stops looking.
    """
    if any(info["status"] in UNFINISHED_STATUSES for info in list_runs(project)):
        return
    for tree_project, info in worktree_runs(project):
        if info["status"] in UNFINISHED_STATUSES:
            raise RunError(
                f"There is no unfinished run here. Run {info['run_id']} lives in `{tree_project.root.as_posix()}`: "
                "run this command from that folder."
            )


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
