"""Tests for running script, call, and parallel blocks."""

import json
import threading
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from pskill_runner import engine
from pskill_runner.adapters import ADAPTERS, HarnessAdapter, TierRow, tier_wording
from pskill_runner.engine import (
    RunError,
    current_packet,
    pause_run,
    read_run_info,
    read_run_state,
    register_stop_attempt,
    resume_run,
    run_background_script,
    start_run,
    submit_answer,
    task_packet,
)
from pskill_runner.inline_executor import CallResult, ScriptResult
from pskill_runner.project import Config, Project, find_project
from pskill_runner.run_store import LOCK_FILE_NAME, read_events
from tests.skill_files import write_skill

SCRIPT_SKILL = """\
schema: pskill/v1
id: scripted
description: Runs a script.
goal: Read data with a script.
outputs:
  count: {type: integer, description: "How many files."}
entry: list_files
blocks:
  list_files:
    type: script
    run: [python, -c, "import json; print(json.dumps({'files': ['a.md', 'b.md']}))"]
    parse: json
    next: done
  done:
    type: end
    status: succeeded
    outputs: {count: "{{ steps.list_files.json.files | length }}"}
"""

PARENT_SKILL = """\
schema: pskill/v1
id: parent
description: Calls a child.
goal: Get a greeting from the child.
outputs:
  greeting: {type: string, description: "The child's greeting."}
entry: greet
blocks:
  greet:
    type: task
    instruction: "Say hello."
    output:
      text: {type: string, description: "The greeting."}
    next: child
  child:
    type: call
    skill: child
    inputs: {name: Ada}
    next:
      - when: "{{ steps.child.status == 'succeeded' }}"
        to: done
      - to: failed
  done:
    type: end
    status: succeeded
    outputs: {greeting: "{{ steps.child.outputs.greeting }}"}
  failed:
    type: end
    status: failed
"""

CHILD_SKILL = """\
schema: pskill/v1
id: child
description: Greets a person.
goal: Greet the person by name.
inputs:
  name: {type: string, description: "Who to greet."}
outputs:
  greeting: {type: string, description: "The greeting."}
entry: greet
blocks:
  greet:
    type: task
    instruction: "Greet {{ inputs.name }}. Earlier greeting: {{ steps.greet.text | default('none') }}."
    output:
      text: {type: string, description: "The greeting."}
    next: done
  done:
    type: end
    status: succeeded
    outputs: {greeting: "{{ steps.greet.text }}"}
"""

PARALLEL_SKILL = """\
schema: pskill/v1
id: fanout
description: Checks documents in parallel.
goal: Find the wrong claims.
inputs:
  files: {type: array, items: {type: string}, description: "The documents."}
outputs:
  wrong_count: {type: integer, description: "How many wrong claims."}
entry: check
blocks:
  check:
    type: task
    context: fresh
    for_each: "{{ inputs.files }}"
    agent: checker
    instruction: "Check every claim in {{ item }}."
    output:
      wrong: {type: array, items: {type: string}, description: "The wrong claims."}
    next: done
  done:
    type: end
    status: succeeded
    outputs: {wrong_count: "{{ steps.check.results | map(attribute='wrong') | map('length') | sum }}"}
"""

NAMED_PARALLEL_SKILL = PARALLEL_SKILL.replace(
    "    agent: checker\n", '    agent: checker\n    task_name: "Check {{ item }}"\n'
)


@pytest.fixture(autouse=True)
def adapter_with_subagents(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stand-in for a harness that can spawn subagents (the real ones come with their adapters)."""
    stand_in = HarnessAdapter(name="subagents-for-tests", question_wording="Ask the user.", can_spawn_subagents=True)
    monkeypatch.setitem(ADAPTERS, stand_in.name, stand_in)


def make_project(tmp_path: Path, skills: dict[str, str], agents: dict[str, str] | None = None) -> Project:
    for skill_id, skill_yaml in skills.items():
        write_skill(tmp_path / ".pskill" / "skills", skill_id, skill_yaml)
    agents_folder = tmp_path / ".pskill" / "agents"
    agents_folder.mkdir(parents=True, exist_ok=True)
    for name, text in (agents or {}).items():
        (agents_folder / f"{name}.md").write_text(text, encoding="utf-8")
    return find_project(tmp_path)


def test_a_script_result_lands_in_steps(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"scripted": SCRIPT_SKILL})

    run_id, packet = start_run(project, "scripted", {}, mode="interactive", harness="generic")

    assert "finished with status succeeded" in packet
    assert read_run_info(project, run_id)["outputs"] == {"count": 2}
    step = read_run_state(project, run_id)["frames"][0]["steps"]["list_files"]
    assert step["exit_code"] == 0
    assert step["json"] == {"files": ["a.md", "b.md"]}
    assert "script_ran" in [event["type"] for event in read_events(project.runs_folder / run_id)]


def test_a_failing_script_is_retried_then_pauses_the_run(tmp_path: Path) -> None:
    failing = SCRIPT_SKILL.replace(
        "\"import json; print(json.dumps({'files': ['a.md', 'b.md']}))\"", '"import sys; sys.exit(3)"'
    )
    project = make_project(tmp_path, {"scripted": failing})

    run_id, packet = start_run(project, "scripted", {}, mode="interactive", harness="generic")

    info = read_run_info(project, run_id)
    assert info["status"] == "paused"
    assert info["pause_reason"] == "block_failed"
    assert "exit code 3" in packet
    script_runs = [event for event in read_events(project.runs_folder / run_id) if event["type"] == "script_ran"]
    assert len(script_runs) == 3  # the first try plus 2 retries


def test_a_script_with_bad_json_fails(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"scripted": SCRIPT_SKILL.replace("print(json.dumps(", "print((")})

    run_id, packet = start_run(project, "scripted", {}, mode="interactive", harness="generic")

    assert read_run_info(project, run_id)["status"] == "paused"
    assert "not valid JSON" in packet


def test_a_json_script_over_the_output_limit_keeps_its_whole_value(tmp_path: Path) -> None:
    big_list = "\"import json; print(json.dumps({'files': ['x' * 40] * 2000}))\""
    project = make_project(
        tmp_path,
        {"scripted": SCRIPT_SKILL.replace("\"import json; print(json.dumps({'files': ['a.md', 'b.md']}))\"", big_list)},
    )

    run_id, packet = start_run(project, "scripted", {}, mode="interactive", harness="generic")

    assert "finished with status succeeded" in packet
    assert read_run_info(project, run_id)["outputs"] == {"count": 2000}
    step = read_run_state(project, run_id)["frames"][0]["steps"]["list_files"]
    assert len(step["stdout"]) > engine.OUTPUT_LIMIT_CHARACTERS
    script_ran = [event for event in read_events(project.runs_folder / run_id) if event["type"] == "script_ran"]
    assert script_ran[0]["stdout"] == step["stdout"]


CUT_NOTE = "\n[pskill cut this output: it keeps the first 65536 of 100001 characters.]\n"


def test_a_text_output_over_the_limit_is_cut_with_a_note(tmp_path: Path) -> None:
    long_text = (
        SCRIPT_SKILL.replace(
            "\"import json; print(json.dumps({'files': ['a.md', 'b.md']}))\"",
            "\"import sys; print('x' * 100_000); print('y' * 100_000, file=sys.stderr)\"",
        )
        .replace("    parse: json\n", "")
        .replace("steps.list_files.json.files | length", "steps.list_files.exit_code")
    )
    project = make_project(tmp_path, {"scripted": long_text})

    run_id, _ = start_run(project, "scripted", {}, mode="interactive", harness="generic")

    step = read_run_state(project, run_id)["frames"][0]["steps"]["list_files"]
    assert step["stdout"] == "x" * 65536 + CUT_NOTE
    assert step["stderr"] == "y" * 65536 + CUT_NOTE
    script_ran = [event for event in read_events(project.runs_folder / run_id) if event["type"] == "script_ran"]
    assert (script_ran[0]["stdout"], script_ran[0]["stderr"]) == (step["stdout"], step["stderr"])


def test_a_failed_script_over_the_limit_shows_the_real_end_of_its_stderr(tmp_path: Path) -> None:
    failing = SCRIPT_SKILL.replace(
        "\"import json; print(json.dumps({'files': ['a.md', 'b.md']}))\"",
        "\"import sys; print('y' * 100_000 + ' the real end', file=sys.stderr); sys.exit(3)\"",
    )
    project = make_project(tmp_path, {"scripted": failing})

    _, packet = start_run(project, "scripted", {}, mode="interactive", harness="generic")

    assert "the real end" in packet


STDIN_SKILL = """\
schema: pskill/v1
id: piped
description: Gives a script its input on stdin.
goal: Hand data to a script.
inputs:
  pr: {type: integer, description: "The pull request."}
  body: {type: string, description: "A text."}
outputs:
  received: {type: string, description: "What the script printed."}
entry: read_input
blocks:
  read_input:
    type: script
    run: [python, -c, "import sys; print(sys.stdin.read())"]
    input: {pr: "{{ inputs.pr }}", labels: [bug, "{{ inputs.body | length }}"]}
    next: done
  done:
    type: end
    status: succeeded
    outputs: {received: "{{ steps.read_input.stdout }}"}
"""


def script_output(tmp_path: Path, skill_yaml: str, body: str = "hello") -> str:
    project = make_project(tmp_path, {"piped": skill_yaml})
    run_id, _ = start_run(project, "piped", {"pr": "7", "body": body}, mode="interactive", harness="generic")
    outputs = read_run_info(project, run_id)["outputs"]
    assert outputs is not None
    return str(outputs["received"])


def test_a_script_reads_a_mapping_input_as_one_json_object_on_stdin(tmp_path: Path) -> None:
    assert json.loads(script_output(tmp_path, STDIN_SKILL)) == {"pr": 7, "labels": ["bug", 5]}


def test_a_script_reads_a_text_input_as_it_is(tmp_path: Path) -> None:
    skill_yaml = STDIN_SKILL.replace(
        '{pr: "{{ inputs.pr }}", labels: [bug, "{{ inputs.body | length }}"]}', '"{{ inputs.body }}"'
    )

    assert script_output(tmp_path, skill_yaml, body="line one\nline two") == "line one\nline two\n"


def test_a_long_input_is_not_limited_by_the_command_line(tmp_path: Path) -> None:
    skill_yaml = STDIN_SKILL.replace("print(sys.stdin.read())", "print(len(sys.stdin.read()))").replace(
        '{pr: "{{ inputs.pr }}", labels: [bug, "{{ inputs.body | length }}"]}', '"{{ inputs.body }}"'
    )

    assert script_output(tmp_path, skill_yaml, body="x" * 100_000) == "100000\n"


def test_a_script_reads_its_input_as_utf_8_on_every_system(tmp_path: Path) -> None:
    skill_yaml = STDIN_SKILL.replace(
        "print(sys.stdin.read())", "print(sys.stdin.read() == 'caf\\\\u00e9 \\\\U0001f440')"
    ).replace('{pr: "{{ inputs.pr }}", labels: [bug, "{{ inputs.body | length }}"]}', '"{{ inputs.body }}"')

    assert script_output(tmp_path, skill_yaml, body="café \U0001f440") == "True\n"


def test_a_script_without_input_reads_an_empty_stdin(tmp_path: Path) -> None:
    skill_yaml = STDIN_SKILL.replace("print(sys.stdin.read())", "print(repr(sys.stdin.read()))").replace(
        '    input: {pr: "{{ inputs.pr }}", labels: [bug, "{{ inputs.body | length }}"]}\n', ""
    )

    assert script_output(tmp_path, skill_yaml) == "''\n"


def test_a_script_gets_no_copy_of_the_run_state(tmp_path: Path) -> None:
    skill_yaml = STDIN_SKILL.replace("print(sys.stdin.read())", "import os; print('PSKILL_STATE_FILE' in os.environ)")
    project = make_project(tmp_path, {"piped": skill_yaml})

    run_id, _ = start_run(project, "piped", {"pr": "7", "body": "hello"}, mode="interactive", harness="generic")

    assert read_run_info(project, run_id)["outputs"] == {"received": "False\n"}
    assert not (project.runs_folder / run_id / "script-state.json").exists()


def test_the_trace_records_the_input_that_a_script_got(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"piped": STDIN_SKILL})

    run_id, _ = start_run(project, "piped", {"pr": "7", "body": "hello"}, mode="interactive", harness="generic")

    script_run = next(event for event in read_events(project.runs_folder / run_id) if event["type"] == "script_ran")
    assert script_run["input"] == {"pr": 7, "labels": ["bug", 5]}


def test_a_call_runs_the_child_and_returns_its_status_and_outputs(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"parent": PARENT_SKILL, "child": CHILD_SKILL})
    run_id, _ = start_run(project, "parent", {}, mode="interactive", harness="generic")

    child_packet = submit_answer(project, run_id, "text: Hello from the parent.\n")
    assert "· parent > child · greet (visit 1)" in child_packet
    assert "Goal\nGreet the person by name." in child_packet
    assert "Greet Ada. Earlier greeting: none." in child_packet

    final = submit_answer(project, run_id, "text: Hello, Ada!\n")

    assert "finished with status succeeded" in final
    assert read_run_info(project, run_id)["outputs"] == {"greeting": "Hello, Ada!"}
    parent_frame = read_run_state(project, run_id)["frames"][0]
    assert parent_frame["steps"]["child"] == {"status": "succeeded", "outputs": {"greeting": "Hello, Ada!"}}


def test_parallel_with_subagents_lists_every_task_and_waits_for_all(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": PARALLEL_SKILL}, {"checker": "You check facts carefully."})
    run_id, packet = start_run(
        project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="subagents-for-tests"
    )

    assert "Spawn one subagent per task" in packet
    assert "#### Task 0" in packet and "#### Task 1" in packet
    assert f"task {run_id} 1`" in packet
    assert "Check every claim in b.md." not in packet

    waiting = submit_answer(project, run_id, "wrong:\n  - The sky is green.\n", task=1)
    assert "1 of 2 tasks are done" in waiting
    assert read_run_info(project, run_id)["status"] == "active"

    last_task = submit_answer(project, run_id, "wrong: []\n", task=0)
    assert last_task == "Task 0 is recorded. All 2 tasks are done.\n"
    assert "finished with status succeeded" in current_packet(project, run_id)
    assert read_run_info(project, run_id)["outputs"] == {"wrong_count": 1}
    results = read_run_state(project, run_id)["frames"][0]["steps"]["check"]["results"]
    assert results == [{"wrong": []}, {"wrong": ["The sky is green."]}]


def test_parallel_without_subagents_gives_one_task_at_a_time(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": PARALLEL_SKILL}, {"checker": "You check facts carefully."})
    run_id, packet = start_run(project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="generic")

    assert "Spawn one subagent" not in packet
    assert "Check every claim in a.md." in packet
    assert "--task 0" in packet

    second = submit_answer(project, run_id, "wrong: []\n", task=0)
    assert "Check every claim in b.md." in second
    assert "--task 1" in second
    assert "Check every claim in b.md." in current_packet(project, run_id)

    final = submit_answer(project, run_id, "wrong: [x]\n", task=1)
    assert "finished with status succeeded" in final


def test_an_empty_parallel_list_completes_at_once(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": PARALLEL_SKILL}, {"checker": "You check facts."})

    run_id, packet = start_run(project, "fanout", {"files": []}, mode="interactive", harness="generic")

    assert "finished with status succeeded" in packet
    assert read_run_state(project, run_id)["frames"][0]["steps"]["check"] == {"results": []}


def test_a_parallel_answer_needs_its_task_number(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": PARALLEL_SKILL}, {"checker": "You check facts."})
    run_id, _ = start_run(project, "fanout", {"files": ["a.md"]}, mode="interactive", harness="generic")

    packet = submit_answer(project, run_id, "wrong: []\n")

    assert "--task" in packet.split("### Errors")[1]


def test_the_lock_keeps_every_concurrent_task_submission(tmp_path: Path) -> None:
    files = [f"doc{index}.md" for index in range(8)]
    project = make_project(tmp_path, {"fanout": PARALLEL_SKILL}, {"checker": "You check facts."})
    run_id, _ = start_run(project, "fanout", {"files": files}, mode="interactive", harness="subagents-for-tests")

    threads = [
        threading.Thread(
            target=submit_answer, args=(project, run_id, f"wrong: [claim {index}]\n"), kwargs={"task": index}
        )
        for index in range(len(files))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert read_run_info(project, run_id)["outputs"] == {"wrong_count": 8}
    results = read_run_state(project, run_id)["frames"][0]["steps"]["check"]["results"]
    assert [result["wrong"] for result in results] == [[f"claim {index}"] for index in range(8)]


HARNESS_TOOL_NAMES = ("AskUserQuestion", "Agent tool", "subagent_type", "spawn_agent")


def test_generic_packets_name_no_harness_tool(tmp_path: Path) -> None:
    project = make_project(
        tmp_path,
        {"parent": PARENT_SKILL, "child": CHILD_SKILL, "fanout": PARALLEL_SKILL},
        {"checker": "You check facts."},
    )
    _, parallel_packet = start_run(
        project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="generic"
    )
    _, task_packet = start_run(project, "parent", {}, mode="interactive", harness="generic")

    for packet in (parallel_packet, task_packet):
        assert not any(tool_name in packet for tool_name in HARNESS_TOOL_NAMES), packet


def test_a_script_with_its_own_retries_runs_that_many_extra_times(tmp_path: Path) -> None:
    failing = SCRIPT_SKILL.replace(
        "\"import json; print(json.dumps({'files': ['a.md', 'b.md']}))\"", '"import sys; sys.exit(3)"'
    ).replace("    parse: json\n", "    parse: json\n    retries: 0\n")
    project = make_project(tmp_path, {"scripted": failing})

    run_id, _ = start_run(project, "scripted", {}, mode="interactive", harness="generic")

    script_runs = [event for event in read_events(project.runs_folder / run_id) if event["type"] == "script_ran"]
    assert len(script_runs) == 1


def test_a_script_with_its_own_timeout_stops_after_it(tmp_path: Path) -> None:
    slow = SCRIPT_SKILL.replace(
        "\"import json; print(json.dumps({'files': ['a.md', 'b.md']}))\"", '"import time; time.sleep(10)"'
    ).replace("    parse: json\n", "    parse: json\n    retries: 0\n    timeout_s: 1\n")
    project = make_project(tmp_path, {"scripted": slow})

    run_id, packet = start_run(project, "scripted", {}, mode="interactive", harness="generic")

    assert read_run_info(project, run_id)["status"] == "paused"
    assert "within 1 s" in packet


def test_each_parallel_task_gets_the_name_that_task_name_computes(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": NAMED_PARALLEL_SKILL}, {"checker": "You check facts."})

    run_id, packet = start_run(
        project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="subagents-for-tests"
    )

    assert "#### Task 0 · Check a.md\n" in packet and "#### Task 1 · Check b.md\n" in packet
    tasks = read_run_state(project, run_id)["frames"][0]["tasks"] or []
    assert [task["name"] for task in tasks] == ["Check a.md", "Check b.md"]
    started = [event for event in read_events(project.runs_folder / run_id) if event["type"] == "block_started"]
    assert started[-1]["task_names"] == ["Check a.md", "Check b.md"]


@pytest.mark.parametrize("task_name", ["{{ item.name }}", "   ", "{{ '' }}"])
def test_a_task_name_that_fails_or_is_empty_leaves_the_task_unnamed(tmp_path: Path, task_name: str) -> None:
    skill_yaml = NAMED_PARALLEL_SKILL.replace("Check {{ item }}", task_name)
    project = make_project(tmp_path, {"fanout": skill_yaml}, {"checker": "You check facts."})

    run_id, packet = start_run(
        project, "fanout", {"files": ["a.md"]}, mode="interactive", harness="subagents-for-tests"
    )

    assert read_run_info(project, run_id)["status"] == "active"
    assert "#### Task 0\n" in packet
    assert (read_run_state(project, run_id)["frames"][0]["tasks"] or [])[0]["name"] is None
    started = [event for event in read_events(project.runs_folder / run_id) if event["type"] == "block_started"]
    assert "task_names" not in started[-1]


def test_a_long_task_name_is_one_short_line(tmp_path: Path) -> None:
    skill_yaml = NAMED_PARALLEL_SKILL.replace("Check {{ item }}", "Check\n  {{ item }} {{ 'x' * 80 }}")
    project = make_project(tmp_path, {"fanout": skill_yaml}, {"checker": "You check facts."})

    run_id, _ = start_run(project, "fanout", {"files": ["a.md"]}, mode="interactive", harness="subagents-for-tests")

    name = (read_run_state(project, run_id)["frames"][0]["tasks"] or [])[0]["name"] or ""
    assert name.startswith("Check a.md xxx") and "\n" not in name
    assert len(name) == 60 and name.endswith("…")


def test_a_task_submission_never_changes_the_owner_session(tmp_path: Path) -> None:
    """A parallel task comes from a subagent, which may have its own session id."""
    project = make_project(tmp_path, {"fanout": PARALLEL_SKILL}, {"checker": "You check facts carefully."})
    run_id, _ = start_run(
        project,
        "fanout",
        {"files": ["a.md", "b.md"]},
        mode="interactive",
        harness="subagents-for-tests",
        session_id="main-session",
    )

    submit_answer(project, run_id, "wrong: []\n", task=1, session_id="subagent-session")

    assert read_run_info(project, run_id)["session_id"] == "main-session"


def test_the_first_packet_of_a_child_skill_shows_its_goal_once(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"parent": PARENT_SKILL, "child": CHILD_SKILL})
    run_id, first = start_run(project, "parent", {}, mode="interactive", harness="generic")

    child_packet = submit_answer(project, run_id, "text: Hello from the parent.\n")
    retry = submit_answer(project, run_id, "wrong_field: x\n")

    assert "### Goal" not in first
    assert "### Goal\nGreet the person by name." in child_packet
    assert "### Errors" in retry
    assert "### Goal" not in retry


PICKED_PARALLEL_SKILL = """\
schema: pskill/v1
id: picked
description: Runs only the reviewers that the change needs.
goal: Review the change.
inputs:
  paths: {type: array, items: {type: string}, description: "The changed paths."}
outputs:
  count: {type: integer, description: "How many reviews ran."}
entry: review
blocks:
  review:
    type: task
    context: fresh
    for_each:
      - {name: always}
      - {name: api, when: "{{ inputs.paths | select('matches', '^api/') | list }}"}
      - {name: docs, when: "{{ inputs.paths | select('matches', '^docs/') | list }}"}
    task_name: "{{ item.name }}"
    instruction: "Review as {{ item.name }}."
    output:
      ok: {type: boolean, description: "True when the review is done."}
    next: done
  done:
    type: end
    status: succeeded
    outputs: {count: "{{ steps.review.results | length }}"}
"""


def test_a_parallel_item_runs_only_when_its_when_is_true(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"picked": PICKED_PARALLEL_SKILL})

    run_id, packet = start_run(
        project, "picked", {"paths": ["api/a.ts"]}, mode="interactive", harness="subagents-for-tests"
    )

    assert "#### Task 0 · always\n" in packet and "#### Task 1 · api\n" in packet
    assert "docs" not in packet
    tasks = read_run_state(project, run_id)["frames"][0]["tasks"] or []
    assert [task["item"] for task in tasks] == [{"name": "always"}, {"name": "api"}]
    started = [event for event in read_events(project.runs_folder / run_id) if event["type"] == "block_started"]
    assert started[-1]["skipped_tasks"] == [
        {"name": "docs", "when": "{{ inputs.paths | select('matches', '^docs/') | list }}"}
    ]


def test_a_parallel_block_whose_items_are_all_skipped_completes_at_once(tmp_path: Path) -> None:
    skill_yaml = PICKED_PARALLEL_SKILL.replace("      - {name: always}\n", "")
    project = make_project(tmp_path, {"picked": skill_yaml})

    run_id, packet = start_run(project, "picked", {"paths": ["sdk/a.py"]}, mode="interactive", harness="generic")

    assert "finished with status succeeded" in packet
    assert read_run_info(project, run_id)["outputs"] == {"count": 0}
    events = read_events(project.runs_folder / run_id)
    started = next(event for event in events if event["type"] == "block_started" and event["block"] == "review")
    assert [task["name"] for task in started["skipped_tasks"]] == ["api", "docs"]


def test_the_task_command_gives_the_full_prompt_of_one_open_task(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": PARALLEL_SKILL}, {"checker": "You check facts carefully."})
    run_id, _ = start_run(
        project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="subagents-for-tests"
    )

    prompt = task_packet(project, run_id, 1)

    assert f"Work in the folder `{project.root.as_posix()}`." in prompt
    assert "You check facts carefully." in prompt
    assert "Check every claim in b.md." in prompt
    assert f"submit {run_id} --task 1" in prompt


def test_the_task_command_refuses_a_task_that_already_has_an_answer(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": PARALLEL_SKILL}, {"checker": "You check facts."})
    run_id, _ = start_run(
        project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="subagents-for-tests"
    )
    submit_answer(project, run_id, "wrong: []\n", task=0)

    with pytest.raises(RunError, match=r"Task 0 .* already has an answer"):
        task_packet(project, run_id, 0)


def stop_until_paused(project: Project, run_id: str) -> None:
    while register_stop_attempt(project, run_id):
        pass


def test_a_run_paused_by_stop_attempts_still_records_task_answers(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": PARALLEL_SKILL}, {"checker": "You check facts."})
    run_id, _ = start_run(
        project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="subagents-for-tests"
    )
    stop_until_paused(project, run_id)
    assert read_run_info(project, run_id)["pause_reason"] == "agent_stopped"

    answer_file = project.runs_folder / run_id / "answers" / "check-task-1.yaml"
    answer_file.write_text("wrongs: [x]\n", encoding="utf-8")
    rejected = submit_answer(project, run_id, "wrongs: [x]\n", task=1, answer_file=answer_file)
    assert "not recorded" in rejected and answer_file.exists()  # a rejected answer keeps its file
    answer_file.write_text("wrong: [x]\n", encoding="utf-8")

    first = submit_answer(project, run_id, "wrong: [x]\n", task=1, answer_file=answer_file)
    last = submit_answer(project, run_id, "wrong: []\n", task=0)

    assert "Task 1 is recorded" in first and "Task 0 is recorded" in last
    assert not answer_file.exists()  # a task answer recorded while paused loses its file too
    assert read_run_info(project, run_id)["status"] == "paused"  # only resume advances
    assert "finished with status succeeded" in resume_run(project, run_id)
    assert read_run_info(project, run_id)["outputs"] == {"wrong_count": 1}


def test_a_run_paused_by_the_user_takes_no_task_answer(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": PARALLEL_SKILL}, {"checker": "You check facts."})
    run_id, _ = start_run(project, "fanout", {"files": ["a.md"]}, mode="interactive", harness="subagents-for-tests")
    pause_run(project, run_id)

    with pytest.raises(RunError, match="resume"):
        submit_answer(project, run_id, "wrong: []\n", task=0)


def test_a_text_script_keeps_its_output_as_text(tmp_path: Path) -> None:
    text_script = (
        SCRIPT_SKILL.replace(
            "\"import json; print(json.dumps({'files': ['a.md', 'b.md']}))\"", "\"print('a.md b.md c.md')\""
        )
        .replace("    parse: json\n", "")
        .replace("steps.list_files.json.files", "steps.list_files.stdout.split()")
    )
    project = make_project(tmp_path, {"scripted": text_script})

    run_id, packet = start_run(project, "scripted", {}, mode="interactive", harness="generic")

    assert "finished with status succeeded" in packet
    assert read_run_info(project, run_id)["outputs"] == {"count": 3}
    step = read_run_state(project, run_id)["frames"][0]["steps"]["list_files"]
    assert step == {"exit_code": 0, "stdout": "a.md b.md c.md\n", "stderr": ""}


FAILS_ON_THE_FIRST_RUN = (
    "import pathlib, sys; marker = pathlib.Path('ran-once'); ran = marker.exists(); marker.touch(); "
    "sys.exit(0 if ran else 3)"
)


def test_resume_runs_a_failed_script_again(tmp_path: Path) -> None:
    skill_yaml = (
        SCRIPT_SKILL.replace(
            "\"import json; print(json.dumps({'files': ['a.md', 'b.md']}))\"", f'"{FAILS_ON_THE_FIRST_RUN}"'
        )
        .replace("    parse: json\n", "    retries: 0\n")
        .replace("steps.list_files.json.files | length", "steps.list_files.exit_code")
    )
    project = make_project(tmp_path, {"scripted": skill_yaml})
    run_id, first = start_run(project, "scripted", {}, mode="interactive", harness="generic")
    assert "exit code 3" in first

    resumed = resume_run(project, run_id)

    assert "finished with status succeeded" in resumed
    assert read_run_info(project, run_id)["outputs"] == {"count": 0}
    script_runs = [event for event in read_events(project.runs_folder / run_id) if event["type"] == "script_ran"]
    assert [event["exit_code"] for event in script_runs] == [3, 0]


TWICE_SKILL = """\
schema: pskill/v1
id: twice
description: Calls the same child two times.
goal: Get two greetings.
outputs:
  greeting: {type: string, description: "The second greeting."}
entry: first
blocks:
  first:
    type: call
    skill: child
    inputs: {name: Ada}
    next: second
  second:
    type: call
    skill: child
    inputs: {name: Grace}
    next: done
  done:
    type: end
    status: succeeded
    outputs: {greeting: "{{ steps.second.outputs.greeting }}"}
"""


def test_a_skill_that_calls_one_child_twice_copies_the_child_once(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"twice": TWICE_SKILL, "child": CHILD_SKILL})
    run_id, first = start_run(project, "twice", {}, mode="interactive", harness="generic")

    second = submit_answer(project, run_id, "text: Hello, Ada!\n")
    final = submit_answer(project, run_id, "text: Hello, Grace!\n")

    assert "Greet Ada." in first and "Greet Grace." in second
    assert "finished with status succeeded" in final
    assert read_run_info(project, run_id)["outputs"] == {"greeting": "Hello, Grace!"}
    assert sorted(path.name for path in (project.runs_folder / run_id / "skills").iterdir()) == ["child", "twice"]


class ReadyChildResults:
    """An executor that answers every call with a ready result, as `pskill test` does."""

    def run_script(
        self,
        block_id: str,
        argv: list[str],
        cwd: Path,
        env: dict[str, str],
        timeout_s: int,
        stdin_text: str | None = None,
    ) -> ScriptResult:
        raise AssertionError("This test runs no script.")

    def call_result(self, block_id: str, skill_id: str, inputs: dict[str, Any]) -> CallResult | None:
        return CallResult(status="succeeded", outputs={"greeting": f"Ready hello to {inputs['name']}."})


def test_a_ready_call_result_completes_the_call_without_the_child(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"parent": PARENT_SKILL, "child": CHILD_SKILL})
    run_id, _ = start_run(project, "parent", {}, mode="interactive", harness="generic")

    final = submit_answer(project, run_id, "text: Hello from the parent.\n", executor=ReadyChildResults())

    assert "finished with status succeeded" in final
    assert read_run_info(project, run_id)["outputs"] == {"greeting": "Ready hello to Ada."}
    frames = {event["frame"] for event in read_events(project.runs_folder / run_id)}
    assert frames == {"parent"}  # the child skill never ran


def test_call_inputs_of_the_wrong_type_pause_the_run(tmp_path: Path) -> None:
    parent = PARENT_SKILL.replace("inputs: {name: Ada}", 'inputs: {name: "{{ 42 }}"}')
    project = make_project(tmp_path, {"parent": parent, "child": CHILD_SKILL})
    run_id, _ = start_run(project, "parent", {}, mode="interactive", harness="generic")

    packet = submit_answer(project, run_id, "text: Hello from the parent.\n")

    assert read_run_info(project, run_id)["pause_reason"] == "runner_error"
    assert "The inputs of 'child' are invalid: " in packet
    assert len(read_run_state(project, run_id)["frames"]) == 1


def test_a_for_each_that_gives_no_list_pauses_the_run(tmp_path: Path) -> None:
    skill_yaml = PARALLEL_SKILL.replace('for_each: "{{ inputs.files }}"', 'for_each: "{{ inputs.files | length }}"')
    project = make_project(tmp_path, {"fanout": skill_yaml}, {"checker": "You check facts."})

    run_id, packet = start_run(project, "fanout", {"files": ["a.md"]}, mode="interactive", harness="generic")

    assert read_run_info(project, run_id)["pause_reason"] == "runner_error"
    assert "The for_each of 'check' must give a list, not int." in packet


def test_a_missing_agent_file_pauses_the_run(tmp_path: Path) -> None:
    skill_yaml = PARALLEL_SKILL.replace("agent: checker", "agent: \"{{ 'checker' }}\"")
    project = make_project(tmp_path, {"fanout": skill_yaml})

    run_id, packet = start_run(project, "fanout", {"files": ["a.md"]}, mode="interactive", harness="generic")

    assert read_run_info(project, run_id)["pause_reason"] == "runner_error"
    assert "There is no agent file 'checker.md' in .pskill/agents/." in packet


LOOPING_SKILL = """\
schema: pskill/v1
id: looping
description: Two empty parallel blocks that go to each other.
goal: Never reach an agent block.
inputs:
  files: {type: array, items: {type: string}, description: "The documents."}
entry: first
blocks:
  first:
    type: task
    context: fresh
    for_each: "{{ inputs.files }}"
    instruction: "Check {{ item }}."
    max_visits: 50
    on_max_visits: done
    output:
      ok: {type: boolean, description: "True when done."}
    next: second
  second:
    type: task
    context: fresh
    for_each: "{{ inputs.files }}"
    instruction: "Check {{ item }} again."
    output:
      ok: {type: boolean, description: "True when done."}
    next:
      - when: "{{ inputs.files }}"
        to: done
      - to: first
  done:
    type: end
    status: succeeded
"""


def test_too_many_runner_blocks_in_a_row_pause_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "INLINE_BLOCK_LIMIT", 10)
    project = make_project(tmp_path, {"looping": LOOPING_SKILL})

    run_id, packet = start_run(project, "looping", {"files": []}, mode="interactive", harness="generic")

    assert read_run_info(project, run_id)["pause_reason"] == "runner_error"
    assert "More than 10 runner blocks ran without an agent block." in packet
    assert read_run_state(project, run_id)["frames"][0]["visits"] == {"first": 6, "second": 5}


def test_the_task_command_still_serves_a_run_paused_by_stop_attempts(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": PARALLEL_SKILL}, {"checker": "You check facts carefully."})
    run_id, _ = start_run(
        project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="subagents-for-tests"
    )
    stop_until_paused(project, run_id)

    prompt = task_packet(project, run_id, 1)

    assert "Check every claim in b.md." in prompt
    assert read_run_info(project, run_id)["status"] == "paused"


def test_the_task_command_refuses_a_task_number_out_of_range(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": PARALLEL_SKILL}, {"checker": "You check facts."})
    run_id, _ = start_run(
        project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="subagents-for-tests"
    )

    with pytest.raises(RunError, match=r"The block 'check' has no task 5 \(tasks 0 to 1\)\."):
        task_packet(project, run_id, 5)


def test_an_invalid_task_answer_counts_against_that_task_only(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": PARALLEL_SKILL}, {"checker": "You check facts."})
    run_id, _ = start_run(project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="generic")

    packet = submit_answer(project, run_id, "wrong: not a list\n", task=1)

    assert "### Errors" in packet
    rejected = [event for event in read_events(project.runs_folder / run_id) if event["type"] == "submission_rejected"]
    assert [event["task"] for event in rejected] == [1]
    tasks = read_run_state(project, run_id)["frames"][0]["tasks"] or []
    assert [(task["output"], task["attempts"]) for task in tasks] == [(None, 0), (None, 1)]
    assert read_run_info(project, run_id)["attempts"] == 0


def test_an_invalid_task_answer_is_not_recorded_while_stop_attempts_pause_the_run(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": PARALLEL_SKILL}, {"checker": "You check facts."})
    run_id, _ = start_run(
        project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="subagents-for-tests"
    )
    stop_until_paused(project, run_id)

    text = submit_answer(project, run_id, "wrong: not a list\n", task=0)

    assert text.startswith("Task 0 is not recorded. Fix these problems and submit again:\n- ")
    assert (read_run_state(project, run_id)["frames"][0]["tasks"] or [])[0]["output"] is None


def test_a_rejected_task_answer_tells_the_subagent_what_to_fix(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": PARALLEL_SKILL}, {"checker": "You check facts."})
    run_id, _ = start_run(
        project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="subagents-for-tests"
    )

    reply = submit_answer(project, run_id, "wrong: 3\n", task=1)

    assert reply.startswith("Task 1 is not recorded. Fix these problems and submit again:\n- wrong")
    assert read_run_info(project, run_id)["status"] == "active"


SCRIPT_LOOP_SKILL = """\
schema: pskill/v1
id: script-loop
description: Runs a script again and again.
goal: Count.
entry: count
blocks:
  count:
    type: script
    run: [python, -c, "print('one more')"]
    max_visits: 2
    on_max_visits: done
    next: count
  done:
    type: end
    status: succeeded
"""


def test_a_script_at_its_cap_asks_and_the_question_survives_current_and_resume(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"script-loop": SCRIPT_LOOP_SKILL})

    run_id, packet = start_run(project, "script-loop", {}, mode="interactive", harness="generic")

    assert "`count` reached its visit limit: it ran 2 times." in packet
    assert read_run_info(project, run_id)["status"] == "waiting_for_human"
    assert "`count` reached its visit limit" in current_packet(project, run_id)
    pause_run(project, run_id)
    assert "`count` reached its visit limit" in resume_run(project, run_id)
    packet = submit_answer(project, run_id, "choice: move_on\nrationale: Two runs are enough.\n$answered_by: human\n")
    assert read_run_info(project, run_id)["status"] == "succeeded"


def test_the_cap_question_of_a_script_ignores_the_script_retries(tmp_path: Path) -> None:
    skill_yaml = SCRIPT_LOOP_SKILL.replace("    max_visits: 2\n", "    max_visits: 2\n    retries: 0\n")
    project = make_project(tmp_path, {"script-loop": skill_yaml})
    run_id, _ = start_run(project, "script-loop", {}, mode="interactive", harness="generic")

    packet = submit_answer(project, run_id, "choice: maybe\n$answered_by: human\n")

    assert read_run_info(project, run_id)["status"] == "waiting_for_human"
    assert "`count` reached its visit limit" in packet


def tiered_skill(tier: str) -> str:
    return PARALLEL_SKILL.replace("    agent: checker\n", f"    agent: checker\n    tier: {tier}\n")


def task_tiers(project: Project, run_id: str) -> list[str | None]:
    return [task.get("tier") for task in read_run_state(project, run_id)["frames"][0]["tasks"] or []]


def test_a_tier_asks_claude_code_for_its_model_on_each_agent_call(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": tiered_skill("standard")}, {"checker": "You check facts."})

    run_id, packet = start_run(
        project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="claude-code"
    )

    assert packet.count("`model: sonnet`") == 2
    assert task_tiers(project, run_id) == ["standard", "standard"]


def test_a_tier_asks_codex_for_its_reasoning_effort(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": tiered_skill("deep")}, {"checker": "You check facts."})

    _, packet = start_run(project, "fanout", {"files": ["a.md"]}, mode="interactive", harness="codex")

    assert "Pass `reasoning_effort: high` in this task's spawn_agent call." in packet


def test_a_project_tier_row_sets_the_model_and_effort_of_that_tier_only(tmp_path: Path) -> None:
    skill_yaml = tiered_skill("\"{{ 'fast' if item == 'a.md' else 'deep' }}\"")
    project = make_project(tmp_path, {"fanout": skill_yaml}, {"checker": "You check facts."})
    tiers = {"codex": {"fast": TierRow(model="gpt-6-luna", effort="low")}}
    project = replace(project, config=Config(tiers=tiers))

    _, packet = start_run(project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="codex")

    task_zero, task_one = packet.split("#### Task 1")
    assert "Pass `model: gpt-6-luna` and `reasoning_effort: low` in this task's spawn_agent call." in task_zero
    assert "Pass `reasoning_effort: high` in this task's spawn_agent call." in task_one


def test_a_block_with_no_tier_asks_for_no_model(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": PARALLEL_SKILL}, {"checker": "You check facts."})

    run_id, packet = start_run(project, "fanout", {"files": ["a.md"]}, mode="interactive", harness="claude-code")

    assert "`model:" not in packet
    assert task_tiers(project, run_id) == [None]


def test_each_item_can_ask_for_its_own_tier(tmp_path: Path) -> None:
    skill_yaml = tiered_skill("\"{{ 'deep' if item == 'a.md' else 'fast' }}\"")
    project = make_project(tmp_path, {"fanout": skill_yaml}, {"checker": "You check facts."})

    run_id, packet = start_run(
        project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="claude-code"
    )

    assert task_tiers(project, run_id) == ["deep", "fast"]
    task_zero, task_one = packet.split("#### Task 1")
    assert "`model: opus`" in task_zero.split("#### Task 0")[1]
    assert "`model: haiku`" in task_one


@pytest.mark.parametrize("tier", ["\"{{ '' }}\"", '"{{ none }}"'])
def test_an_empty_computed_tier_inherits_the_model(tmp_path: Path, tier: str) -> None:
    project = make_project(tmp_path, {"fanout": tiered_skill(tier)}, {"checker": "You check facts."})

    run_id, packet = start_run(project, "fanout", {"files": ["a.md"]}, mode="interactive", harness="claude-code")

    assert "`model:" not in packet
    assert task_tiers(project, run_id) == [None]


def test_a_computed_tier_that_is_not_a_tier_pauses_the_run(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": tiered_skill("\"{{ 'medium' }}\"")}, {"checker": "You check facts."})

    run_id, packet = start_run(project, "fanout", {"files": ["a.md"]}, mode="interactive", harness="claude-code")

    assert read_run_info(project, run_id)["pause_reason"] == "runner_error"
    assert "The tier of 'check' must be fast, standard, or deep, not 'medium'." in packet


def test_the_one_by_one_packet_ignores_the_tier(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": tiered_skill("fast")}, {"checker": "You check facts."})

    _, packet = start_run(project, "fanout", {"files": ["a.md"]}, mode="interactive", harness="generic")

    assert "model" not in packet and "fast" not in packet


def profiled_skill(tools: str, extra: str = "") -> str:
    return PARALLEL_SKILL.replace("    agent: checker\n", f"    agent: checker\n    tools: {tools}\n{extra}")


def task_profiles(project: Project, run_id: str) -> list[str | None]:
    return [task.get("tools") for task in read_run_state(project, run_id)["frames"][0]["tasks"] or []]


def test_a_tool_profile_asks_claude_code_for_its_profile_agent_on_each_agent_call(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": profiled_skill("read")}, {"checker": "You check facts."})

    run_id, packet = start_run(
        project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="claude-code"
    )

    assert packet.count("`subagent_type: pskill-read`") == 2
    assert task_profiles(project, run_id) == ["read", "read"]


def test_a_block_with_no_tool_profile_gets_the_same_packet_as_before(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": PARALLEL_SKILL}, {"checker": "You check facts."})

    run_id, packet = start_run(project, "fanout", {"files": ["a.md"]}, mode="interactive", harness="claude-code")

    assert "pskill-" not in packet
    assert packet.split("#### Task 0")[1].splitlines()[1].startswith("You are a subagent of pskill run")
    assert task_profiles(project, run_id) == [None]


def test_a_task_with_a_tool_profile_and_a_tier_gets_both_on_one_line(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": profiled_skill("web", "    tier: fast\n")}, {"checker": "Facts."})

    _, packet = start_run(project, "fanout", {"files": ["a.md"]}, mode="interactive", harness="claude-code")

    spawn_line = packet.split("#### Task 0")[1].splitlines()[1]
    claude_code = ADAPTERS["claude-code"]
    assert spawn_line == f"{claude_code.tools_wording['web']} {tier_wording(claude_code, {}, 'fast')}"


def test_each_item_can_ask_for_its_own_tool_profile(tmp_path: Path) -> None:
    skill_yaml = profiled_skill("\"{{ 'web' if item == 'a.md' else 'read' }}\"")
    project = make_project(tmp_path, {"fanout": skill_yaml}, {"checker": "You check facts."})

    run_id, packet = start_run(
        project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="claude-code"
    )

    assert task_profiles(project, run_id) == ["web", "read"]
    task_zero, task_one = packet.split("#### Task 1")
    assert "pskill-web" in task_zero.split("#### Task 0")[1]
    assert "pskill-read" in task_one


@pytest.mark.parametrize("tools", ["\"{{ '' }}\"", '"{{ none }}"'])
def test_an_empty_computed_tool_profile_gives_every_tool(tmp_path: Path, tools: str) -> None:
    project = make_project(tmp_path, {"fanout": profiled_skill(tools)}, {"checker": "You check facts."})

    run_id, packet = start_run(project, "fanout", {"files": ["a.md"]}, mode="interactive", harness="claude-code")

    assert "pskill-" not in packet
    assert task_profiles(project, run_id) == [None]


def test_a_computed_tool_profile_that_is_not_a_profile_pauses_the_run(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": profiled_skill("\"{{ 'write' }}\"")}, {"checker": "Facts."})

    run_id, packet = start_run(project, "fanout", {"files": ["a.md"]}, mode="interactive", harness="claude-code")

    assert read_run_info(project, run_id)["pause_reason"] == "runner_error"
    assert "The tool profile of 'check' must be read or web, not 'write'." in packet


@pytest.mark.parametrize("harness", ["codex", "generic"])
def test_codex_and_the_one_by_one_packet_ignore_the_tool_profile(tmp_path: Path, harness: str) -> None:
    project = make_project(tmp_path, {"fanout": profiled_skill("read")}, {"checker": "You check facts."})

    _, packet = start_run(project, "fanout", {"files": ["a.md"]}, mode="interactive", harness=harness)

    assert "pskill-read" not in packet


def test_a_state_file_from_before_tool_profiles_still_gives_its_packet(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": PARALLEL_SKILL}, {"checker": "You check facts."})
    run_id, _ = start_run(project, "fanout", {"files": ["a.md"]}, mode="interactive", harness="claude-code")
    state_path = project.runs_folder / run_id / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    for task in state["frames"][0]["tasks"]:
        del task["tools"]
    state_path.write_text(json.dumps(state), encoding="utf-8")

    packet = current_packet(project, run_id)

    assert "#### Task 0" in packet and "pskill-" not in packet


def test_a_pause_in_a_child_shows_the_pause_steps_of_each_skill_with_its_own_values(tmp_path: Path) -> None:
    parent = PARENT_SKILL.replace(
        "goal: Get a greeting from the child.\n",
        'goal: Get a greeting from the child.\non_pause: "Tell them: {{ steps.greet.text }}"\n',
    )
    child = CHILD_SKILL.replace(
        "goal: Greet the person by name.\n",
        'goal: Greet the person by name.\non_pause: "Release the claim for {{ inputs.name }}."\n',
    )
    project = make_project(tmp_path, {"parent": parent, "child": child})
    run_id, _ = start_run(project, "parent", {}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "text: Hello from the parent.\n")

    packet = pause_run(project, run_id)

    assert (
        "### Pause steps of child\nRelease the claim for Ada.\n\n"
        "### Pause steps of parent\nTell them: Hello from the parent.\n\n### Next\n"
    ) in packet


def test_a_pause_in_the_root_skips_the_child_and_a_skill_without_pause_steps(tmp_path: Path) -> None:
    child = CHILD_SKILL.replace(
        "goal: Greet the person by name.\n", 'goal: Greet the person by name.\non_pause: "Release the claim."\n'
    )
    project = make_project(tmp_path, {"parent": PARENT_SKILL, "child": child})
    run_id, _ = start_run(project, "parent", {}, mode="interactive", harness="generic")
    root_packet = pause_run(project, run_id)
    resume_run(project, run_id)
    submit_answer(project, run_id, "text: Hello from the parent.\n")

    child_packet = pause_run(project, run_id)

    assert "### Pause steps" not in root_packet
    assert "### Pause steps of child\nRelease the claim.\n\n### Next\n" in child_packet
    assert "### Pause steps of parent" not in child_packet


PAUSING_PARALLEL_SKILL = PARALLEL_SKILL.replace(
    "goal: Find the wrong claims.\n", 'goal: Find the wrong claims.\non_pause: "Post one comment."\n'
)


def test_a_task_answer_that_pauses_the_run_gives_the_subagent_no_pause_steps(tmp_path: Path) -> None:
    skill_yaml = PAUSING_PARALLEL_SKILL.replace("    agent: checker\n", "    agent: checker\n    retries: 0\n")
    project = make_project(tmp_path, {"fanout": skill_yaml}, {"checker": "You check facts."})
    run_id, _ = start_run(
        project, "fanout", {"files": ["a.md", "b.md"]}, mode="autonomous", harness="subagents-for-tests"
    )

    reply = submit_answer(project, run_id, "$cannot_complete: no access\n", task=0)

    assert reply == (
        f"Task 0 is not recorded, and the run is paused. Stop here, and tell the main agent: it reads the pause "
        f"with `uv run .pskill/pskill.py current {run_id}`.\n"
    )
    assert read_run_info(project, run_id)["status"] == "paused"
    assert "### Pause steps of fanout\nPost one comment." in current_packet(project, run_id)


def test_a_last_task_whose_join_pauses_the_run_gives_the_subagent_no_pause_steps(tmp_path: Path) -> None:
    skill_yaml = PAUSING_PARALLEL_SKILL.replace(
        "    next: done\n", '    next:\n      - when: "{{ false }}"\n        to: done\n'
    )
    project = make_project(tmp_path, {"fanout": skill_yaml}, {"checker": "You check facts."})
    run_id, _ = start_run(project, "fanout", {"files": ["a.md"]}, mode="autonomous", harness="subagents-for-tests")

    reply = submit_answer(project, run_id, "wrong: []\n", task=0)

    assert "Pause steps" not in reply
    assert reply.startswith("Task 0 is recorded, and the run is paused. Stop here, and tell the main agent")
    assert read_run_info(project, run_id)["pause_reason"] == "runner_error"


def test_a_task_answer_that_pauses_the_run_without_subagents_gives_the_main_agent_the_pause_packet(
    tmp_path: Path,
) -> None:
    skill_yaml = PAUSING_PARALLEL_SKILL.replace("    agent: checker\n", "    agent: checker\n    retries: 0\n")
    project = make_project(tmp_path, {"fanout": skill_yaml}, {"checker": "You check facts."})
    run_id, _ = start_run(project, "fanout", {"files": ["a.md", "b.md"]}, mode="autonomous", harness="generic")

    reply = submit_answer(project, run_id, "$cannot_complete: no access\n", task=0)

    assert "### Pause steps of fanout\nPost one comment.\n" in reply
    assert "tell the main agent" not in reply


def test_events_name_their_call_instance_and_a_call_logs_its_inputs(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"parent": PARENT_SKILL, "child": CHILD_SKILL})
    run_id, _ = start_run(project, "parent", {}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "text: Hello from the parent.\n")
    submit_answer(project, run_id, "text: Hello, Ada!\n")

    events = read_events(project.runs_folder / run_id)

    assert {event["call_id"] for event in events if event["frame"] == "parent"} == {""}
    assert {event["call_id"] for event in events if event["frame"] == "parent>child"} == {"child#1"}
    call_started = next(e for e in events if e["type"] == "block_started" and e.get("block_type") == "call")
    assert call_started["inputs"] == {"name": "Ada"}


def test_a_call_whose_inputs_fail_still_logs_its_start(tmp_path: Path) -> None:
    parent = PARENT_SKILL.replace("inputs: {name: Ada}", 'inputs: {name: "{{ steps.greet.missing }}"}')
    project = make_project(tmp_path, {"parent": parent, "child": CHILD_SKILL})
    run_id, _ = start_run(project, "parent", {}, mode="interactive", harness="generic")

    submit_answer(project, run_id, "text: Hello from the parent.\n")

    events = read_events(project.runs_folder / run_id)
    call_started = next(e for e in events if e["type"] == "block_started" and e.get("block_type") == "call")
    assert "inputs" not in call_started
    assert read_run_info(project, run_id)["pause_reason"] == "runner_error"


def test_claude_code_waits_for_a_background_subagent_until_every_task_is_submitted(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": PARALLEL_SKILL}, {"checker": "You check facts."})
    run_id, packet = start_run(
        project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="claude-code"
    )
    submit_answer(project, run_id, "wrong: []\n", task=0)

    current = current_packet(project, run_id)

    wait_line = f'wait {run_id} --reason "the subagents of check"` in the background, then end your turn.'
    assert wait_line in packet and wait_line in current
    assert "1 of 2 tasks are still open." in current
    assert read_run_info(project, run_id)["current_block"] == "check"


def test_codex_gets_no_wait_line_in_a_parallel_packet(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": PARALLEL_SKILL}, {"checker": "You check facts."})

    _, packet = start_run(project, "fanout", {"files": ["a.md"]}, mode="interactive", harness="codex")

    assert "--reason" not in packet


def test_only_the_root_skill_gives_a_summary_card(tmp_path: Path) -> None:
    child = CHILD_SKILL.replace("    status: succeeded\n", '    status: succeeded\n    pending: "Child work left."\n')
    project = make_project(tmp_path, {"parent": PARENT_SKILL, "child": child})
    run_id, _ = start_run(project, "parent", {}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "text: Hello from the parent.\n")

    final = submit_answer(project, run_id, "text: Hello, Ada!\n")

    assert final.count("### Summary card") == 1
    assert "| ✅ DONE | parent · succeeded |" in final
    assert "Child work left." not in final


# --- task jobs: one job or one per item, each in the main context or a fresh one ----------------------

ONE_JOB_SKILL = """\
schema: pskill/v1
id: one-job
description: Does one job.
goal: Judge the change.
outputs:
  verdict: {type: string, description: "The verdict."}
entry: judge
blocks:
  judge:
    type: task
    context: fresh
    tier: fast
    instruction: Judge the change.
    output:
      verdict: {type: string, description: "The verdict."}
    next: done
  done:
    type: end
    status: succeeded
    outputs: {verdict: "{{ steps.judge.verdict }}"}
"""

MIXED_SKILL = """\
schema: pskill/v1
id: mixed
description: Mixes jobs.
goal: Check every part.
entry: check
blocks:
  check:
    type: task
    for_each:
      - {part: a, context: fresh}
      - {part: b, context: main}
      - {part: c, context: fresh}
    context: "{{ item.context }}"
    task_name: "{{ item.part }}"
    instruction: "Check part {{ item.part }}."
    output:
      note: {type: string, description: "What you found."}
    next: done
  done:
    type: end
    status: succeeded
"""


def test_a_one_job_fresh_task_spawns_one_subagent_and_stores_its_output_flat(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"one-job": ONE_JOB_SKILL})

    run_id, packet = start_run(project, "one-job", {}, mode="interactive", harness="subagents-for-tests")
    reply = submit_answer(project, run_id, "verdict: fine\n", task=0)

    assert "### Subagent tasks" in packet
    assert "#### Task 0" in packet
    assert reply == "Task 0 is recorded. All 1 tasks are done.\n"
    assert read_run_state(project, run_id)["frames"][0]["steps"]["judge"] == {"verdict": "fine"}
    assert read_run_info(project, run_id)["outputs"] == {"verdict": "fine"}


def test_a_one_job_fresh_task_logs_the_full_prompt_of_its_subagent(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"one-job": ONE_JOB_SKILL})

    run_id, _ = start_run(project, "one-job", {}, mode="interactive", harness="subagents-for-tests")

    [started] = [event for event in read_events(project.runs_folder / run_id) if event["type"] == "block_started"]
    [prompt] = started["task_prompts"]
    assert prompt.startswith("You are a subagent of a pskill run.")
    assert "Judge the change." in prompt
    assert "for_each" not in started


def test_a_one_job_fresh_task_needs_the_task_number(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"one-job": ONE_JOB_SKILL})
    run_id, _ = start_run(project, "one-job", {}, mode="interactive", harness="subagents-for-tests")

    reply = submit_answer(project, run_id, "verdict: fine\n", task=None)

    assert "Add `--task <n>` to the submit command." in reply


def test_a_harness_without_subagents_does_a_fresh_job_itself_and_ignores_its_tier(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"one-job": ONE_JOB_SKILL})

    run_id, packet = start_run(project, "one-job", {}, mode="interactive", harness="generic")
    final = submit_answer(project, run_id, "verdict: fine\n")

    assert "Subagent tasks" not in packet
    assert "Judge the change." in packet
    assert "--task" not in packet
    assert "haiku" not in packet
    assert "finished with status succeeded" in final
    assert read_run_state(project, run_id)["frames"][0]["steps"]["judge"] == {"verdict": "fine"}
    events = read_events(project.runs_folder / run_id)
    [completed] = [event for event in events if event["type"] == "block_completed" and event["block"] == "judge"]
    assert "tier" not in completed  # the main agent ran it on its own model, not on the tier's


def test_a_one_job_main_task_takes_task_zero_too(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"one-job": ONE_JOB_SKILL.replace("    context: fresh\n    tier: fast\n", "")})
    run_id, _ = start_run(project, "one-job", {}, mode="interactive", harness="subagents-for-tests")

    final = submit_answer(project, run_id, "verdict: fine\n", task=0)

    assert "finished with status succeeded" in final


def test_main_jobs_of_a_for_each_run_one_by_one_and_join_in_item_order(tmp_path: Path) -> None:
    main_only = PARALLEL_SKILL.replace("    context: fresh\n", "").replace("    agent: checker\n", "")
    project = make_project(tmp_path, {"fanout": main_only})

    run_id, first = start_run(
        project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="subagents-for-tests"
    )
    second = submit_answer(project, run_id, "wrong: [x]\n", task=0)
    final = submit_answer(project, run_id, "wrong: []\n", task=1)

    assert "Check every claim in a.md." in first
    assert "--task 0" in first
    assert "Subagent tasks" not in first
    assert "Check every claim in b.md." in second
    assert "--task 1" in second
    assert "finished with status succeeded" in final
    assert read_run_state(project, run_id)["frames"][0]["steps"]["check"] == {
        "results": [{"wrong": ["x"]}, {"wrong": []}]
    }


def test_a_mixed_block_spawns_the_fresh_jobs_then_gives_the_main_jobs(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"mixed": MIXED_SKILL})

    run_id, packet = start_run(project, "mixed", {}, mode="interactive", harness="subagents-for-tests")
    first_reply = submit_answer(project, run_id, "note: c is fine\n", task=2)
    last_fresh_reply = submit_answer(project, run_id, "note: a is fine\n", task=0)
    main_packet = current_packet(project, run_id)
    final = submit_answer(project, run_id, "note: b is fine\n", task=1)

    assert "#### Task 0 · a" in packet and "#### Task 2 · c" in packet
    assert "#### Task 1" not in packet
    assert "1 more task is yours, in this conversation: run `current` for it when every subagent has finished." in (
        packet
    )
    assert first_reply == "Task 2 is recorded. 1 of 3 tasks are done.\n"
    assert last_fresh_reply == "Task 0 is recorded. 2 of 3 tasks are done.\n"
    assert "Check part b." in main_packet
    assert "--task 1" in main_packet
    assert "finished with status succeeded" in final
    assert read_run_state(project, run_id)["frames"][0]["steps"]["check"] == {
        "results": [{"note": "a is fine"}, {"note": "b is fine"}, {"note": "c is fine"}]
    }
    events = read_events(project.runs_folder / run_id)
    started = [event for event in events if event["type"] == "block_started" and event["block"] == "check"]
    assert [event.get("task") for event in started] == [None, 1]


def test_a_main_job_answered_while_subagents_work_is_recorded(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"mixed": MIXED_SKILL})
    run_id, _ = start_run(project, "mixed", {}, mode="interactive", harness="subagents-for-tests")

    reply = submit_answer(project, run_id, "note: b is fine\n", task=1)

    assert reply == "Task 1 is recorded. 1 of 3 tasks are done.\n"


def test_a_computed_context_that_is_not_main_or_fresh_pauses_the_run(tmp_path: Path) -> None:
    project = make_project(
        tmp_path, {"mixed": MIXED_SKILL.replace("{part: b, context: main}", "{part: b, context: x}")}
    )

    run_id, packet = start_run(project, "mixed", {}, mode="interactive", harness="subagents-for-tests")

    assert read_run_info(project, run_id)["status"] == "paused"
    assert "The context of 'check' must be main or fresh, not 'x'." in packet


def test_an_empty_computed_context_is_the_main_context(tmp_path: Path) -> None:
    project = make_project(
        tmp_path, {"mixed": MIXED_SKILL.replace("{part: b, context: main}", "{part: b, context: ''}")}
    )

    _, packet = start_run(project, "mixed", {}, mode="interactive", harness="subagents-for-tests")

    assert "1 more task is yours" in packet


def test_resume_of_a_for_each_task_whose_start_failed_starts_its_jobs_again(tmp_path: Path) -> None:
    not_a_list = PARALLEL_SKILL.replace('for_each: "{{ inputs.files }}"', 'for_each: "{{ run.id }}"')
    project = make_project(tmp_path, {"fanout": not_a_list}, {"checker": "You check facts."})
    run_id, _ = start_run(project, "fanout", {"files": ["a.md"]}, mode="interactive", harness="subagents-for-tests")

    packet = resume_run(project, run_id)

    assert read_run_info(project, run_id)["status"] == "paused"
    assert "The for_each of 'check' must give a list, not str." in packet
    assert read_run_state(project, run_id)["frames"][0]["tasks"] is None


def test_a_rejected_main_job_while_subagents_work_gets_its_errors_and_then_the_pause_not_a_spawn_list(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path, {"mixed": MIXED_SKILL})
    run_id, _ = start_run(project, "mixed", {}, mode="interactive", harness="subagents-for-tests")

    first = submit_answer(project, run_id, "note: [not, text]\n", task=1)
    submit_answer(project, run_id, "note: [not, text]\n", task=1)
    last = submit_answer(project, run_id, "note: [not, text]\n", task=1)

    assert first.startswith("Task 1 is not recorded. Fix these problems and submit again:")
    assert "Spawn one subagent" not in first
    assert read_run_info(project, run_id)["status"] == "paused"
    assert "Stop here, and tell the main agent" not in last
    assert "is paused at block check" in last


def test_a_fresh_job_continued_in_a_harness_without_subagents_is_done_by_the_main_agent(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"one-job": ONE_JOB_SKILL})
    run_id, _ = start_run(project, "one-job", {}, mode="interactive", harness="subagents-for-tests")

    packet = current_packet(project, run_id, harness="generic")
    rejected = submit_answer(project, run_id, "verdict: [not, text]\n", harness="generic")
    final = submit_answer(project, run_id, "verdict: fine\n", harness="generic")

    assert "Subagent tasks" not in packet
    assert "Judge the change." in packet
    assert "### Errors" in rejected
    assert "finished with status succeeded" in final
    events = read_events(project.runs_folder / run_id)
    [completed] = [event for event in events if event["type"] == "block_completed" and event["block"] == "judge"]
    assert "tier" not in completed


def test_resume_of_a_one_job_task_whose_start_failed_logs_its_start(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"one-job": ONE_JOB_SKILL.replace("tier: fast", "tier: \"{{ 'huge' }}\"")})
    run_id, paused = start_run(project, "one-job", {}, mode="interactive", harness="subagents-for-tests")
    copy = project.runs_folder / run_id / "skills" / "one-job" / "skill.yaml"
    copy.write_text(copy.read_text(encoding="utf-8").replace("tier: \"{{ 'huge' }}\"", "tier: fast"), encoding="utf-8")

    packet = resume_run(project, run_id)

    assert "must be fast, standard, or deep, not 'huge'" in paused
    assert "### Subagent tasks" in packet
    started = [event for event in read_events(project.runs_folder / run_id) if event["type"] == "block_started"]
    assert [event["block"] for event in started] == ["judge"]
    assert started[0]["task_prompts"]


def test_a_rejected_main_job_with_no_subagent_at_work_gets_its_packet_with_the_errors(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"mixed": MIXED_SKILL})
    run_id, _ = start_run(project, "mixed", {}, mode="interactive", harness="subagents-for-tests")
    submit_answer(project, run_id, "note: a is fine\n", task=0)
    submit_answer(project, run_id, "note: c is fine\n", task=2)

    reply = submit_answer(project, run_id, "note: [not, text]\n", task=1)

    assert reply.startswith("## pskill · mixed · check (visit 1)")
    assert "### Errors" in reply
    assert "Check part b." in reply


def test_a_one_job_main_task_counts_its_rejections_once_with_or_without_the_task_number(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"one-job": ONE_JOB_SKILL.replace("    context: fresh\n    tier: fast\n", "")})
    run_id, _ = start_run(project, "one-job", {}, mode="interactive", harness="subagents-for-tests")

    submit_answer(project, run_id, "verdict: [not, text]\n", task=0)
    submit_answer(project, run_id, "verdict: [not, text]\n")
    submit_answer(project, run_id, "verdict: [not, text]\n", task=0)

    assert read_run_info(project, run_id)["status"] == "paused"  # 2 retries, then the pause


def test_for_each_jobs_continued_in_a_harness_without_subagents_log_no_tier(tmp_path: Path) -> None:
    tiered = PARALLEL_SKILL.replace("    agent: checker\n", "    agent: checker\n    tier: deep\n")
    project = make_project(tmp_path, {"fanout": tiered}, {"checker": "You check facts."})
    run_id, _ = start_run(
        project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="subagents-for-tests"
    )

    submit_answer(project, run_id, "wrong: []\n", task=0, harness="generic")
    submit_answer(project, run_id, "wrong: []\n", task=1, harness="generic")

    events = read_events(project.runs_folder / run_id)
    completed = [event for event in events if event["type"] == "block_completed" and event["block"] == "check"]
    assert [event.get("task") for event in completed] == [0, 1, None]
    assert all("tier" not in event for event in completed)


def test_resume_of_a_main_job_whose_start_failed_repeats_the_goal_and_the_rules(tmp_path: Path) -> None:
    broken = ONE_JOB_SKILL.replace("    context: fresh\n    tier: fast\n", "    context: \"{{ 'huge' }}\"\n")
    project = make_project(tmp_path, {"one-job": broken})
    run_id, _ = start_run(project, "one-job", {}, mode="interactive", harness="subagents-for-tests")
    copy = project.runs_folder / run_id / "skills" / "one-job" / "skill.yaml"
    copy.write_text(copy.read_text(encoding="utf-8").replace("    context: \"{{ 'huge' }}\"\n", ""), encoding="utf-8")

    packet = resume_run(project, run_id)

    assert "Judge the change." in packet
    assert "### Goal" in packet
    assert "### Rules" in packet


def test_resume_of_a_for_each_task_whose_start_failed_and_now_gives_no_item_completes_it(tmp_path: Path) -> None:
    not_a_list = PARALLEL_SKILL.replace('for_each: "{{ inputs.files }}"', 'for_each: "{{ run.id }}"')
    project = make_project(tmp_path, {"fanout": not_a_list}, {"checker": "You check facts."})
    run_id, _ = start_run(project, "fanout", {"files": ["a.md"]}, mode="interactive", harness="subagents-for-tests")
    copy = project.runs_folder / run_id / "skills" / "fanout" / "skill.yaml"
    copy.write_text(copy.read_text(encoding="utf-8").replace('"{{ run.id }}"', '"{{ [] }}"'), encoding="utf-8")

    packet = resume_run(project, run_id)

    assert "finished with status succeeded" in packet
    assert read_run_state(project, run_id)["frames"][0]["steps"]["check"] == {"results": []}


BACKGROUND_SKILL = SCRIPT_SKILL.replace(
    "    parse: json\n", "    parse: json\n    background: true\n    timeout_s: 900\n"
)


class NoScripts:
    """An executor for a run that must not run any script now."""

    def run_script(
        self,
        block_id: str,
        argv: list[str],
        cwd: Path,
        env: dict[str, str],
        timeout_s: int,
        stdin_text: str | None = None,
    ) -> ScriptResult:
        raise AssertionError("The script must run in the background command, not here.")

    def call_result(self, block_id: str, skill_id: str, inputs: dict[str, Any]) -> CallResult | None:
        return None


def test_a_background_script_on_claude_code_gives_one_command_to_start_in_the_background(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"scripted": BACKGROUND_SKILL})

    run_id, packet = start_run(project, "scripted", {}, mode="interactive", harness="claude-code", executor=NoScripts())

    assert f"uv run .pskill/pskill.py run-script {run_id}" in packet
    assert "`run_in_background: true` and `timeout: 2760000` (46 minutes)" in packet  # 3 attempts of 900 s, plus 60 s
    assert "then end your turn" in packet
    info = read_run_info(project, run_id)
    assert info["status"] == "active"
    assert info["current_block"] == "list_files"
    assert info["wait_reason"] == "the background script list_files"
    assert info["wait_until"] is not None and info["waits_since"] is not None
    frame = read_run_state(project, run_id)["frames"][-1]
    assert frame["background_script"] is not None and frame["background_script"]["state"] == "issued"
    started = [event for event in read_events(project.runs_folder / run_id) if event["type"] == "block_started"]
    assert started[-1]["block"] == "list_files" and started[-1]["packet"] == packet


def test_the_shell_timeout_of_a_background_script_covers_every_attempt(tmp_path: Path) -> None:
    skill_yaml = BACKGROUND_SKILL.replace("timeout_s: 900", "timeout_s: 1800\n    retries: 1")
    project = make_project(tmp_path, {"scripted": skill_yaml})

    run_id, packet = start_run(project, "scripted", {}, mode="interactive", harness="claude-code", executor=NoScripts())

    assert "`timeout: 3660000` (61 minutes)" in packet  # 2 attempts of 1800 s, plus 60 s
    info = read_run_info(project, run_id)
    assert info["wait_until"] is not None and info["wait_started_at"] is not None
    waited_s = (datetime.fromisoformat(info["wait_until"]) - datetime.fromisoformat(info["wait_started_at"])).seconds
    assert waited_s == 3660


def test_the_shell_timeout_of_a_background_script_stays_within_two_hours(tmp_path: Path) -> None:
    skill_yaml = BACKGROUND_SKILL.replace("timeout_s: 900", "timeout_s: 7140\n    retries: 0")
    project = make_project(tmp_path, {"scripted": skill_yaml})

    _, packet = start_run(project, "scripted", {}, mode="interactive", harness="claude-code", executor=NoScripts())

    assert "`timeout: 7200000` (120 minutes)" in packet


def test_a_background_script_runs_in_the_foreground_on_a_harness_that_wakes_nobody(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"scripted": BACKGROUND_SKILL})

    for harness in ("generic", "codex"):
        run_id, packet = start_run(project, "scripted", {}, mode="interactive", harness=harness)

        assert "finished with status succeeded" in packet, packet
        assert read_run_info(project, run_id)["outputs"] == {"count": 2}


def start_background(tmp_path: Path, skill_yaml: str = BACKGROUND_SKILL) -> tuple[Project, str]:
    project = make_project(tmp_path, {"scripted": skill_yaml})
    run_id, _ = start_run(project, "scripted", {}, mode="interactive", harness="claude-code", executor=NoScripts())
    return project, run_id


class ScriptWithSideEffect:
    """Runs `while_running` while the script runs (the run lock is free then), then returns a good result."""

    def __init__(self, while_running: Any) -> None:
        self.while_running = while_running
        self.calls = 0

    def run_script(
        self,
        block_id: str,
        argv: list[str],
        cwd: Path,
        env: dict[str, str],
        timeout_s: int,
        stdin_text: str | None = None,
    ) -> ScriptResult:
        self.calls += 1
        self.while_running()
        return ScriptResult(exit_code=0, stdout=json.dumps({"files": ["a.md"]}), stderr="", duration_ms=5)

    def call_result(self, block_id: str, skill_id: str, inputs: dict[str, Any]) -> CallResult | None:
        return None


def test_the_background_command_runs_the_script_records_it_and_prints_the_next_packet(tmp_path: Path) -> None:
    project, run_id = start_background(tmp_path)

    text = run_background_script(project, run_id)

    assert "finished with status succeeded" in text
    info = read_run_info(project, run_id)
    assert info["outputs"] == {"count": 2}
    assert (info["wait_reason"], info["wait_until"], info["waits_since"]) == (None, None, None)
    assert read_run_state(project, run_id)["frames"][-1]["background_script"] is None
    events = read_events(project.runs_folder / run_id)
    ran = [event for event in events if event["type"] == "script_ran"]
    assert len(ran) == 1 and ran[0]["block"] == "list_files" and ran[0]["exit_code"] == 0
    completed = [event for event in events if event["type"] == "block_completed" and event["block"] == "list_files"]
    assert len(completed) == 1


def test_the_background_command_runs_the_script_with_no_run_lock_held(tmp_path: Path) -> None:
    project, run_id = start_background(tmp_path)
    seen: list[str] = []

    def look_at_the_lock() -> None:
        seen.append("held" if (project.runs_folder / run_id / LOCK_FILE_NAME).exists() else "free")

    run_background_script(project, run_id, ScriptWithSideEffect(look_at_the_lock))

    assert seen == ["free"]


def test_a_failed_background_script_is_retried_then_pauses_the_run(tmp_path: Path) -> None:
    failing = BACKGROUND_SKILL.replace(
        "\"import json; print(json.dumps({'files': ['a.md', 'b.md']}))\"", '"import sys; sys.exit(3)"'
    ).replace("    background: true\n", "    background: true\n    retries: 1\n")
    project, run_id = start_background(tmp_path, failing)

    text = run_background_script(project, run_id)

    info = read_run_info(project, run_id)
    assert (info["status"], info["pause_reason"]) == ("paused", "block_failed")
    assert "exit code 3" in text
    ran = [event for event in read_events(project.runs_folder / run_id) if event["type"] == "script_ran"]
    assert len(ran) == 2


def test_a_second_background_command_is_refused_while_the_script_runs(tmp_path: Path) -> None:
    project, run_id = start_background(tmp_path)
    refusals: list[str] = []

    def start_again() -> None:
        with pytest.raises(RunError) as raised:
            run_background_script(project, run_id, NoScripts())
        refusals.append(str(raised.value))

    run_background_script(project, run_id, ScriptWithSideEffect(start_again))

    assert "already runs in the background" in refusals[0]
    assert read_run_info(project, run_id)["status"] == "succeeded"


def test_the_result_is_dropped_when_the_run_changed_while_the_script_ran(tmp_path: Path) -> None:
    project, run_id = start_background(tmp_path)

    text = run_background_script(project, run_id, ScriptWithSideEffect(lambda: pause_run(project, run_id)))

    assert "its result is dropped" in text
    assert f"uv run .pskill/pskill.py current {run_id}" in text
    info = read_run_info(project, run_id)
    assert info["status"] == "paused" and info["current_block"] == "list_files"
    assert not [event for event in read_events(project.runs_folder / run_id) if event["type"] == "script_ran"]


def test_the_background_command_needs_a_background_script_that_waits_for_it(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"parent": PARENT_SKILL, "child": CHILD_SKILL})
    run_id, _ = start_run(project, "parent", {}, mode="interactive", harness="claude-code")

    with pytest.raises(RunError) as raised:
        run_background_script(project, run_id)

    assert "does not run a script in the background" in str(raised.value)


def test_a_background_command_that_cannot_compute_its_command_pauses_the_run(tmp_path: Path) -> None:
    broken = BACKGROUND_SKILL.replace("run: [python, -c,", 'run: ["{{ [1][5] }}", -c,')
    project, run_id = start_background(tmp_path, broken)

    text = run_background_script(project, run_id, NoScripts())

    assert read_run_info(project, run_id)["pause_reason"] == "runner_error"
    assert "The command of 'list_files'" in text


def test_current_gives_the_background_command_again_until_it_starts(tmp_path: Path) -> None:
    project, run_id = start_background(tmp_path)

    packet = current_packet(project, run_id)

    assert f"run-script {run_id}" in packet
    assert "### Goal\nRead data with a script." in packet and "### Rules" in packet


def test_current_on_a_harness_that_wakes_nobody_runs_the_background_script_in_the_foreground(tmp_path: Path) -> None:
    project, run_id = start_background(tmp_path)

    packet = current_packet(project, run_id, harness="codex")

    assert "finished with status succeeded" in packet, packet
    info = read_run_info(project, run_id)
    assert info["outputs"] == {"count": 2}
    assert (info["wait_reason"], info["wait_until"], info["waits_since"]) == (None, None, None)
    assert read_run_state(project, run_id)["frames"][-1]["background_script"] is None


def test_a_foreground_run_clears_the_marker_of_a_background_script_it_replaces(tmp_path: Path) -> None:
    project, run_id = start_background(tmp_path)
    pause_run(project, run_id)

    packet = resume_run(project, run_id, harness="codex")

    assert "finished with status succeeded" in packet, packet
    assert read_run_state(project, run_id)["frames"][-1]["background_script"] is None


def test_current_at_a_paused_background_script_gives_the_pause_text(tmp_path: Path) -> None:
    project, run_id = start_background(tmp_path)
    pause_run(project, run_id)

    packet = current_packet(project, run_id)

    assert "paused" in packet and "run-script" not in packet


def test_current_says_that_the_script_runs_while_it_runs(tmp_path: Path) -> None:
    project, run_id = start_background(tmp_path)
    seen: list[str] = []

    run_background_script(project, run_id, ScriptWithSideEffect(lambda: seen.append(current_packet(project, run_id))))

    assert "The script 'list_files' runs in the background" in seen[0]
    assert "End your turn" in seen[0]
    assert f"pause {run_id}" in seen[0] and f"resume {run_id}" in seen[0]


def test_a_background_script_takes_no_answer(tmp_path: Path) -> None:
    project, run_id = start_background(tmp_path)

    with pytest.raises(RunError) as raised:
        submit_answer(project, run_id, "status: done\n")

    assert "runs a script in the background, so it takes no answer" in str(raised.value)


def test_resume_gives_the_background_command_again_and_drops_the_old_run(tmp_path: Path) -> None:
    project, run_id = start_background(tmp_path)
    resumed: list[str] = []

    def pause_and_resume() -> None:
        pause_run(project, run_id)
        resumed.append(resume_run(project, run_id))

    dropped = run_background_script(project, run_id, ScriptWithSideEffect(pause_and_resume))

    assert f"run-script {run_id}" in resumed[0] and "### Goal" in resumed[0]
    assert "its result is dropped" in dropped
    marker = read_run_state(project, run_id)["frames"][-1]["background_script"]
    assert marker is not None and marker["state"] == "issued"
    assert "finished with status succeeded" in run_background_script(project, run_id)
