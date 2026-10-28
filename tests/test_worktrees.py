"""Tests for pskill_runner.worktrees: a run in its own git worktree, against real git repositories."""

import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from pskill_runner.engine import RunError, start_run
from pskill_runner.project import Config, Project, find_project
from pskill_runner.run_store import new_run_id, utc_now
from pskill_runner.worktrees import check_run_is_here, run_worktree, worktree_mode
from tests.skill_files import PLAN_SKILL, PLAN_SKILL_FILES, write_skill

GIT_IDENTITY = ("-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false")
INPUTS = {"topic": "the login page"}


def git(folder: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(folder), *arguments], capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout.strip()


def write_project(root: Path) -> None:
    write_skill(root / ".pskill" / "skills", "plan-work", PLAN_SKILL, PLAN_SKILL_FILES)
    (root / ".pskill" / ".gitignore").write_text("runs/\n", encoding="utf-8")


def make_checkout(root: Path, project_folder: str = "", commit_the_project: bool = True) -> Project:
    """A git repository with one commit, and the plan-work project in `project_folder` of it."""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    (root / "README.md").write_text("A project.\n", encoding="utf-8")
    if commit_the_project:
        write_project(root / project_folder)
    git(root, "add", ".")
    git(root, *GIT_IDENTITY, "commit", "--quiet", "-m", "First")
    if not commit_the_project:
        write_project(root / project_folder)
    return find_project(root / project_folder)


def with_setup(project: Project, command: list[str]) -> Project:
    return replace(project, config=Config(worktree_setup=command))


def a_run_id() -> str:
    return new_run_id(utc_now())


def remove_line(tree: Path) -> str:
    return f"`git worktree remove --force {tree.as_posix()}`"


# --- worktree_mode ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("flag", "environment", "expected"),
    [
        (True, {}, True),
        (False, {}, False),
        (False, {"PSKILL_RUN_IN_WORKTREE": "true"}, True),
        (False, {"PSKILL_RUN_IN_WORKTREE": "TRUE"}, True),
        (False, {"PSKILL_RUN_IN_WORKTREE": "1"}, True),
        (False, {"PSKILL_RUN_IN_WORKTREE": "0"}, False),
        (False, {"PSKILL_RUN_IN_WORKTREE": "false"}, False),
        (False, {"PSKILL_RUN_IN_WORKTREE": "yes"}, False),
        (False, {"PSKILL_RUN_IN_WORKTREE": ""}, False),
        (True, {"PSKILL_RUN_IN_WORKTREE": "0"}, True),
    ],
)
def test_the_mode_is_on_with_the_flag_or_with_the_variable_set_to_true_or_1(
    flag: bool, environment: dict[str, str], expected: bool
) -> None:
    assert worktree_mode(flag, environment) is expected


# --- run_worktree ----------------------------------------------------------------------------------


def test_a_run_gets_a_detached_worktree_at_head_named_after_the_skill_and_the_run(tmp_path: Path) -> None:
    project = make_checkout(tmp_path)
    run_id = a_run_id()

    run_project, tree = run_worktree(project, "plan-work", INPUTS, run_id)

    assert tree == tmp_path / ".worktrees" / f"plan-work-{run_id}"
    assert run_project.root == tree
    assert (tree / ".pskill" / "skills" / "plan-work" / "skill.yaml").is_file()
    assert git(tree, "rev-parse", "HEAD") == git(tmp_path, "rev-parse", "HEAD")
    assert git(tree, "branch", "--show-current") == ""  # detached: no branch of the checkout moves
    assert git(tmp_path, "branch", "--show-current") != ""


def test_the_worktree_folder_ignores_itself_so_the_checkout_stays_clean(tmp_path: Path) -> None:
    project = make_checkout(tmp_path)

    run_worktree(project, "plan-work", INPUTS, a_run_id())

    assert (tmp_path / ".worktrees" / ".gitignore").read_text(encoding="utf-8") == "*\n"
    assert git(tmp_path, "status", "--porcelain") == ""


def test_a_worktree_folder_that_exists_keeps_its_own_files(tmp_path: Path) -> None:
    project = make_checkout(tmp_path)
    folder = tmp_path / ".worktrees"
    folder.mkdir()
    (folder / ".gitignore").write_text("keep-me\n", encoding="utf-8")

    run_worktree(project, "plan-work", INPUTS, a_run_id())

    assert (folder / ".gitignore").read_text(encoding="utf-8") == "keep-me\n"


def test_the_worktree_goes_to_the_folder_that_the_config_names(tmp_path: Path) -> None:
    project = make_checkout(tmp_path)
    run_id = a_run_id()

    _, tree = run_worktree(replace(project, config=Config(worktree_folder="build/trees")), "plan-work", INPUTS, run_id)

    assert tree == tmp_path / "build" / "trees" / f"plan-work-{run_id}"


def test_no_git_hook_runs_when_the_worktree_is_made(tmp_path: Path) -> None:
    project = make_checkout(tmp_path / "repo")
    marker = tmp_path / "hook-ran"
    hook = tmp_path / "repo" / ".git" / "hooks" / "post-checkout"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(f"#!/bin/sh\necho ran > '{marker.as_posix()}'\n", encoding="utf-8", newline="\n")
    hook.chmod(0o755)

    run_worktree(project, "plan-work", INPUTS, a_run_id())

    assert not marker.exists()


def test_the_setup_command_runs_in_the_new_worktree(tmp_path: Path) -> None:
    command = [sys.executable, "-c", "open('setup-ran.txt', 'w').close()"]
    project = with_setup(make_checkout(tmp_path), command)

    _, tree = run_worktree(project, "plan-work", INPUTS, a_run_id())

    assert tree is not None
    assert (tree / "setup-ran.txt").is_file()
    assert not (tmp_path / "setup-ran.txt").exists()


def test_a_failing_setup_stops_the_start_and_names_the_worktree_to_remove(tmp_path: Path) -> None:
    command = [sys.executable, "-c", "import sys; print('npm ERR! broken', file=sys.stderr); sys.exit(3)"]
    project = with_setup(make_checkout(tmp_path), command)
    run_id = a_run_id()
    tree = tmp_path / ".worktrees" / f"plan-work-{run_id}"

    with pytest.raises(RunError) as error:
        run_worktree(project, "plan-work", INPUTS, run_id)

    message = str(error.value)
    assert "failed with exit code 3" in message
    assert "npm ERR! broken" in message
    assert f"No run started. If the worktree `{tree.as_posix()}` exists, remove it with: {remove_line(tree)}" in message
    assert tree.is_dir()  # the runner never removes a worktree


def test_a_setup_command_that_does_not_exist_stops_the_start(tmp_path: Path) -> None:
    project = with_setup(make_checkout(tmp_path), ["no-such-program-for-pskill-tests"])
    run_id = a_run_id()

    with pytest.raises(RunError, match="did not start") as error:
        run_worktree(project, "plan-work", INPUTS, run_id)

    assert remove_line(tmp_path / ".worktrees" / f"plan-work-{run_id}") in str(error.value)


def test_a_git_error_stops_the_start_and_names_the_worktree(tmp_path: Path) -> None:
    project = make_checkout(tmp_path)
    run_id = a_run_id()
    tree = tmp_path / ".worktrees" / f"plan-work-{run_id}"
    tree.mkdir(parents=True)
    (tree / "in-the-way.txt").write_text("x", encoding="utf-8")

    with pytest.raises(RunError, match="worktree add") as error:
        run_worktree(project, "plan-work", INPUTS, run_id)

    assert remove_line(tree) in str(error.value)


def test_a_project_that_is_not_committed_has_no_project_in_the_worktree(tmp_path: Path) -> None:
    project = make_checkout(tmp_path, commit_the_project=False)
    run_id = a_run_id()

    with pytest.raises(RunError, match=r"has no \.pskill folder.*commit") as error:
        run_worktree(project, "plan-work", INPUTS, run_id)

    assert remove_line(tmp_path / ".worktrees" / f"plan-work-{run_id}") in str(error.value)


def test_a_skill_that_is_not_committed_stops_the_start(tmp_path: Path) -> None:
    project = make_checkout(tmp_path)
    write_skill(
        project.skills_folder, "new-skill", PLAN_SKILL.replace("id: plan-work", "id: new-skill"), PLAN_SKILL_FILES
    )
    run_id = a_run_id()

    with pytest.raises(RunError, match="There is no skill 'new-skill'") as error:
        run_worktree(project, "new-skill", INPUTS, run_id)

    assert remove_line(tmp_path / ".worktrees" / f"new-skill-{run_id}") in str(error.value)


@pytest.mark.parametrize(
    ("skill_id", "inputs", "message"),
    [("nothing-here", INPUTS, "There is no skill 'nothing-here'"), ("plan-work", {}, "The inputs are invalid")],
)
def test_a_wrong_skill_or_input_fails_before_any_worktree_exists(
    tmp_path: Path, skill_id: str, inputs: dict[str, Any], message: str
) -> None:
    project = make_checkout(tmp_path)

    with pytest.raises(RunError, match=message) as error:
        run_worktree(project, skill_id, inputs, a_run_id())

    assert "git worktree" not in str(error.value)
    assert not (tmp_path / ".worktrees").exists()


def test_a_project_in_a_linked_worktree_uses_that_worktree(tmp_path: Path) -> None:
    make_checkout(tmp_path / "repo")
    linked = tmp_path / "linked"
    git(tmp_path / "repo", "worktree", "add", "--quiet", "--detach", str(linked), "HEAD")
    project = find_project(linked)

    assert run_worktree(project, "plan-work", INPUTS, a_run_id()) == (project, None)
    assert not (linked / ".worktrees").exists()


def test_a_project_in_a_subfolder_of_the_checkout_gets_its_worktree_with_the_same_subfolder(tmp_path: Path) -> None:
    project = make_checkout(tmp_path, project_folder="app")
    run_id = a_run_id()

    run_project, tree = run_worktree(project, "plan-work", INPUTS, run_id)

    assert tree == tmp_path / "app" / ".worktrees" / f"plan-work-{run_id}"
    assert run_project.root == tree / "app"


def test_a_folder_outside_git_cannot_run_in_a_worktree(tmp_path: Path) -> None:
    write_project(tmp_path)

    with pytest.raises(RunError, match=r"`git rev-parse .*` failed") as error:
        run_worktree(find_project(tmp_path), "plan-work", INPUTS, a_run_id())

    assert "git worktree remove" not in str(error.value)


def test_a_missing_git_stops_the_start_with_a_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = make_checkout(tmp_path)

    def no_git(*arguments: Any, **options: Any) -> None:
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", no_git)

    with pytest.raises(RunError, match="could not run git"):
        run_worktree(project, "plan-work", INPUTS, a_run_id())


# --- check_run_is_here -----------------------------------------------------------------------------


def start_in_tree(project: Project) -> tuple[str, Path]:
    run_id = a_run_id()
    run_project, tree = run_worktree(project, "plan-work", INPUTS, run_id)
    start_run(run_project, "plan-work", INPUTS, mode="interactive", harness="generic", run_id=run_id, worktree=tree)
    assert tree is not None
    return run_id, run_project.root


def test_a_run_of_another_worktree_names_the_folder_that_holds_it(tmp_path: Path) -> None:
    project = make_checkout(tmp_path, project_folder="app")
    run_id, run_root = start_in_tree(project)

    with pytest.raises(RunError) as error:
        check_run_is_here(project, run_id)

    assert str(error.value) == f"Run {run_id} lives in `{run_root.as_posix()}`: run this command from that folder."


def test_a_run_of_this_project_passes_the_check(tmp_path: Path) -> None:
    project = make_checkout(tmp_path)
    run_id, run_root = start_in_tree(project)

    check_run_is_here(find_project(run_root), run_id)


def test_a_run_that_no_worktree_holds_passes_the_check(tmp_path: Path) -> None:
    project = make_checkout(tmp_path)
    start_in_tree(project)

    check_run_is_here(project, "r-20260101-0000-dead")


def test_outside_git_the_check_passes(tmp_path: Path) -> None:
    write_project(tmp_path)

    check_run_is_here(find_project(tmp_path), "r-20260101-0000-dead")
