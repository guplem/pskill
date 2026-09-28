"""Command-line interface of the runner (SPEC.md section 15).

Exit codes: 0 ok, 1 usage error, 2 validation error, 3 internal error.
"""

import argparse
import os
import sys
import traceback
from pathlib import Path
from typing import Any

from pskill_runner import __version__
from pskill_runner.adapters import AdapterError, detect_harness
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
from pskill_runner.project import Project, ProjectError, find_project
from pskill_runner.run_records import UNFINISHED_STATUSES
from pskill_runner.skill_loader import SkillLoadError, load_skill
from pskill_runner.validator import Problem, validate_skill
from pskill_runner.yaml_loading import load_answer_yaml

EXIT_OK = 0
EXIT_USAGE_ERROR = 1
EXIT_VALIDATION_ERROR = 2
EXIT_INTERNAL_ERROR = 3

USER_ERRORS = (RunError, ProjectError, AnswerInputError, AdapterError)


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
    project = find_project(Path.cwd())
    command = options.command
    if command == "start":
        return print_text(start_command(project, options))
    if command == "current":
        return print_text(current_packet(project, options.run_id))
    if command == "submit":
        return print_text(submit_answer(project, options.run_id, read_answer(sys.stdin)))
    if command == "pause":
        return print_text(pause_run(project, options.run_id))
    if command == "resume":
        return print_text(resume_run(project, options.run_id))
    if command == "cancel":
        return print_text(cancel_run(project, options.run_id))
    if command == "runs":
        return print_text(runs_table(project, only_open=options.open))
    if command == "list":
        return print_text(skills_table(project))
    if command == "validate":
        return validate_command(project, options.skill)
    raise RunError(f"Unknown command {command!r}.")


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
    lines = []
    error_count = warning_count = 0
    for folder in folders:
        for problem in skill_problems(folder):
            lines.append(f"{problem.level:<7}{folder.name}  {problem.location}: {problem.message}")
            error_count += problem.level == "error"
            warning_count += problem.level == "warning"
    noun = "skill" if len(folders) == 1 else "skills"
    lines.append(f"{len(folders)} {noun} checked: {error_count} errors, {warning_count} warnings.")
    print_text("\n".join(lines))
    return EXIT_VALIDATION_ERROR if error_count else EXIT_OK


def skill_problems(folder: Path) -> list[Problem]:
    try:
        skill = load_skill(folder)
    except SkillLoadError as error:
        return [Problem(level="error", location="skill.yaml", message=problem) for problem in error.problems]
    return validate_skill(skill)
