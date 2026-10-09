"""The engine: runs a skill one block at a time (SPEC.md sections 4, 6, and 7).

The public functions (`start_run`, `submit_answer`, ...) each load a run from disk, change it,
save it, and return the text to print. A `Run` object lives only for one command. Commands that
change a run hold the run's lock, because parallel subagents submit at the same time.
"""

import contextlib
import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pskill_runner
from pskill_runner.adapters import adapter_for
from pskill_runner.computed_values import ComputedValueError, compute, is_true, render_text
from pskill_runner.field_types import FieldMap, FieldSpec, check_answer, check_typed_values
from pskill_runner.inline_executor import InlineExecutor, RealExecutor, ScriptResult
from pskill_runner.packets import (
    VISIT_CAP_CHOICES,
    VISIT_CAP_ROUNDS,
    AgentPacket,
    TaskPrompt,
    render_agent_packet,
    render_final_packet,
    render_parallel_packet,
    render_pause_packet,
    task_prompt_text,
    visit_cap_instruction,
)
from pskill_runner.project import Project
from pskill_runner.run_records import (
    ACTIVE_STATUSES,
    SCHEMA_VERSION,
    UNFINISHED_STATUSES,
    Frame,
    ParallelTask,
    RunInfo,
    RunState,
    SkippedTask,
    new_frame,
)
from pskill_runner.run_store import (
    append_event,
    copy_skill_snapshot,
    folder_hash,
    new_run_id,
    parse_timestamp,
    read_json,
    run_lock,
    timestamp,
    utc_now,
    write_json_atomic,
)
from pskill_runner.shells import detect_shell
from pskill_runner.skill_loader import SkillLoadError, load_catalog, load_skill
from pskill_runner.skill_model import (
    AgentBlock,
    AnyBlock,
    CallBlock,
    DecisionBlock,
    Edge,
    EndBlock,
    ParallelBlock,
    RetryableBlock,
    ScriptBlock,
    Skill,
    SkillCatalog,
    TaskBlock,
)
from pskill_runner.validator import validate_skill
from pskill_runner.yaml_loading import load_answer_yaml

ENTRY_SCRIPT_NAME = "pskill.py"
INLINE_BLOCK_LIMIT = 1000
TASK_NAME_LIMIT = 60  # characters: a task name is a short label
OUTPUT_LIMIT_CHARACTERS = 64 * 1024  # characters: the most of a text output or a stderr that a run keeps


class RunError(Exception):
    """A command cannot run: an unknown run, a run in the wrong status, or an invalid skill."""


class RunnerStop(Exception):
    """A runner-side failure (a computed value, no matching edge, invalid end outputs, a cap with no target).

    It pauses the run.
    """


# ---------------------------------------------------------------------------------------------
# Public commands
# ---------------------------------------------------------------------------------------------


def start_run(
    project: Project,
    skill_id: str,
    raw_inputs: dict[str, Any],
    mode: str,
    harness: str,
    executor: InlineExecutor | None = None,
    runs_folder: Path | None = None,
    allow_internal: bool = False,
    session_id: str | None = None,
) -> tuple[str, str]:
    """Create a run and return its id and its first packet.

    `runs_folder` and `allow_internal` let `pskill test` use a temp folder and replay an internal skill.
    """
    catalog = load_catalog(project.skills_folder, project.agents_folder)
    skill = load_valid_skill(project, skill_id, catalog)
    if skill.invocation == "internal" and not allow_internal:
        raise RunError(
            f"{skill_id!r} is an internal skill: only a call block of another skill starts it. "
            "Start the skill that calls it."
        )
    inputs = checked_inputs(skill, raw_inputs)
    now = utc_now()
    run_id = new_run_id(now)
    folder = (runs_folder or project.runs_folder) / run_id
    folder.mkdir(parents=True)
    copy_run_snapshot(project, folder, skill, catalog)
    repo_commit, repo_dirty = repository_state(project.root)
    info = RunInfo(
        schema_version=SCHEMA_VERSION,
        run_id=run_id,
        skill_id=skill.id,
        skill_hash=folder_hash(folder / "skills" / skill.id),
        repo_commit=repo_commit,
        repo_dirty=repo_dirty,
        runner_version=pskill_runner.__version__,
        harness=adapter_for(harness).name,
        session_id=session_id,
        mode=mode,
        inputs=inputs,
        status="active",
        pause_reason=None,
        pause_error=None,
        current_block=None,
        packet_issued_at=None,
        attempts=0,
        stop_blocks=0,
        created_at=timestamp(now),
        updated_at=timestamp(now),
        ended_at=None,
        outputs=None,
        final_report=None,
    )
    state = RunState(frames=[new_frame(skill.id, inputs, started_at=timestamp(now))])
    run = Run(project, folder, info, state, executor)
    run.log(
        "run_started",
        skill_id=skill.id,
        skill_hash=info["skill_hash"],
        inputs=inputs,
        mode=mode,
        harness=info["harness"],
        runner_version=info["runner_version"],
    )
    text = run.guarded(lambda: run.enter_skill(skill))
    run.save()
    return run_id, text


def current_packet(
    project: Project, run_id: str | None, harness: str | None = None, session_id: str | None = None
) -> str:
    """Print the current packet again, worded for the calling harness. Only a harness or session change is recorded."""
    resolved_run_id = resolve_run_id(project, run_id)
    with run_lock(run_folder(project, resolved_run_id)):
        run = Run.load(project, resolved_run_id)
        run.use_harness(harness)
        run.use_session(session_id)
        text = run.current_text()
        run.save()
    return text


def submit_answer(
    project: Project,
    run_id: str,
    answer_text: str,
    task: int | None = None,
    executor: InlineExecutor | None = None,
    runs_folder: Path | None = None,
    harness: str | None = None,
    session_id: str | None = None,
    answer_file: Path | None = None,
) -> str:
    """Take an answer. With `answer_file` (`submit --file`), delete that file once the run records the answer.

    A later visit of the block then never sends the old answer again. A rejected answer keeps its file, so
    the agent fixes only the wrong fields.
    """
    folder = run_folder(project, run_id, runs_folder)
    with run_lock(folder):
        run = Run.load(project, run_id, executor, runs_folder)
        run.use_harness(harness)
        if task is None:  # a task answer comes from a subagent, which may have its own session id
            run.use_session(session_id)
        text = run.submit(answer_text, task)
        run.save()
    if answer_file is not None and run.answer_recorded:
        delete_answer_file(answer_file, folder / "answers")
    return text


def delete_answer_file(answer_file: Path, answers_folder: Path) -> None:
    """Delete a recorded answer's file, only inside the run's `answers/` folder: never a file of the user's.

    A file that another program holds open stays: the answer is safe in the run.
    """
    if not answer_file.resolve().is_relative_to(answers_folder.resolve()):
        return
    with contextlib.suppress(OSError):
        answer_file.unlink(missing_ok=True)


def task_packet(project: Project, run_id: str, index: int) -> str:
    """The full prompt of one open task of the current parallel block, for the subagent that runs it."""
    with run_lock(run_folder(project, run_id)):
        run = Run.load(project, run_id)
        return run.task_text(index)


def pause_run(project: Project, run_id: str) -> str:
    with run_lock(run_folder(project, run_id)):
        run = Run.load(project, run_id)
        run.require_status(ACTIVE_STATUSES, "pause")
        text = run.pause("paused_by_user", None)
        run.save()
    return text


def resume_run(project: Project, run_id: str, harness: str | None = None, session_id: str | None = None) -> str:
    with run_lock(run_folder(project, run_id)):
        run = Run.load(project, run_id)
        run.use_harness(harness)
        run.use_session(session_id)
        run.require_status(("paused",), "resume")
        text = run.resume()
        run.save()
    return text


def cancel_run(project: Project, run_id: str) -> str:
    with run_lock(run_folder(project, run_id)):
        run = Run.load(project, run_id)
        run.require_status(UNFINISHED_STATUSES, "cancel")
        run.end_run("cancelled", outputs={}, report=None)
        run.save()
    return f"Run {run_id} is cancelled. No more pskill commands are needed.\n"


def delete_run(project: Project, run_id: str) -> str:
    """Delete the folder of a finished run, for cleanup. An unfinished run must be cancelled first.

    The id must name a folder right inside `runs/`, so that `../` never reaches another folder.
    """
    folder = run_folder(project, run_id)
    if folder.resolve().parent != project.runs_folder.resolve():
        raise RunError(f"There is no run {run_id!r}. List the runs with `pskill runs`.")
    with run_lock(folder):
        status = read_run_info(project, run_id)["status"]
        if status in UNFINISHED_STATUSES:
            raise RunError(f"Run {run_id} is {status}, so it cannot be deleted. Cancel it first.")
    shutil.rmtree(folder)
    return f"Run {run_id} is deleted.\n"


def register_stop_attempt(project: Project, run_id: str) -> bool:
    """Count one try of the agent to end its turn with an open block. Return True to keep it working.

    After `stop_hook_max_blocks` tries in a row with no submission between them, pause the run and
    return False, so the agent can stop and a stuck run never loops forever.
    """
    with run_lock(run_folder(project, run_id)):
        run = Run.load(project, run_id)
        run.info["stop_blocks"] += 1
        keep_working = run.info["stop_blocks"] <= project.config.stop_hook_max_blocks
        if not keep_working:
            run.pause("agent_stopped", "The agent ended its turn with an open block, several times in a row.")
        run.save()
    return keep_working


def read_run_info(project: Project, run_id: str, runs_folder: Path | None = None) -> RunInfo:
    return cast(RunInfo, read_json(run_folder(project, run_id, runs_folder) / "run.json"))


def read_run_state(project: Project, run_id: str, runs_folder: Path | None = None) -> RunState:
    return cast(RunState, read_json(run_folder(project, run_id, runs_folder) / "state.json"))


def list_runs(project: Project) -> list[RunInfo]:
    """Every run in the project, newest first."""
    if not project.runs_folder.is_dir():
        return []
    runs = [
        cast(RunInfo, read_json(folder / "run.json"))
        for folder in project.runs_folder.iterdir()
        if (folder / "run.json").is_file()
    ]
    return sorted(runs, key=lambda info: info["updated_at"], reverse=True)


def resolve_run_id(project: Project, run_id: str | None) -> str:
    """Use the given run id, or the newest unfinished run."""
    if run_id is not None:
        return run_id
    for info in list_runs(project):
        if info["status"] in UNFINISHED_STATUSES:
            return info["run_id"]
    raise RunError("There is no unfinished run. Start one with `pskill start <skill>`.")


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------


def run_folder(project: Project, run_id: str, runs_folder: Path | None = None) -> Path:
    folder = (runs_folder or project.runs_folder) / run_id
    if not (folder / "run.json").is_file():
        raise RunError(f"There is no run {run_id!r}. List the runs with `pskill runs`.")
    return folder


def load_valid_skill(project: Project, skill_id: str, catalog: SkillCatalog) -> Skill:
    """Load a skill and refuse it when it has validation errors (a stale stub never blocks a run)."""
    folder = project.skills_folder / skill_id
    if not (folder / "skill.yaml").is_file():
        raise RunError(f"There is no skill {skill_id!r}. List the skills with `pskill list`.")
    try:
        skill = load_skill(folder)
    except SkillLoadError as error:
        raise RunError(f"The skill {skill_id!r} is invalid:\n- " + "\n- ".join(error.problems)) from error
    problems = validate_skill(skill, catalog)
    errors = [f"{problem.location}: {problem.message}" for problem in problems if problem.level == "error"]
    if errors:
        raise RunError(f"The skill {skill_id!r} is invalid:\n- " + "\n- ".join(errors))
    return skill


def checked_inputs(skill: Skill, raw_inputs: dict[str, Any]) -> dict[str, Any]:
    """Convert text inputs (from the command line or stdin) to the declared types, and apply defaults."""
    inputs, errors = check_answer(raw_inputs, skill.inputs)
    if errors:
        raise RunError("The inputs are invalid:\n- " + "\n- ".join(errors))
    return with_defaults(inputs, skill.inputs)


def with_defaults(inputs: dict[str, Any], fields: FieldMap) -> dict[str, Any]:
    missing_defaults = {name: spec.default for name, spec in fields.items() if name not in inputs}
    return {**{name: value for name, value in missing_defaults.items() if value is not None}, **inputs}


def called_skills(skill: Skill, catalog: SkillCatalog) -> list[Skill]:
    """The skill and every skill that it can reach through `call` blocks."""
    found: dict[str, Skill] = {}
    to_visit = [skill]
    while to_visit:
        current = to_visit.pop()
        if current.id in found:
            continue
        found[current.id] = current
        for block in current.blocks.values():
            if isinstance(block, CallBlock) and block.skill in catalog.skills:
                to_visit.append(catalog.skills[block.skill])
    return list(found.values())


def copy_run_snapshot(project: Project, folder: Path, skill: Skill, catalog: SkillCatalog) -> None:
    """Copy every skill that the run can reach, and the pskill agents, into the run (D22)."""
    for reached_skill in called_skills(skill, catalog):
        copy_skill_snapshot(reached_skill.folder, folder)
    if project.agents_folder.is_dir():
        shutil.copytree(project.agents_folder, folder / "agents", dirs_exist_ok=True)


def repository_state(root: Path) -> tuple[str | None, bool | None]:
    """The git commit and whether the working tree has changes. (None, None) outside git."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()
        changes = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None, None
    return commit, bool(changes)


def runner_command(project: Project) -> str:
    """How the agent calls the runner: the project launcher, `uv run .pskill/pskill.py`.

    Never the runner's own folder: in a cached install that is an absolute path that the permission rule
    does not match.
    """
    entry_script = project.pskill_folder / ENTRY_SCRIPT_NAME
    return f"uv run {entry_script.relative_to(project.root).as_posix()}"


def visit_cap_question(block: AnyBlock, visits: int, asks_the_human: bool) -> DecisionBlock:
    """The question that the runner asks at a block's visit cap (SPEC.md section 5.5). It is not in `skill.yaml`."""
    return DecisionBlock(
        id=block.id,
        decider="human",
        instruction=visit_cap_instruction(block.id, visits, asks_the_human),
        choices=VISIT_CAP_CHOICES,
        output={"rounds": VISIT_CAP_ROUNDS},
        # A script's `retries` means "run the command again", not "ask again", so only an agent block's counts.
        retries=block.retries if isinstance(block, TaskBlock | DecisionBlock) else None,
    )


def decision_fields(block: DecisionBlock, asks_the_human: bool) -> FieldMap:
    """The fields that every decision returns, plus the block's own extra fields."""
    automatic: FieldMap
    if block.choices:
        automatic = {
            "choice": FieldSpec(type="string", description="The chosen option.", enum=tuple(block.choices)),
            "rationale": FieldSpec(type="string", description="Why this choice (for a user's choice: their words)."),
        }
    else:
        answer_description = (
            "The user's answer, word for word." if asks_the_human else "Your answer, as the user would give it."
        )
        automatic = {
            "answer": FieldSpec(type="string", description=answer_description),
            "rationale": FieldSpec(type="string", description="Why this answer.", optional=True),
        }
    return {**automatic, **block.output}


def script_problem(result: ScriptResult, parse: str) -> str | None:
    """Why a script result is a failure, or None when it succeeded."""
    if result.problem is not None:
        return f"The script failed: {result.problem}."
    if result.exit_code != 0:
        stderr_tail = result.stderr.strip()[-500:]
        return f"The script ended with exit code {result.exit_code}." + (f"\n{stderr_tail}" if stderr_tail else "")
    if parse == "json":
        try:
            load_json_text(result.stdout)
        except ValueError as error:
            return f"The script output is not valid JSON: {error}"
    return None


def stored_result(result: ScriptResult, parse: str) -> ScriptResult:
    """The result that the run keeps: a JSON stdout whole (it is the block's value), any other output limited."""
    stdout = result.stdout if parse == "json" else limited_output(result.stdout)
    return replace(result, stdout=stdout, stderr=limited_output(result.stderr))


def limited_output(text: str) -> str:
    """The text, or its first OUTPUT_LIMIT_CHARACTERS and a note that says it was cut, so no step takes it as whole."""
    if len(text) <= OUTPUT_LIMIT_CHARACTERS:
        return text
    note = f"[pskill cut this output: it keeps the first {OUTPUT_LIMIT_CHARACTERS} of {len(text)} characters.]"
    return f"{text[:OUTPUT_LIMIT_CHARACTERS]}\n{note}\n"


def load_json_text(text: str) -> Any:
    return json.loads(text)


def stdin_text_of(script_input: Any) -> str:
    """What a script reads on stdin: a text as it is, any other value as JSON."""
    return script_input if isinstance(script_input, str) else json.dumps(script_input)


def task_not_recorded(task: int, errors: list[str]) -> str:
    """The reply to a task answer that fails its checks: the subagent fixes it and submits again."""
    listed = "\n".join(f"- {error}" for error in errors)
    return f"Task {task} is not recorded. Fix these problems and submit again:\n{listed}\n"


def elapsed_ms_since(timestamp_text: str | None) -> int:
    if timestamp_text is None:  # pragma: no cover - every agent block sets packet_issued_at first
        return 0
    return int((utc_now() - parse_timestamp(timestamp_text)).total_seconds() * 1000)


# ---------------------------------------------------------------------------------------------
# One loaded run
# ---------------------------------------------------------------------------------------------


class Run:
    def __init__(
        self,
        project: Project,
        folder: Path,
        info: RunInfo,
        state: RunState,
        executor: InlineExecutor | None = None,
    ) -> None:
        self.project = project
        self.folder = folder
        self.info = info
        self.state = state
        self.executor: InlineExecutor = executor or RealExecutor()
        self.skills: dict[str, Skill] = {}
        self.adapter = adapter_for(info["harness"])
        self.answer_recorded = False  # set by `submit` when it keeps the answer, not when it rejects it

    @classmethod
    def load(
        cls,
        project: Project,
        run_id: str,
        executor: InlineExecutor | None = None,
        runs_folder: Path | None = None,
    ) -> "Run":
        folder = run_folder(project, run_id, runs_folder)
        info = read_run_info(project, run_id, runs_folder)
        return cls(project, folder, info, read_run_state(project, run_id, runs_folder), executor)

    def save(self) -> None:
        self.info["updated_at"] = timestamp(utc_now())
        self.info["current_block"] = self.frame["current_block"]
        write_json_atomic(self.folder / "run.json", self.info)
        write_json_atomic(self.folder / "state.json", self.state)

    def use_harness(self, harness: str | None) -> None:
        """A run can continue in another harness (D13). Record the change and word packets for it."""
        if harness is None or harness == self.info["harness"]:
            return
        self.adapter = adapter_for(harness)
        self.log("harness_changed", **{"from": self.info["harness"], "to": harness})
        self.info["harness"] = harness

    def use_session(self, session_id: str | None) -> None:
        """The session that runs a command owns the run, so the Stop hook holds only that session."""
        if session_id is None or session_id == self.info.get("session_id"):
            return
        self.log("session_changed", **{"from": self.info.get("session_id"), "to": session_id})
        self.info["session_id"] = session_id

    def log(self, event_type: str, **fields: Any) -> None:
        append_event(self.folder, event_type, frame=">".join(self.chain()), **fields)

    # --- reading the state -------------------------------------------------------------------

    @property
    def frame(self) -> Frame:
        return self.state["frames"][-1]

    def skill_by_id(self, skill_id: str) -> Skill:
        """A skill from the run's own copy, never from the project (D22)."""
        if skill_id not in self.skills:
            self.skills[skill_id] = load_skill(self.folder / "skills" / skill_id)
        return self.skills[skill_id]

    def skill_of(self, frame: Frame) -> Skill:
        return self.skill_by_id(frame["skill_id"])

    def chain(self) -> list[str]:
        return [frame["skill_id"] for frame in self.state["frames"]]

    def current_block(self) -> AnyBlock:
        block_id = self.frame["current_block"]
        if block_id is None:
            raise RunError("The run has no current block.")
        block = self.skill_of(self.frame).blocks[block_id]
        if self.frame.get("visit_cap_question"):
            interactive = self.info["mode"] == "interactive"
            return visit_cap_question(block, self.frame["visits"].get(block_id, 0), interactive)
        return block

    def autonomous_ceiling_of(self, block: AnyBlock) -> int:
        """The most visits that the agent may allow: the block's own ceiling, or the `config.yaml` value.

        Never below `max_visits`, so a config ceiling under a block's cap does not cut the block short.
        """
        ceiling = block.autonomous_max_visits or self.project.config.autonomous_max_visits
        return max(ceiling, block.max_visits or 0)

    def retries_of(self, block: AnyBlock) -> int:
        """The block's own `retries`, or the global value from `config.yaml`."""
        if isinstance(block, RetryableBlock) and block.retries is not None:
            return block.retries
        return self.project.config.retries

    def context(self, item: Any = None) -> dict[str, Any]:
        """The names that `{{ }}` values can read (SPEC.md section 7.1)."""
        frame = self.frame
        skill = self.skill_of(frame)
        context = {
            "inputs": frame["inputs"],
            "steps": frame["steps"],
            "history": {block_id: frame["history"].get(block_id, []) for block_id in skill.blocks},
            "run": {
                "id": self.info["run_id"],
                "mode": self.info["mode"],
                "harness": self.info["harness"],
                "dir": str(self.folder),
            },
            "skill": {"id": skill.id, "dir": str(skill.folder)},
        }
        if item is not None:
            context["item"] = item
        return context

    def computed(self, value: Any, what: str, item: Any = None) -> Any:
        """Compute a `{{ }}` value. A failure pauses the run (a runner-side failure)."""
        try:
            return compute(value, self.context(item))
        except ComputedValueError as error:
            raise RunnerStop(f"{what} failed: {error}") from error

    def rendered(self, text: str, what: str, item: Any = None) -> str:
        try:
            return render_text(text, self.context(item))
        except ComputedValueError as error:
            raise RunnerStop(f"{what} failed: {error}") from error

    def asks_the_human(self, block: AnyBlock) -> bool:
        return isinstance(block, DecisionBlock) and block.decider == "human" and self.info["mode"] == "interactive"

    def require_status(self, allowed: tuple[str, ...], action: str) -> None:
        status = self.info["status"]
        if status not in allowed:
            raise RunError(f"Run {self.info['run_id']} is {status}, so it cannot {action}.")

    # --- moving through the graph ------------------------------------------------------------

    def guarded(self, step: Callable[[], str]) -> str:
        """Run a step. A runner-side failure pauses the run instead of crashing."""
        try:
            return step()
        except RunnerStop as stop:
            return self.pause("runner_error", str(stop))

    def enter_skill(self, skill: Skill) -> str:
        """Start the current frame at its skill's entry, then continue."""
        target, reason = self.choose_edge(skill.entry)
        self.go_to(target, from_block=None, reason=reason)
        return self.advance()

    def choose_edge(self, edges: list[Edge]) -> tuple[str, str]:
        """Return the target of the first edge that applies, and why it applied."""
        for edge in edges:
            if edge.when is None:
                return edge.to, "always"
            if is_true_or_stop(edge.when, self.context()):
                return edge.to, edge.when
        raise RunnerStop("no edge matched: every edge has a when, and none of them is true")

    def go_to(self, target: str, from_block: str | None, reason: str) -> None:
        """Enter a block, following its visit cap (SPEC.md section 5.5)."""
        block = self.skill_of(self.frame).blocks[target]
        visits = self.frame["visits"].get(target, 0)
        extra_visits = self.frame.get("extra_visits", {}).get(target, 0)
        at_ceiling = self.info["mode"] == "autonomous" and visits >= self.autonomous_ceiling_of(block)
        if block.max_visits is not None and (visits >= block.max_visits + extra_visits or at_ceiling):
            if block.on_max_visits is None:  # a run started before 0.33.0 can have a cap with no target
                raise RunnerStop(f"The block {block.id!r} reached its visit cap ({block.max_visits}).")
            if block.asks_at_cap and not at_ceiling:
                self.frame["visit_cap_question"] = True
                self.arrive(target, from_block, reason)
                return
            self.move_on_from_cap(block)
            return
        self.frame["visits"][target] = visits + 1
        self.arrive(target, from_block, reason)

    def arrive(self, target: str, from_block: str | None, reason: str) -> None:
        self.frame["current_block"] = target
        self.frame["arrived_from"] = from_block
        self.frame["arrival_reason"] = reason

    def move_on_from_cap(self, block: AnyBlock) -> None:
        """Leave a capped block for its `on_max_visits` block. `go_to` checked that the block has one."""
        assert block.on_max_visits is not None
        self.go_to(block.on_max_visits, from_block=block.id, reason=f"visit cap of {block.id} ({block.max_visits})")

    def follow_edges(self, block: AnyBlock, value: dict[str, Any]) -> None:
        """Go to the next block after a completed block."""
        if isinstance(block, EndBlock):  # pragma: no cover - finish() ends a skill; no end block completes
            raise RunError("An end block has no next block.")
        if isinstance(block, DecisionBlock) and isinstance(block.next, dict):
            choice = value["choice"]
            target, condition = self.choose_edge(block.next[choice])
            reason = f"choice {choice}" if condition == "always" else f"choice {choice}: {condition}"
        else:
            edges = block.next if isinstance(block.next, list) else []
            target, reason = self.choose_edge(edges)
        self.go_to(target, from_block=block.id, reason=reason)

    def advance(self) -> str:
        """Run runner blocks until a block needs the agent, the run pauses, or the run ends."""
        for _ in range(INLINE_BLOCK_LIMIT):
            block = self.current_block()
            if isinstance(block, EndBlock):
                final_text = self.finish(block)
                if final_text is not None:
                    return final_text
            elif isinstance(block, ScriptBlock):
                pause_text = self.run_script(block)
                if pause_text is not None:
                    return pause_text
            elif isinstance(block, CallBlock):
                self.start_call(block)
            elif isinstance(block, ParallelBlock) and not self.start_parallel(block):
                continue  # an empty list: the block completed at once
            else:
                return self.issue_packet(new_block=True)
        raise RunnerStop(f"More than {INLINE_BLOCK_LIMIT} runner blocks ran without an agent block.")

    def complete_block(self, block: AnyBlock, value: dict[str, Any], decided_by: str, duration_ms: int) -> None:
        """Store a block's output, log it, and go to the next block."""
        self.frame["steps"][block.id] = value
        self.frame["history"].setdefault(block.id, []).append(value)
        self.log("block_completed", block=block.id, output=value, decided_by=decided_by, duration_ms=duration_ms)
        self.info["attempts"] = 0
        self.follow_edges(block, value)

    def log_block_started(self, block: AnyBlock, packet: str | None, task: int | None = None) -> None:
        fields: dict[str, Any] = {
            "block": block.id,
            "block_type": (
                "visit_cap"
                if self.frame.get("visit_cap_question")
                else type(block).__name__.removesuffix("Block").lower()
            ),
            "visit": self.frame["visits"].get(block.id, 0),
            "from": self.frame["arrived_from"],
            "reason": self.frame["arrival_reason"],
            "packet": packet,
        }
        if task is not None:
            fields["task"] = task
        task_names = [task.get("name") for task in self.frame["tasks"] or []]
        if isinstance(block, ParallelBlock) and any(task_names):
            fields["task_names"] = task_names  # the viewer names the tasks of finished runs from this
        skipped_tasks = self.frame.get("skipped_tasks")
        if isinstance(block, ParallelBlock) and skipped_tasks:
            fields["skipped_tasks"] = skipped_tasks
        if isinstance(block, ParallelBlock) and task is None and self.frame["tasks"]:
            fields["task_prompts"] = self.task_prompts(block)
        self.log("block_started", **fields)

    def task_prompts(self, block: ParallelBlock) -> list[str]:
        """The full prompt of every task. The packet gives only one line per task, so the viewer reads these."""
        base = self.base_packet(block, [])
        return [
            task_prompt_text(base, self.task_prompt(block, index)) for index in range(len(self.frame["tasks"] or []))
        ]

    # --- end blocks ---------------------------------------------------------------------------

    def finish(self, block: EndBlock) -> str | None:
        """End the current skill. Return the final packet for the root skill, or None for a child."""
        skill = self.skill_of(self.frame)
        self.log_block_started(block, packet=None)
        outputs = self.computed(block.outputs, f"The end block {block.id!r}")
        errors = check_typed_values(outputs, skill.outputs)
        if errors:
            raise RunnerStop(f"The end block {block.id!r} gives invalid outputs: " + "; ".join(errors))
        self.log("block_completed", block=block.id, output=outputs, decided_by="runner", duration_ms=0)
        if len(self.state["frames"]) > 1:
            self.return_to_caller(block.status, outputs)
            return None
        report = self.rendered(skill.instruction_text(block.report), "The report") if block.report else None
        self.end_run(block.status, outputs, report)
        return render_final_packet(self.info["run_id"], skill.id, block.status, report, outputs)

    def end_run(self, status: str, outputs: dict[str, Any], report: str | None) -> None:
        self.info["status"] = status
        self.info["outputs"] = outputs
        self.info["final_report"] = report
        self.info["ended_at"] = timestamp(utc_now())
        self.log("run_ended", status=status, outputs=outputs, duration_ms=elapsed_ms_since(self.info["created_at"]))

    # --- call blocks --------------------------------------------------------------------------

    def start_call(self, block: CallBlock) -> None:
        """Push the child skill's frame, or use a ready result (in `pskill test`)."""
        self.log_block_started(block, packet=None)
        inputs = self.computed(block.inputs, f"The inputs of {block.id!r}")
        ready_result = self.executor.call_result(block.id, block.skill, inputs)
        if ready_result is not None:
            value = {"status": ready_result.status, "outputs": ready_result.outputs}
            self.complete_block(block, value, decided_by="runner", duration_ms=0)
            return
        callee = self.skill_by_id(block.skill)
        errors = check_typed_values(inputs, callee.inputs)
        if errors:
            raise RunnerStop(f"The inputs of {block.id!r} are invalid: " + "; ".join(errors))
        self.state["frames"].append(new_frame(callee.id, with_defaults(inputs, callee.inputs), timestamp(utc_now())))
        target, reason = self.choose_edge(callee.entry)
        self.go_to(target, from_block=None, reason=reason)

    def return_to_caller(self, status: str, outputs: dict[str, Any]) -> None:
        """Pop the child frame and complete the caller's call block with the child's result."""
        child = self.state["frames"].pop()
        call_block = self.current_block()
        value = {"status": status, "outputs": outputs}
        self.complete_block(call_block, value, decided_by="runner", duration_ms=elapsed_ms_since(child["started_at"]))

    # --- script blocks ------------------------------------------------------------------------

    def run_script(self, block: ScriptBlock) -> str | None:
        """Run a script, with retries. Return the pause text on failure, or None on success."""
        self.log_block_started(block, packet=None)
        argv = [str(part) for part in self.computed(block.run, f"The command of {block.id!r}")]
        script_input = self.computed(block.input, f"The input of {block.id!r}")
        stdin_text = None if script_input is None else stdin_text_of(script_input)
        # A Python script reads stdin and writes stdout as UTF-8 on every system, as the runner does.
        env = {**os.environ, "PSKILL_RUN_DIR": str(self.folder), "PYTHONIOENCODING": "utf-8"}
        problem = None
        timeout_s = block.timeout_s if block.timeout_s is not None else self.project.config.script_timeout_s
        for _ in range(self.retries_of(block) + 1):
            whole_result = self.executor.run_script(block.id, argv, self.project.root, env, timeout_s, stdin_text)
            problem = script_problem(whole_result, block.parse)
            result = stored_result(whole_result, block.parse)
            self.log(
                "script_ran",
                block=block.id,
                argv=argv,
                input=script_input,
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                duration_ms=result.duration_ms,
                problem=result.problem,
            )
            if problem is None:
                value: dict[str, Any] = {
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
                if block.parse == "json":
                    value["json"] = load_json_text(result.stdout)
                self.complete_block(block, value, decided_by="runner", duration_ms=result.duration_ms)
                return None
        return self.pause("block_failed", problem)

    # --- parallel blocks ----------------------------------------------------------------------

    def start_parallel(self, block: ParallelBlock) -> bool:
        """Create the tasks. Return False when no item runs (the block then completes at once)."""
        items = self.computed(block.for_each, f"The for_each of {block.id!r}")
        if not isinstance(items, list):
            raise RunnerStop(f"The for_each of {block.id!r} must give a list, not {type(items).__name__}.")
        items = self.items_that_run(block, items)
        if not items:
            self.log_block_started(block, packet=None)
            self.frame["skipped_tasks"] = None
            self.complete_block(block, {"results": []}, decided_by="runner", duration_ms=0)
            return False
        self.frame["tasks"] = [
            ParallelTask(
                item=item,
                agent=str(self.computed(block.agent, f"The agent of {block.id!r}", item)) if block.agent else None,
                name=self.task_name(block, item),
                output=None,
                attempts=0,
            )
            for item in items
        ]
        return True

    def items_that_run(self, block: ParallelBlock, items: list[Any]) -> list[Any]:
        """The items of a fixed `for_each` list whose `when` is true, without their `when` key.

        `items` is the computed list, so each `when` already holds its result. The skipped items go to the
        frame, so that `block_started` can say which tasks did not run, and why.
        """
        if not isinstance(block.for_each, list):
            return items  # A list computed during the run: its items are data, and a `when` key is plain data.
        kept: list[Any] = []
        skipped: list[SkippedTask] = []
        for written, item in zip(block.for_each, items, strict=True):
            if not (isinstance(written, dict) and "when" in written):
                kept.append(item)
                continue
            item_without_when = {key: value for key, value in item.items() if key != "when"}
            if item["when"]:
                kept.append(item_without_when)
            else:
                skipped.append(SkippedTask(name=self.task_name(block, item_without_when), when=str(written["when"])))
        self.frame["skipped_tasks"] = skipped
        return kept

    def task_name(self, block: ParallelBlock, item: Any) -> str | None:
        """The task's name from `task_name`, on one short line. A name that fails or is empty is no name:
        the task then shows as "task <n>", and the run goes on."""
        if block.task_name is None:
            return None
        try:
            name = " ".join(str(compute(block.task_name, self.context(item))).split())
        except ComputedValueError:
            return None
        if len(name) > TASK_NAME_LIMIT:
            name = name[: TASK_NAME_LIMIT - 1].rstrip() + "…"
        return name or None

    def open_task_indexes(self) -> list[int]:
        return [index for index, task in enumerate(self.frame["tasks"] or []) if task["output"] is None]

    def agent_text(self, agent_name: str | None) -> str | None:
        """The role text of a pskill agent, from the run's own copy of `.pskill/agents/`."""
        if agent_name is None:
            return None
        path = self.folder / "agents" / f"{agent_name}.md"
        if not path.is_file():
            raise RunnerStop(f"There is no agent file '{agent_name}.md' in .pskill/agents/.")
        return path.read_text(encoding="utf-8")

    def task_prompt(self, block: ParallelBlock, index: int) -> TaskPrompt:
        task = (self.frame["tasks"] or [])[index]
        skill = self.skill_of(self.frame)
        instruction = self.rendered(skill.instruction_text(block.instruction), f"Task {index}", task["item"])
        return TaskPrompt(
            index=index,
            agent_text=self.agent_text(task["agent"]),
            instruction=instruction,
            return_fields=block.output,
            name=task.get("name"),
        )

    def parallel_packet(self, block: ParallelBlock, errors: list[str], show_goal: bool, show_rules: bool) -> str:
        """All open tasks for subagents (each task prompt has the goal), or the next open task for the main agent."""
        open_indexes = self.open_task_indexes()
        if self.adapter.can_spawn_subagents:
            tasks = [self.task_prompt(block, index) for index in open_indexes]
            text = render_parallel_packet(self.base_packet(block, errors), tasks, len(self.frame["tasks"] or []))
            return text
        next_task = self.task_prompt(block, open_indexes[0])
        instruction = "\n\n".join(part for part in (next_task.agent_text, next_task.instruction) if part)
        packet = self.base_packet(block, errors, instruction, task_index=next_task.index)
        return render_agent_packet(replace(packet, show_goal=show_goal, show_rules=show_rules))

    # --- packets -------------------------------------------------------------------------------

    def issue_packet(self, new_block: bool, reentry: bool = False) -> str:
        """Print the packet of the current agent block, and start its clock.

        The first packet of a child skill shows the child's goal once. A re-entry (`resume`) shows the
        goal and the rules, because the session may not have read the stub.
        """
        block = self.current_block()
        self.info["status"] = "waiting_for_human" if self.asks_the_human(block) else "active"
        self.info["packet_issued_at"] = timestamp(utc_now())
        enters_child = len(self.state["frames"]) > 1 and not self.frame.get("goal_shown", False)
        if enters_child:
            self.frame["goal_shown"] = True
        text = self.agent_packet(errors=[], show_goal=enters_child or reentry, show_rules=reentry)
        if new_block:
            self.info["attempts"] = 0
            self.log_block_started(block, packet=text, task=self.sequential_task_index(block))
        return text

    def sequential_task_index(self, block: AnyBlock) -> int | None:
        """The task that a one-by-one parallel packet shows, or None."""
        if isinstance(block, ParallelBlock) and not self.adapter.can_spawn_subagents:
            return self.open_task_indexes()[0]
        return None

    def agent_packet(self, errors: list[str], show_goal: bool = False, show_rules: bool = False) -> str:
        block = self.current_block()
        if isinstance(block, ParallelBlock):
            return self.parallel_packet(block, errors, show_goal, show_rules)
        if not isinstance(
            block, TaskBlock | DecisionBlock
        ):  # pragma: no cover - an active run waits only at an agent block
            raise RunError(f"The block {block.id!r} does not need the agent.")
        skill = self.skill_of(self.frame)
        instruction = self.rendered(skill.instruction_text(block.instruction), f"The instruction of {block.id!r}")
        packet = self.base_packet(block, errors, instruction)
        return render_agent_packet(replace(packet, show_goal=show_goal, show_rules=show_rules))

    def base_packet(
        self, block: AgentBlock, errors: list[str], instruction: str = "", task_index: int | None = None
    ) -> AgentPacket:
        return AgentPacket(
            run_id=self.info["run_id"],
            chain=self.chain(),
            block_id=block.id,
            visit=self.frame["visits"].get(block.id, 0),
            mode=self.info["mode"],
            goal=self.skill_of(self.frame).goal,
            instruction=instruction,
            return_fields=self.return_fields(block),
            choices=block.choices if isinstance(block, DecisionBlock) else None,
            decider=block.decider if isinstance(block, DecisionBlock) else None,
            errors=errors,
            runner_command=runner_command(self.project),
            shell=detect_shell(),
            question_wording=self.adapter.question_wording,
            answers_folder=self.answers_folder(),
            task_index=task_index,
            subagent_wording=self.adapter.subagent_wording,
            work_folder=self.project.root.as_posix(),
        )

    def answers_folder(self) -> str:
        """Create the run's folder for answer files, and return it as the agent writes it.

        Relative to the project root, except for `pskill test`, whose runs live in a temp folder.
        """
        folder = self.folder / "answers"
        folder.mkdir(exist_ok=True)
        shown = folder.relative_to(self.project.root) if folder.is_relative_to(self.project.root) else folder
        return shown.as_posix()

    def return_fields(self, block: AgentBlock) -> FieldMap:
        if isinstance(block, DecisionBlock):
            return decision_fields(block, self.asks_the_human(block))
        return block.output

    def current_text(self) -> str:
        status = self.info["status"]
        if status in ACTIVE_STATUSES:  # a re-entry: a new session may not have read the stub
            return self.guarded(lambda: self.agent_packet(errors=[], show_goal=True, show_rules=True))
        if status == "paused":
            return self.pause_text()
        return render_final_packet(
            self.info["run_id"], self.info["skill_id"], status, self.info["final_report"], self.info["outputs"] or {}
        )

    # --- pause and resume ----------------------------------------------------------------------

    def pause(self, reason: str, error: str | None) -> str:
        self.info["status"] = "paused"
        self.info["pause_reason"] = reason
        self.info["pause_error"] = error
        self.log("run_paused", reason=reason, error=error)
        return self.pause_text()

    def pause_text(self) -> str:
        return render_pause_packet(
            self.info["run_id"],
            self.info["skill_id"],
            self.frame["current_block"] or "(none)",
            self.info["pause_reason"] or "paused",
            self.info["pause_error"],
            runner_command(self.project),
        )

    def paused_by_stop_attempts(self) -> bool:
        return self.info["status"] == "paused" and self.info["pause_reason"] == "agent_stopped"

    def resume(self) -> str:
        """Retry the current block with fresh attempt counts.

        A parallel block whose tasks all got their answers while the run was paused completes now.
        """
        self.info["attempts"] = 0
        self.info["stop_blocks"] = 0
        self.info["pause_reason"] = None
        self.info["pause_error"] = None
        for task in self.frame["tasks"] or []:
            task["attempts"] = 0
        self.log("run_resumed", reason="resumed_by_user")
        block = self.current_block()
        if isinstance(block, ParallelBlock) and self.frame["tasks"] is not None and not self.open_task_indexes():
            self.info["status"] = "active"
            return self.guarded(lambda: self.complete_parallel(block, duration_ms=0))
        if isinstance(block, TaskBlock | DecisionBlock | ParallelBlock):
            return self.guarded(lambda: self.issue_packet(new_block=False, reentry=True))
        self.info["status"] = "active"
        return self.guarded(self.advance)  # a script or a call: run it again

    # --- submissions ---------------------------------------------------------------------------

    def task_text(self, index: int) -> str:
        """The full prompt of one open task. A run paused by stop attempts still serves it."""
        if not self.paused_by_stop_attempts():
            self.require_status(ACTIVE_STATUSES, "give a task (run `pskill resume` first)")
        block = self.current_block()
        if not isinstance(block, ParallelBlock) or self.frame["tasks"] is None:
            raise RunError(f"The block {block.id!r} has no tasks.")
        self.check_open_task(block, index)
        return task_prompt_text(self.base_packet(block, []), self.task_prompt(block, index))

    def check_open_task(self, block: ParallelBlock, index: int) -> None:
        tasks = self.frame["tasks"] or []
        if not 0 <= index < len(tasks):
            raise RunError(f"The block {block.id!r} has no task {index} (tasks 0 to {len(tasks) - 1}).")
        if tasks[index]["output"] is not None:
            raise RunError(f"Task {index} of {block.id!r} already has an answer.")

    def submit(self, answer_text: str, task: int | None) -> str:
        if task is not None and self.paused_by_stop_attempts():
            return self.record_task_while_paused(answer_text, task)
        self.require_status(ACTIVE_STATUSES, "take an answer (run `pskill resume` first)")
        block = self.current_block()
        if not isinstance(block, TaskBlock | DecisionBlock | ParallelBlock):  # pragma: no cover - same: an agent block
            raise RunError(f"The block {block.id!r} does not take an answer.")
        if task is not None and not isinstance(block, ParallelBlock):
            raise RunError(f"The block {block.id!r} has no tasks, so `--task` does not apply.")
        self.info["stop_blocks"] = 0
        if isinstance(block, ParallelBlock):
            return self.submit_task(block, answer_text, task)
        answer, answered_by, errors = self.read_answer(answer_text, block)
        if errors:
            return self.reject(errors, answer_text)
        decided_by = self.decided_by(block, answered_by)
        duration_ms = elapsed_ms_since(self.info["packet_issued_at"])
        self.answer_recorded = True
        return self.guarded(lambda: self.accept(block, answer, decided_by, duration_ms))

    def submit_task(self, block: ParallelBlock, answer_text: str, task: int | None) -> str:
        """The answer of one task of a parallel block."""
        if task is None:
            return self.reject(["This block has several tasks. Add `--task <n>` to the submit command."], answer_text)
        answer, _, errors = self.read_answer(answer_text, block)
        if errors:
            return self.reject(errors, answer_text, task)
        self.answer_recorded = True
        return self.guarded(lambda: self.accept_task(block, task, answer))

    def record_task_while_paused(self, answer_text: str, task: int) -> str:
        """Keep a subagent's answer when the main agent's stop attempts paused the run. Only `resume` advances."""
        block = self.current_block()
        if not isinstance(block, ParallelBlock):
            raise RunError(f"The block {block.id!r} has no tasks, so `--task` does not apply.")
        answer, _, errors = self.read_answer(answer_text, block)
        if errors:
            return task_not_recorded(task, errors)
        self.record_task(block, task, answer)
        self.answer_recorded = True
        tasks = self.frame["tasks"] or []
        done = len(tasks) - len(self.open_task_indexes())
        return f"Task {task} is recorded while the run is paused. {done} of {len(tasks)} tasks are done.\n"

    def read_answer(self, answer_text: str, block: AgentBlock) -> tuple[dict[str, Any], str | None, list[str]]:
        """Parse and check an answer. Return the typed answer, who answered, and the problems."""
        try:
            raw_answer = load_answer_yaml(answer_text)
        except Exception as error:  # PyYAML raises several error types; all mean "not valid YAML"
            return (
                {},
                None,
                [f"The answer is not valid YAML: {error}\nWrite free text as `field: |` with indented lines."],
            )
        if isinstance(raw_answer, dict) and "$cannot_complete" in raw_answer:
            return {}, None, [f"You could not complete the block: {raw_answer['$cannot_complete']}"]
        answered_by = raw_answer.pop("$answered_by", None) if isinstance(raw_answer, dict) else None
        answer, errors = check_answer(raw_answer, self.return_fields(block))
        if self.needs_more_rounds(errors, answer):
            errors.append("For the choice `more`, give `rounds`: a whole number of at least 1.")
        if self.asks_the_human(block) and answered_by not in ("human", "agent"):
            errors.append(
                "Add the line `$answered_by: human` (the user answered) or `$answered_by: agent` (you answered)."
            )
        return answer, answered_by, errors

    def needs_more_rounds(self, errors: list[str], answer: dict[str, Any]) -> bool:
        """A valid cap answer `more` with no `rounds`, or fewer than 1. `check_answer` already checked the type."""
        if errors or not self.frame.get("visit_cap_question") or answer["choice"] != "more":
            return False
        return answer.get("rounds") is None or answer["rounds"] < 1

    def reject(self, errors: list[str], answer_text: str, task: int | None = None) -> str:
        """Count a failed attempt. Pause after the retries run out, else show the packet with the errors."""
        tasks = self.frame["tasks"] or []
        if task is not None and 0 <= task < len(tasks):
            tasks[task]["attempts"] += 1
            attempts = tasks[task]["attempts"]
        else:
            self.info["attempts"] += 1
            attempts = self.info["attempts"]
        self.log("submission_rejected", block=self.frame["current_block"], task=task, errors=errors, raw=answer_text)
        if attempts > self.retries_of(self.current_block()):
            return self.pause("block_failed", "\n".join(errors))
        if task is not None and self.adapter.can_spawn_subagents:
            return task_not_recorded(task, errors)  # the subagent gets its own errors, not the main agent's packet
        return self.guarded(lambda: self.agent_packet(errors=errors))

    def accept(
        self, block: TaskBlock | DecisionBlock, answer: dict[str, Any], decided_by: str, duration_ms: int
    ) -> str:
        if self.frame.get("visit_cap_question"):
            return self.answer_visit_cap(block.id, answer, decided_by, duration_ms)
        self.complete_block(block, answer, decided_by, duration_ms)
        return self.advance()

    def answer_visit_cap(self, block_id: str, answer: dict[str, Any], decided_by: str, duration_ms: int) -> str:
        """Run the capped block more times, or leave it. The answer stays out of `steps` and `history`."""
        self.frame["visit_cap_question"] = False
        self.log("block_completed", block=block_id, output=answer, decided_by=decided_by, duration_ms=duration_ms)
        self.info["attempts"] = 0
        block = self.skill_of(self.frame).blocks[block_id]
        if answer["choice"] == "more":
            extra_visits = self.frame.setdefault("extra_visits", {})
            extra_visits[block_id] = extra_visits.get(block_id, 0) + answer["rounds"]
            self.go_to(block_id, from_block=self.frame["arrived_from"], reason=self.frame["arrival_reason"] or "")
        else:
            self.move_on_from_cap(block)
        return self.advance()

    def record_task(self, block: ParallelBlock, index: int, answer: dict[str, Any]) -> int:
        """Store one task's answer and log it. Return how long the task took."""
        self.check_open_task(block, index)
        (self.frame["tasks"] or [])[index]["output"] = answer
        duration_ms = elapsed_ms_since(self.info["packet_issued_at"])
        self.log(
            "block_completed", block=block.id, task=index, output=answer, decided_by="agent", duration_ms=duration_ms
        )
        return duration_ms

    def complete_parallel(self, block: ParallelBlock, duration_ms: int) -> str:
        """Join the answers of every task into the block's results, then go on."""
        results = [task["output"] for task in self.frame["tasks"] or []]
        self.frame["tasks"] = None
        self.frame["skipped_tasks"] = None
        self.complete_block(block, {"results": results}, decided_by="agent", duration_ms=duration_ms)
        return self.advance()

    def accept_task(self, block: ParallelBlock, index: int, answer: dict[str, Any]) -> str:
        duration_ms = self.record_task(block, index, answer)
        tasks = self.frame["tasks"] or []
        open_indexes = self.open_task_indexes()
        if open_indexes:
            if self.adapter.can_spawn_subagents:
                done = len(tasks) - len(open_indexes)
                return f"Task {index} is recorded. {done} of {len(tasks)} tasks are done.\n"
            return self.issue_packet_for_next_task(block)
        next_text = self.complete_parallel(block, duration_ms)
        if self.adapter.can_spawn_subagents:
            # The last subagent must not see the next block: the main agent reads it with `current`.
            return f"Task {index} is recorded. All {len(tasks)} tasks are done.\n"
        return next_text

    def issue_packet_for_next_task(self, block: ParallelBlock) -> str:
        self.info["packet_issued_at"] = timestamp(utc_now())
        text = self.agent_packet(errors=[])
        self.log_block_started(block, packet=text, task=self.open_task_indexes()[0])
        return text

    def decided_by(self, block: AgentBlock, answered_by: str | None) -> str:
        if not isinstance(block, DecisionBlock) or block.decider == "agent":
            return "agent"
        if self.info["mode"] == "autonomous":
            return "agent_autonomous"
        return answered_by or "agent"


def is_true_or_stop(condition: str, context: dict[str, Any]) -> bool:
    try:
        return is_true(condition, context)
    except ComputedValueError as error:
        raise RunnerStop(f"The condition {condition!r} failed: {error}") from error
