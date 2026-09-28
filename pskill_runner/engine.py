"""The engine: runs a skill one block at a time (SPEC.md sections 4 and 7).

The public functions (`start_run`, `submit_answer`, ...) each load a run from disk, change it,
save it, and return the text to print. A `Run` object lives only for one command.
"""

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pskill_runner
from pskill_runner.adapters import adapter_for
from pskill_runner.computed_values import ComputedValueError, compute, is_true, render_text
from pskill_runner.field_types import FieldMap, FieldSpec, check_answer, check_typed_values
from pskill_runner.packets import AgentPacket, render_agent_packet, render_final_packet, render_pause_packet
from pskill_runner.project import Project
from pskill_runner.run_records import (
    ACTIVE_STATUSES,
    SCHEMA_VERSION,
    UNFINISHED_STATUSES,
    Frame,
    RunInfo,
    RunState,
    new_frame,
)
from pskill_runner.run_store import (
    append_event,
    copy_skill_snapshot,
    folder_hash,
    new_run_id,
    parse_timestamp,
    read_json,
    timestamp,
    utc_now,
    write_json_atomic,
)
from pskill_runner.shells import detect_shell
from pskill_runner.skill_loader import SkillLoadError, load_skill
from pskill_runner.skill_model import AnyBlock, DecisionBlock, Edge, EndBlock, Skill, TaskBlock
from pskill_runner.validator import validate_skill
from pskill_runner.yaml_loading import load_answer_yaml

ENTRY_SCRIPT_NAME = "pskill.py"


class RunError(Exception):
    """A command cannot run: an unknown run, a run in the wrong status, or an invalid skill."""


class RunnerStop(Exception):
    """A runner-side failure (a computed value, no matching edge, a visit cap). It pauses the run."""


# ---------------------------------------------------------------------------------------------
# Public commands
# ---------------------------------------------------------------------------------------------


def start_run(project: Project, skill_id: str, raw_inputs: dict[str, Any], mode: str, harness: str) -> tuple[str, str]:
    """Create a run and return its id and its first packet."""
    skill = load_valid_skill(project.skills_folder / skill_id)
    inputs = checked_inputs(skill, raw_inputs)
    now = utc_now()
    run_id = new_run_id(now)
    folder = project.runs_folder / run_id
    folder.mkdir(parents=True)
    copy_skill_snapshot(skill.folder, folder)
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
    run = Run(project, folder, info, RunState(frames=[new_frame(skill.id, inputs)]))
    run.log(
        "run_started",
        skill_id=skill.id,
        skill_hash=info["skill_hash"],
        inputs=inputs,
        mode=mode,
        harness=info["harness"],
        runner_version=info["runner_version"],
    )
    text = run.guarded(lambda: run.go_to_first_block(skill.entry))
    run.save()
    return run_id, text


def current_packet(project: Project, run_id: str | None) -> str:
    """Print the current packet again. This changes nothing."""
    return Run.load(project, resolve_run_id(project, run_id)).current_text()


def submit_answer(project: Project, run_id: str, answer_text: str) -> str:
    run = Run.load(project, run_id)
    text = run.submit(answer_text)
    run.save()
    return text


def pause_run(project: Project, run_id: str) -> str:
    run = Run.load(project, run_id)
    run.require_status(ACTIVE_STATUSES, "pause")
    text = run.pause("paused_by_user", None)
    run.save()
    return text


def resume_run(project: Project, run_id: str) -> str:
    run = Run.load(project, run_id)
    run.require_status(("paused",), "resume")
    run.info["attempts"] = 0
    run.info["stop_blocks"] = 0
    run.info["pause_reason"] = None
    run.info["pause_error"] = None
    run.log("run_resumed", reason="resumed_by_user")
    text = run.issue_packet(new_block=False)
    run.save()
    return text


def cancel_run(project: Project, run_id: str) -> str:
    run = Run.load(project, run_id)
    run.require_status(UNFINISHED_STATUSES, "cancel")
    run.end_run("cancelled", outputs={}, report=None)
    run.save()
    return f"Run {run_id} is cancelled. No more pskill commands are needed.\n"


def read_run_info(project: Project, run_id: str) -> RunInfo:
    return cast(RunInfo, read_json(run_folder(project, run_id) / "run.json"))


def read_run_state(project: Project, run_id: str) -> RunState:
    return cast(RunState, read_json(run_folder(project, run_id) / "state.json"))


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


def run_folder(project: Project, run_id: str) -> Path:
    folder = project.runs_folder / run_id
    if not (folder / "run.json").is_file():
        raise RunError(f"There is no run {run_id!r}. List the runs with `pskill runs`.")
    return folder


def load_valid_skill(folder: Path) -> Skill:
    if not (folder / "skill.yaml").is_file():
        raise RunError(f"There is no skill {folder.name!r}. List the skills with `pskill list`.")
    try:
        skill = load_skill(folder)
    except SkillLoadError as error:
        raise RunError(f"The skill {folder.name!r} is invalid:\n- " + "\n- ".join(error.problems)) from error
    errors = [f"{problem.location}: {problem.message}" for problem in validate_skill(skill) if problem.level == "error"]
    if errors:
        raise RunError(f"The skill {folder.name!r} is invalid:\n- " + "\n- ".join(errors))
    return skill


def checked_inputs(skill: Skill, raw_inputs: dict[str, Any]) -> dict[str, Any]:
    inputs, errors = check_answer(raw_inputs, skill.inputs)
    if errors:
        raise RunError("The inputs are invalid:\n- " + "\n- ".join(errors))
    for name, spec in skill.inputs.items():
        if name not in inputs and spec.default is not None:
            inputs[name] = spec.default
    return inputs


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
    """How the agent calls the runner, for example `uv run .pskill/pskill.py`."""
    entry_script = Path(pskill_runner.__file__).resolve().parent.parent / ENTRY_SCRIPT_NAME
    try:
        return f"uv run {entry_script.relative_to(project.root.resolve()).as_posix()}"
    except ValueError:
        return f"uv run {entry_script.as_posix()}"


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


# ---------------------------------------------------------------------------------------------
# One loaded run
# ---------------------------------------------------------------------------------------------


class Run:
    def __init__(self, project: Project, folder: Path, info: RunInfo, state: RunState) -> None:
        self.project = project
        self.folder = folder
        self.info = info
        self.state = state
        self.skills: dict[str, Skill] = {}
        self.adapter = adapter_for(info["harness"])

    @classmethod
    def load(cls, project: Project, run_id: str) -> "Run":
        folder = run_folder(project, run_id)
        return cls(project, folder, read_run_info(project, run_id), read_run_state(project, run_id))

    def save(self) -> None:
        self.info["updated_at"] = timestamp(utc_now())
        self.info["current_block"] = self.state["frames"][-1]["current_block"] if self.state["frames"] else None
        write_json_atomic(self.folder / "run.json", self.info)
        write_json_atomic(self.folder / "state.json", self.state)

    def log(self, event_type: str, **fields: Any) -> None:
        append_event(self.folder, event_type, frame=self.chain_text(), **fields)

    # --- reading the state -------------------------------------------------------------------

    @property
    def frame(self) -> Frame:
        return self.state["frames"][-1]

    def skill_of(self, frame: Frame) -> Skill:
        skill_id = frame["skill_id"]
        if skill_id not in self.skills:
            self.skills[skill_id] = load_skill(self.folder / "skills" / skill_id)
        return self.skills[skill_id]

    def chain(self) -> list[str]:
        return [frame["skill_id"] for frame in self.state["frames"]]

    def chain_text(self) -> str:
        return ">".join(self.chain())

    def current_block(self) -> AnyBlock:
        block_id = self.frame["current_block"]
        if block_id is None:
            raise RunError("The run has no current block.")
        return self.skill_of(self.frame).blocks[block_id]

    def context(self) -> dict[str, Any]:
        """The names that `{{ }}` values can read (SPEC.md section 7.1)."""
        frame = self.frame
        skill = self.skill_of(frame)
        return {
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

    def go_to_first_block(self, entry: list[Edge]) -> str:
        target, reason = self.choose_edge(entry)
        self.go_to(target, from_block=None, reason=reason)
        return self.advance()

    def choose_edge(self, edges: list[Edge]) -> tuple[str, str]:
        """Return the target of the first edge that applies, and why it applied."""
        for edge in edges:
            if edge.when is None:
                return edge.to, "always"
            try:
                if is_true(edge.when, self.context()):
                    return edge.to, edge.when
            except ComputedValueError as error:
                raise RunnerStop(f"The condition {edge.when!r} failed: {error}") from error
        raise RunnerStop("no edge matched: every edge has a when, and none of them is true")

    def go_to(self, target: str, from_block: str | None, reason: str) -> None:
        """Enter a block, following its visit cap (SPEC.md section 5.5)."""
        block = self.skill_of(self.frame).blocks[target]
        visits = self.frame["visits"].get(target, 0)
        if block.max_visits is not None and visits >= block.max_visits:
            if block.on_max_visits is None:
                raise RunnerStop(f"The block {target!r} reached its visit cap ({block.max_visits}).")
            self.go_to(block.on_max_visits, from_block=target, reason=f"visit cap of {target} ({block.max_visits})")
            return
        self.frame["visits"][target] = visits + 1
        self.frame["current_block"] = target
        self.frame["arrived_from"] = from_block
        self.frame["arrival_reason"] = reason

    def advance(self) -> str:
        """Continue from the current block: finish at an end block, or print the next agent packet."""
        block = self.current_block()
        if isinstance(block, EndBlock):
            return self.finish(block)
        return self.issue_packet(new_block=True)

    def log_block_started(self, block: AnyBlock, packet: str | None) -> None:
        self.log(
            "block_started",
            block=block.id,
            block_type=type(block).__name__.removesuffix("Block").lower(),
            visit=self.frame["visits"].get(block.id, 0),
            **{"from": self.frame["arrived_from"]},
            reason=self.frame["arrival_reason"],
            packet=packet,
        )

    def finish(self, block: EndBlock) -> str:
        skill = self.skill_of(self.frame)
        self.log_block_started(block, packet=None)
        try:
            outputs = compute(block.outputs, self.context())
            report = render_text(skill.instruction_text(block.report), self.context()) if block.report else None
        except ComputedValueError as error:
            raise RunnerStop(f"The end block {block.id!r} failed: {error}") from error
        errors = check_typed_values(outputs, skill.outputs)
        if errors:
            raise RunnerStop(f"The end block {block.id!r} gives invalid outputs: " + "; ".join(errors))
        self.log("block_completed", block=block.id, output=outputs, decided_by="runner", duration_ms=0)
        self.end_run(block.status, outputs, report)
        return render_final_packet(self.info["run_id"], skill.id, block.status, report, outputs)

    def end_run(self, status: str, outputs: dict[str, Any], report: str | None) -> None:
        now = utc_now()
        self.info["status"] = status
        self.info["outputs"] = outputs
        self.info["final_report"] = report
        self.info["ended_at"] = timestamp(now)
        duration_ms = int((now - parse_timestamp(self.info["created_at"])).total_seconds() * 1000)
        self.log("run_ended", status=status, outputs=outputs, duration_ms=duration_ms)

    # --- packets -------------------------------------------------------------------------------

    def issue_packet(self, new_block: bool) -> str:
        """Print the packet of the current agent block, and start its clock."""
        block = self.current_block()
        self.info["status"] = "waiting_for_human" if self.asks_the_human(block) else "active"
        self.info["packet_issued_at"] = timestamp(utc_now())
        text = self.agent_packet(errors=[])
        if new_block:
            self.info["attempts"] = 0
            self.log_block_started(block, packet=text)
        return text

    def agent_packet(self, errors: list[str]) -> str:
        block = self.current_block()
        if not isinstance(block, TaskBlock | DecisionBlock):
            raise RunError(f"The block {block.id!r} does not need the agent.")
        skill = self.skill_of(self.frame)
        try:
            instruction = render_text(skill.instruction_text(block.instruction), self.context())
        except ComputedValueError as error:
            raise RunnerStop(f"The instruction of {block.id!r} failed: {error}") from error
        return render_agent_packet(
            AgentPacket(
                run_id=self.info["run_id"],
                chain=self.chain(),
                block_id=block.id,
                visit=self.frame["visits"].get(block.id, 0),
                mode=self.info["mode"],
                goal=skill.goal,
                instruction=instruction,
                return_fields=self.return_fields(block),
                choices=block.choices if isinstance(block, DecisionBlock) else None,
                decider=block.decider if isinstance(block, DecisionBlock) else None,
                errors=errors,
                runner_command=runner_command(self.project),
                shell=detect_shell(),
                question_wording=self.adapter.question_wording,
            )
        )

    def return_fields(self, block: TaskBlock | DecisionBlock) -> FieldMap:
        if isinstance(block, DecisionBlock):
            return decision_fields(block, self.asks_the_human(block))
        return block.output

    def current_text(self) -> str:
        status = self.info["status"]
        if status in ACTIVE_STATUSES:
            return self.guarded(lambda: self.agent_packet(errors=[]))
        if status == "paused":
            return self.pause_text()
        return render_final_packet(
            self.info["run_id"], self.info["skill_id"], status, self.info["final_report"], self.info["outputs"] or {}
        )

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

    # --- submissions ---------------------------------------------------------------------------

    def submit(self, answer_text: str) -> str:
        self.require_status(ACTIVE_STATUSES, "take an answer (run `pskill resume` first)")
        block = self.current_block()
        if not isinstance(block, TaskBlock | DecisionBlock):
            raise RunError(f"The block {block.id!r} does not take an answer.")
        self.info["stop_blocks"] = 0
        try:
            raw_answer = load_answer_yaml(answer_text)
        except Exception as error:  # PyYAML raises several error types; all mean "not valid YAML"
            return self.reject([f"The answer is not valid YAML: {error}"], answer_text)
        if isinstance(raw_answer, dict) and "$cannot_complete" in raw_answer:
            reason = str(raw_answer["$cannot_complete"])
            return self.reject([f"You could not complete the block: {reason}"], answer_text)
        answered_by = raw_answer.pop("$answered_by", None) if isinstance(raw_answer, dict) else None
        value, errors = check_answer(raw_answer, self.return_fields(block))
        if self.asks_the_human(block) and answered_by not in ("human", "agent"):
            errors.append(
                "Add the line `$answered_by: human` (the user answered) or `$answered_by: agent` (you answered)."
            )
        if errors:
            return self.reject(errors, answer_text)
        return self.guarded(lambda: self.accept(block, value, answered_by))

    def reject(self, errors: list[str], answer_text: str) -> str:
        block_id = self.frame["current_block"]
        self.info["attempts"] += 1
        self.log("submission_rejected", block=block_id, errors=errors, raw=answer_text)
        if self.info["attempts"] > self.project.config.retries:
            return self.pause("block_failed", "\n".join(errors))
        return self.guarded(lambda: self.agent_packet(errors=errors))

    def accept(self, block: TaskBlock | DecisionBlock, value: dict[str, Any], answered_by: str | None) -> str:
        frame = self.frame
        frame["steps"][block.id] = value
        frame["history"].setdefault(block.id, []).append(value)
        issued_at = self.info["packet_issued_at"]
        duration_ms = int((utc_now() - parse_timestamp(issued_at)).total_seconds() * 1000) if issued_at else 0
        self.log(
            "block_completed",
            block=block.id,
            output=value,
            decided_by=self.decided_by(block, answered_by),
            duration_ms=duration_ms,
        )
        self.info["attempts"] = 0
        if isinstance(block.next, dict):
            target, reason = block.next[value["choice"]], f"choice {value['choice']}"
        else:
            target, reason = self.choose_edge(block.next)
        self.go_to(target, from_block=block.id, reason=reason)
        return self.advance()

    def decided_by(self, block: TaskBlock | DecisionBlock, answered_by: str | None) -> str:
        if not isinstance(block, DecisionBlock) or block.decider == "agent":
            return "agent"
        if self.info["mode"] == "autonomous":
            return "agent_autonomous"
        return answered_by or "agent"
