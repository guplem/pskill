"""`pskill test`: run a skill's test cases with a scripted fake agent (SPEC.md section 12).

A case file `tests/<case>.yaml` gives the inputs, the agent's answers, the recorded script results,
the recorded child results (each can name the inputs that its call must send), and the expected path, status, and
outputs. No harness and no LLM take part. Scripts and child skills never run for real.
"""

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from pskill_runner.engine import read_run_info, read_run_state, start_run, submit_answer
from pskill_runner.inline_executor import CallResult, ScriptResult
from pskill_runner.project import Project
from pskill_runner.run_records import ACTIVE_STATUSES
from pskill_runner.run_store import read_events
from pskill_runner.yaml_loading import load_answer_yaml, load_skill_yaml

CASE_KEYS = ("answers", "calls", "expect", "inputs", "mode", "name", "scripts")
MAX_SUBMISSIONS = 1000


class SkillTestError(Exception):
    """The case cannot go on (a missing answer or recorded result, or a malformed case file)."""


@dataclass(frozen=True)
class SkillTestResult:
    skill_id: str
    case: str
    passed: bool
    problem: str | None


class RecordedExecutor:
    """Gives recorded script and call results, in order, instead of running anything."""

    def __init__(self, scripts: dict[str, list[dict[str, Any]]], calls: dict[str, list[dict[str, Any]]]) -> None:
        self.scripts = {block_id: list(results) for block_id, results in scripts.items()}
        self.calls = {block_id: list(results) for block_id, results in calls.items()}
        self.call_visits: dict[str, int] = {}

    def run_script(
        self,
        block_id: str,
        argv: list[str],
        cwd: Path,
        env: dict[str, str],
        timeout_s: int,
        stdin_text: str | None = None,
    ) -> ScriptResult:
        results = self.scripts.get(block_id)
        if not results:
            raise SkillTestError(f"the script block {block_id!r} ran, but the case has no recorded result for it")
        recorded = results.pop(0)
        return ScriptResult(
            exit_code=int(recorded.get("exit_code", 0)),
            stdout=str(recorded.get("stdout", "")),
            stderr=str(recorded.get("stderr", "")),
            duration_ms=0,
        )

    def call_result(self, block_id: str, skill_id: str, inputs: dict[str, Any]) -> CallResult | None:
        results = self.calls.get(block_id)
        if not results:
            raise SkillTestError(f"the call block {block_id!r} ran, but the case has no recorded result for it")
        recorded = results.pop(0)
        self.call_visits[block_id] = self.call_visits.get(block_id, 0) + 1
        check_call_inputs(block_id, self.call_visits[block_id], recorded.get("inputs", {}), inputs)
        return CallResult(status=str(recorded.get("status", "succeeded")), outputs=dict(recorded.get("outputs", {})))


def check_call_inputs(block_id: str, visit: int, expected: Any, actual: dict[str, Any]) -> None:
    """Fail the case when the call block sent another value for an input that the recorded call names."""
    if not isinstance(expected, dict):
        raise SkillTestError(
            f"the recorded call {block_id!r} on visit {visit} has inputs that are not a mapping, such as {{pr: 9}}"
        )
    for name, expected_value in expected.items():
        if name not in actual:
            raise SkillTestError(
                f"the call block {block_id!r} did not send the input {name!r} on visit {visit}, "
                f"but the case expects {expected_value!r}"
            )
        if actual[name] != expected_value:
            raise SkillTestError(
                f"the call block {block_id!r} sent the input {name!r} = {actual[name]!r} on visit {visit}, "
                f"but the case expects {expected_value!r}"
            )


def run_skill_tests(project: Project, skill_id: str) -> list[SkillTestResult]:
    """Run every case in `.pskill/skills/<skill_id>/tests/`, in file name order."""
    tests_folder = project.skills_folder / skill_id / "tests"
    if not tests_folder.is_dir():
        return []
    return [run_case_file(project, skill_id, path) for path in sorted(tests_folder.glob("*.yaml"))]


def run_case_file(project: Project, skill_id: str, path: Path) -> SkillTestResult:
    name = path.stem
    try:
        case = read_case_file(path)
        name = str(case.get("name", path.stem))
        problem = run_case(project, skill_id, case)
    except SkillTestError as error:
        problem = str(error)
    return SkillTestResult(skill_id=skill_id, case=name, passed=problem is None, problem=problem)


def read_case_file(path: Path) -> dict[str, Any]:
    try:
        case = load_skill_yaml(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        raise SkillTestError(f"the case file is not valid YAML: {error}{quoting_hint(path, error)}") from error
    check_case_keys(case)
    return dict(case)


def quoting_hint(path: Path, error: yaml.YAMLError) -> str:
    """A hint for the common trap: a plain value with '?' inside { } (a YAML flow mapping)."""
    mark = getattr(error, "problem_mark", None)
    lines = path.read_text(encoding="utf-8").splitlines()
    if mark is None or mark.line >= len(lines):
        return ""
    line = lines[mark.line]
    if line[mark.column : mark.column + 1] != "?" or "{" not in line[: mark.column]:
        return ""
    start = max(line.rfind(",", 0, mark.column), line.rfind("{", 0, mark.column)) + 1
    end_candidates = [index for index in (line.find(",", mark.column), line.find("}", mark.column)) if index >= 0]
    pair = line[start : min(end_candidates, default=len(line))].strip()
    key, _, value = pair.partition(": ")
    return f"\nHint: put a value with '?' or ': ' inside {{ }} in quotes, such as {key}: \"{value}\"."


def check_case_keys(case: Any) -> None:
    if not isinstance(case, dict):
        raise SkillTestError("the case file must be a mapping, such as 'name: my case'")
    for key in case:
        if key not in CASE_KEYS:
            raise SkillTestError(f"the case file has an unknown key {key!r} (known keys: {', '.join(CASE_KEYS)})")


def as_text_values(values: dict[str, Any]) -> dict[str, Any]:
    """Turn typed YAML values into text, the way the agent's answers and CLI inputs arrive."""
    return dict(load_answer_yaml(yaml.safe_dump(values, allow_unicode=True)) or {})


def run_case(project: Project, skill_id: str, case: dict[str, Any]) -> str | None:
    """Run one case. Return the first problem, or None when it passes."""
    answers: dict[str, list[Any]] = {block_id: list(queue) for block_id, queue in case.get("answers", {}).items()}
    executor = RecordedExecutor(case.get("scripts", {}), case.get("calls", {}))
    with tempfile.TemporaryDirectory(prefix="pskill-test-") as temp_folder:
        runs_folder = Path(temp_folder)
        run_id, _ = start_run(
            project,
            skill_id,
            as_text_values(case.get("inputs", {})),
            mode=case.get("mode", "interactive"),
            harness="generic",
            executor=executor,
            runs_folder=runs_folder,
            allow_internal=True,
        )
        for _ in range(MAX_SUBMISSIONS):
            info = read_run_info(project, run_id, runs_folder)
            if info["status"] not in ACTIVE_STATUSES:
                break
            block_id = info["current_block"] or ""
            queue = answers.get(block_id)
            if not queue:
                raise SkillTestError(
                    f"the block {block_id!r} asked for an answer, but the case has no more answers for it"
                )
            answer_text = yaml.safe_dump(queue.pop(0), allow_unicode=True, sort_keys=False)
            submit_answer(project, run_id, answer_text, open_task(project, run_id, runs_folder), executor, runs_folder)
        info = read_run_info(project, run_id, runs_folder)
        path = run_path(runs_folder / run_id, skill_id)
    return expectation_problem(case.get("expect", {}), path, info["status"], info["outputs"] or {})


def open_task(project: Project, run_id: str, runs_folder: Path) -> int | None:
    """The first open task of the current parallel block, or None for other blocks."""
    tasks = read_run_state(project, run_id, runs_folder)["frames"][-1]["tasks"]
    if not tasks:
        return None
    return next(index for index, task in enumerate(tasks) if task["output"] is None)


def run_path(run_folder: Path, skill_id: str) -> list[str]:
    """The blocks that the root skill entered, in order. A parallel block counts once."""
    return [
        event["block"]
        for event in read_events(run_folder)
        if event["type"] == "block_started" and event["frame"] == skill_id and event.get("task") in (None, 0)
    ]


def expectation_problem(expect: dict[str, Any], path: list[str], status: str, outputs: dict[str, Any]) -> str | None:
    if "path" in expect and list(expect["path"]) != path:
        return f"path: expected {bracketed(expect['path'])}, got {bracketed(path)}"
    if "path_contains" in expect and not is_subsequence(list(expect["path_contains"]), path):
        return f"path_contains: {bracketed(expect['path_contains'])} is not in order in the path {bracketed(path)}"
    if "status" in expect and expect["status"] != status:
        return f"status: expected {expect['status']}, got {status}"
    for name, expected in expect.get("outputs", {}).items():
        if outputs.get(name) != expected:
            return f"outputs.{name}: expected {expected!r}, got {outputs.get(name)!r}"
    return None


def is_subsequence(wanted: list[str], path: list[str]) -> bool:
    remaining = iter(path)
    return all(block_id in remaining for block_id in wanted)


def bracketed(block_ids: list[str]) -> str:
    return "[" + ", ".join(block_ids) + "]"
