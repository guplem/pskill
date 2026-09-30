"""Tests for running script, call, and parallel blocks."""

import threading
from pathlib import Path

import pytest

from pskill_runner.adapters import ADAPTERS, HarnessAdapter
from pskill_runner.engine import current_packet, read_run_info, read_run_state, start_run, submit_answer
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
    assert "You check facts carefully." in packet
    assert "Check every claim in b.md." in packet
    assert "submit " + run_id + " --task 1" in packet

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
