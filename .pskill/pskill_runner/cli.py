"""Command-line interface of the runner (SPEC.md section 15).

Exit codes: 0 ok, 1 usage error, 2 validation error, 3 internal error.
"""

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

import pskill_runner
from pskill_runner import __version__, claude_code, codex
from pskill_runner.adapters import GENERIC, AdapterError, detect_harness, detect_hook_harness
from pskill_runner.answer_input import AnswerInputError, read_answer
from pskill_runner.engine import (
    RunError,
    cancel_run,
    current_packet,
    list_runs,
    pause_run,
    resume_run,
    start_run,
    submit_answer,
)
from pskill_runner.hook_settings import SettingsError
from pskill_runner.hooks import session_start_text, stop_hook_reason
from pskill_runner.project import Project, ProjectError, find_project
from pskill_runner.release import is_archive_source, release_url, unpack_archive
from pskill_runner.run_records import UNFINISHED_STATUSES
from pskill_runner.skill_loader import SkillLoadError, load_catalog, load_skill
from pskill_runner.skill_model import SkillCatalog
from pskill_runner.skill_tests import run_skill_tests
from pskill_runner.stubs import StubError, sync_stubs
from pskill_runner.sync import sync_project, sync_with_the_vendored_runner
from pskill_runner.validator import Problem, validate_skill
from pskill_runner.vendoring import VendoringError, init_project, update_project
from pskill_runner.viewer_server import serve_viewer
from pskill_runner.yaml_loading import load_answer_yaml

EXIT_OK = 0
EXIT_USAGE_ERROR = 1
EXIT_VALIDATION_ERROR = 2
EXIT_INTERNAL_ERROR = 3

USER_ERRORS = (RunError, ProjectError, AnswerInputError, AdapterError, VendoringError, SettingsError, StubError)
HOOK_INPUT_TIMEOUT_S = 2.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pskill", description="Run programmatic skills one block at a time.")
    parser.add_argument("--version", action="version", version=f"pskill {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="<command>")

    start = commands.add_parser("start", help="Start a run of a skill and print its first block.")
    start.add_argument("skill", help="The skill id.")
    start.add_argument("--input", action="append", default=[], metavar="NAME=VALUE", help="One input value.")
    start.add_argument("--inputs", choices=["-"], help="Read the inputs as YAML from stdin.")
    start.add_argument("--mode", choices=["interactive", "autonomous"], help="Default: from config.yaml.")
    start.add_argument("--harness", default="auto", help="The harness that runs the agent. Default: detect it.")

    current = commands.add_parser("current", help="Print the current block of a run again.")
    current.add_argument("run_id", nargs="?", help="Default: the newest unfinished run.")

    submit = commands.add_parser("submit", help="Send the answer (YAML on stdin) and print the next block.")
    submit.add_argument("run_id")
    submit.add_argument("--task", type=int, help="The task number, for a block with several tasks.")

    for name, help_text in (
        ("pause", "Pause a run."),
        ("resume", "Resume a paused run and retry its block."),
        ("cancel", "Stop a run for good."),
    ):
        commands.add_parser(name, help=help_text).add_argument("run_id")

    runs = commands.add_parser("runs", help="List the runs, newest first.")
    runs.add_argument("--open", action="store_true", help="Only unfinished runs.")

    commands.add_parser("list", help="List the skills.")

    validate = commands.add_parser("validate", help="Check the skills for errors and warnings.")
    validate.add_argument("skill", nargs="?", help="Default: every skill.")

    test = commands.add_parser("test", help="Run the skills' test cases with a scripted fake agent.")
    test.add_argument("skill", nargs="?", help="Default: every skill.")

    sync = commands.add_parser("sync", help="Write the skill stubs and the harness hooks and permission rule.")
    sync.add_argument("--check", action="store_true", help="Only report what is out of date.")

    init = commands.add_parser("init", help="Create .pskill/ in the current folder and vendor the runner.")
    init.add_argument(
        "--from", dest="source", help="A pskill checkout, a .pskill folder, or a release .zip (file or URL)."
    )

    update = commands.add_parser("update", help="Replace the vendored runner with another version.")
    update.add_argument(
        "--from", dest="source", help="A pskill checkout, a .pskill folder, or a release .zip. Default: latest release."
    )
    update.add_argument("--force", action="store_true", help="Overwrite vendored files that were edited by hand.")

    view = commands.add_parser("view", help="Open the viewer (runs and skills) in the browser.")
    view.add_argument("--port", type=int, help="Default: viewer_port from config.yaml. 0 picks a free port.")
    view.add_argument("--no-open", action="store_true", help="Do not open the browser.")

    hook = commands.add_parser("hook", help="Internal: the harness calls this from its hooks.")
    hook.add_argument("event", choices=["stop", "session-start"])
    hook.add_argument("--harness", required=True, help="The app that runs the hook, or auto to detect it.")
    return parser


def main(arguments: list[str] | None = None) -> int:
    use_utf8_streams()
    parser = build_parser()
    options = parser.parse_args(arguments)
    if options.command is None:
        parser.print_help()
        return EXIT_USAGE_ERROR
    try:
        return run_command(options)
    except USER_ERRORS as error:
        print(f"pskill: {error}", file=sys.stderr)
        return EXIT_USAGE_ERROR
    except Exception:
        print("pskill: internal error. Please report it with the text below.", file=sys.stderr)
        traceback.print_exc()
        return EXIT_INTERNAL_ERROR


def use_utf8_streams() -> None:
    """Packets contain non-ASCII text. Windows consoles and pipes may default to another encoding."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def run_command(options: argparse.Namespace) -> int:
    command = options.command
    if command == "hook":
        return hook_command(options.event, options.harness)
    if command == "init":
        return init_command(options.source)
    project = find_project(Path.cwd())
    harness = specific_harness()
    if command == "start":
        return print_text(start_command(project, options))
    if command == "current":
        return print_text(current_packet(project, options.run_id, harness))
    if command == "submit":
        return print_text(submit_answer(project, options.run_id, read_answer(sys.stdin), options.task, harness=harness))
    if command == "pause":
        return print_text(pause_run(project, options.run_id))
    if command == "resume":
        return print_text(resume_run(project, options.run_id, harness))
    if command == "cancel":
        return print_text(cancel_run(project, options.run_id))
    if command == "runs":
        return print_text(runs_table(project, only_open=options.open))
    if command == "list":
        return print_text(skills_table(project))
    if command == "validate":
        return validate_command(project, options.skill)
    if command == "test":
        return test_command(project, options.skill)
    if command == "sync":
        return sync_command(project, options.check)
    if command == "update":
        return update_command(project, options.source, options.force)
    if command == "view":
        port = project.config.viewer_port if options.port is None else options.port
        serve_viewer(project, running_copy_root() / "viewer", port, open_browser=not options.no_open)
        return EXIT_OK
    raise RunError(f"Unknown command {command!r}.")


def specific_harness() -> str | None:
    """The detected harness, or None when detection finds only `generic`.

    None keeps the harness that the run already records, so a command from an unknown shell never
    turns a Claude Code run into a generic one.
    """
    harness = detect_harness(os.environ)
    return None if harness == GENERIC.name else harness


def print_text(text: str) -> int:
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return EXIT_OK


def start_command(project: Project, options: argparse.Namespace) -> str:
    inputs: dict[str, Any] = {}
    if options.inputs == "-":
        stdin_inputs = load_answer_yaml(read_answer(sys.stdin))
        if not isinstance(stdin_inputs, dict):
            raise RunError("The inputs on stdin must be 'name: value' lines.")
        inputs.update(stdin_inputs)
    for pair in options.input:
        name, separator, value = pair.partition("=")
        if not separator:
            raise RunError(f"--input {pair!r} must look like NAME=VALUE.")
        inputs[name] = value
    harness = detect_harness(os.environ) if options.harness == "auto" else options.harness
    mode = options.mode or project.config.default_mode
    _, packet = start_run(project, options.skill, inputs, mode=mode, harness=harness)
    return packet


def runs_table(project: Project, only_open: bool) -> str:
    runs = [info for info in list_runs(project) if not only_open or info["status"] in UNFINISHED_STATUSES]
    if not runs:
        return "No runs."
    rows = [
        f"{info['run_id']}  {info['skill_id']}  {info['status']}  {info['current_block'] or '-'}  {info['updated_at']}"
        for info in runs
    ]
    return "\n".join(["run  skill  status  block  updated", *rows])


def skill_folders(project: Project, skill_id: str | None = None) -> list[Path]:
    if skill_id is not None:
        folder = project.skills_folder / skill_id
        if not (folder / "skill.yaml").is_file():
            raise RunError(f"There is no skill {skill_id!r}.")
        return [folder]
    if not project.skills_folder.is_dir():
        return []
    return sorted(folder for folder in project.skills_folder.iterdir() if (folder / "skill.yaml").is_file())


def skills_table(project: Project) -> str:
    rows = []
    for folder in skill_folders(project):
        try:
            skill = load_skill(folder)
        except SkillLoadError:
            rows.append(f"{folder.name}  (invalid: run `pskill validate {folder.name}`)")
            continue
        rows.append(f"{skill.id}  {skill.invocation}  {skill.description.strip()}")
    return "\n".join(rows) if rows else "No skills in .pskill/skills/."


def validate_command(project: Project, skill_id: str | None) -> int:
    folders = skill_folders(project, skill_id)
    catalog = load_catalog(project.skills_folder, project.agents_folder)
    lines = []
    error_count = warning_count = 0
    for folder in folders:
        for problem in skill_problems(folder, catalog):
            lines.append(f"{problem.level:<7}{folder.name}  {problem.location}: {problem.message}")
            error_count += problem.level == "error"
            warning_count += problem.level == "warning"
    if skill_id is None:
        for change in sync_stubs(project, catalog, check_only=True):
            lines.append(
                f"error  (stubs)  {change.path.relative_to(project.root).as_posix()} is out of date: run `pskill sync`"
            )
            error_count += 1
    noun = "skill" if len(folders) == 1 else "skills"
    lines.append(f"{len(folders)} {noun} checked: {error_count} errors, {warning_count} warnings.")
    print_text("\n".join(lines))
    return EXIT_VALIDATION_ERROR if error_count else EXIT_OK


def skill_problems(folder: Path, catalog: SkillCatalog) -> list[Problem]:
    try:
        skill = load_skill(folder)
    except SkillLoadError as error:
        return [Problem(level="error", location="skill.yaml", message=problem) for problem in error.problems]
    return validate_skill(skill, catalog)


def test_command(project: Project, skill_id: str | None) -> int:
    """Run the test cases, one line per case. Exit code 2 when any case fails."""
    lines = []
    passed = failed = 0
    for folder in skill_folders(project, skill_id):
        for result in run_skill_tests(project, folder.name):
            if result.passed:
                passed += 1
                lines.append(f"PASS  {result.skill_id}  {result.case}")
            else:
                failed += 1
                lines.append(f"FAIL  {result.skill_id}  {result.case}: {result.problem}")
    total = passed + failed
    noun = "case" if total == 1 else "cases"
    lines.append(f"{total} {noun} run: {passed} passed, {failed} failed.")
    print_text("\n".join(lines))
    return EXIT_VALIDATION_ERROR if failed else EXIT_OK


def sync_command(project: Project, check_only: bool) -> int:
    lines = sync_project(project, check_only)
    if not lines:
        return print_text("Everything is up to date.")
    print_text("\n".join(lines))
    return EXIT_VALIDATION_ERROR if check_only else EXIT_OK


def running_copy_root() -> Path:
    """The folder of the runner that runs this command: a pskill checkout or a project's .pskill/."""
    return Path(pskill_runner.__file__).resolve().parent.parent


def source_folder(source: str) -> Path:
    """A folder with the vendored files: the given folder, or an unpacked release archive."""
    return unpack_archive(source) if is_archive_source(source) else Path(source).resolve()


def init_command(source: str | None) -> int:
    project_root = Path.cwd()
    lines = init_project(project_root, source_folder(source) if source else running_copy_root())
    lines += sync_project(find_project(project_root), check_only=False)
    lines.append("Next: add a skill in .pskill/skills/<id>/, then run `uv run .pskill/pskill.py sync`.")
    return print_text("\n".join(lines))


def update_command(project: Project, source: str | None, force: bool) -> int:
    lines = update_project(project.root, source_folder(source or release_url()), force)
    sync_lines, synced = sync_with_the_vendored_runner(project)
    print_text("\n".join(lines + sync_lines))
    return EXIT_OK if synced else EXIT_INTERNAL_ERROR


def hook_command(event: str, harness: str) -> int:
    """Answer a harness hook. A hook must never break the harness, so every failure ends quietly."""
    try:
        hook_input = read_hook_input()
        project = find_project(Path(str(hook_input.get("cwd") or Path.cwd())))
        if event == "stop":
            if harness == "auto":
                harness = detect_hook_harness(os.environ, hook_input)
            stdout, exit_code = stop_hook_output(project, harness)
            sys.stdout.write(stdout)
            return exit_code
        sys.stdout.write(session_start_text(project))
    except Exception as error:  # a hook must never fail the harness
        print(f"pskill hook {event}: {error}", file=sys.stderr)
    return EXIT_OK


def read_hook_input() -> dict[str, Any]:
    try:
        text = read_answer(sys.stdin, timeout_s=HOOK_INPUT_TIMEOUT_S)
    except AnswerInputError:
        return {}
    parsed = json.loads(text)
    return parsed if isinstance(parsed, dict) else {}


def stop_hook_output(project: Project, harness: str) -> tuple[str, int]:
    reason = stop_hook_reason(project, harness)
    if harness == "claude-code":
        return claude_code.stop_response(reason)
    if harness == "codex":
        return codex.stop_response(reason)
    return ("" if reason is None else reason + "\n"), EXIT_OK
