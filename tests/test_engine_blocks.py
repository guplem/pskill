"""Tests for running script, call, and parallel blocks."""

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from pskill_runner import engine
from pskill_runner.adapters import ADAPTERS, HarnessAdapter
from pskill_runner.engine import (
    RunError,
    current_packet,
    pause_run,
    read_run_info,
    read_run_state,
    register_stop_attempt,
    resume_run,
    start_run,
    submit_answer,
    task_packet,
)
from pskill_runner.inline_executor import CallResult, ScriptResult
from pskill_runner.project import Project, find_project
from pskill_runner.run_store import read_events
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
    type: parallel
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
    type: parallel
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
    type: parallel
    for_each: "{{ inputs.files }}"
    instruction: "Check {{ item }}."
    output:
      ok: {type: boolean, description: "True when done."}
    next: second
  second:
    type: parallel
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
