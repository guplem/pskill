"""Tests for pskill_runner.skill_loader."""

from pathlib import Path

import pytest

from pskill_runner.field_types import FieldSpec
from pskill_runner.skill_loader import SkillLoadError, load_skill
from pskill_runner.skill_model import CallBlock, DecisionBlock, Edge, EndBlock, ParallelBlock, ScriptBlock, TaskBlock
from tests.skill_files import PER_ITEM_SKILL, PLAN_SKILL, PLAN_SKILL_FILES, write_skill


def test_load_skill_builds_the_typed_model(tmp_path: Path) -> None:
    folder = write_skill(tmp_path, "plan-work", PLAN_SKILL, PLAN_SKILL_FILES)

    skill = load_skill(folder)

    assert skill.id == "plan-work"
    assert skill.goal == "Produce a plan that the user approved."
    assert skill.invocation == "auto"
    assert skill.entry == [Edge(to="create_plan")]
    assert skill.inputs["topic"] == FieldSpec(type="string", description="What to plan.")
    task = skill.blocks["create_plan"]
    assert isinstance(task, TaskBlock)
    assert task.max_visits == 3
    assert task.next[0] == Edge(to="ask_user", when="{{ steps.create_plan.status == 'question' }}")
    decision = skill.blocks["approve_plan"]
    assert isinstance(decision, DecisionBlock)
    assert decision.choices == {"approve": "Accept the plan.", "stop": "Stop without a plan."}
    assert decision.next == {"approve": [Edge(to="done")], "stop": [Edge(to="stopped")]}
    end = skill.blocks["stopped"]
    assert isinstance(end, EndBlock)
    assert end.status == "cancelled"


def test_instruction_text_reads_a_file_or_uses_the_inline_text(tmp_path: Path) -> None:
    skill = load_skill(write_skill(tmp_path, "plan-work", PLAN_SKILL, PLAN_SKILL_FILES))

    assert skill.instruction_text("instructions/approve_plan.md").startswith("Show the plan:")
    assert skill.instruction_text("Ask the user.") == "Ask the user."


def test_a_conditional_entry_is_read_as_edges(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace(
        "entry: create_plan", "entry:\n  - when: \"{{ inputs.topic == 'x' }}\"\n    to: done\n  - to: create_plan"
    )

    skill = load_skill(write_skill(tmp_path, "plan-work", skill_yaml, PLAN_SKILL_FILES))

    assert skill.entry == [Edge(to="done", when="{{ inputs.topic == 'x' }}"), Edge(to="create_plan")]


def test_an_unknown_block_type_is_rejected(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace("    type: end\n    status: succeeded", "    type: finish\n    status: succeeded")

    with pytest.raises(SkillLoadError) as raised:
        load_skill(write_skill(tmp_path, "plan-work", skill_yaml, PLAN_SKILL_FILES))

    assert raised.value.problems == [
        "blocks.done: unknown block type 'finish' (known types: call, decision, end, parallel, script, task)"
    ]


def test_an_unknown_key_is_rejected(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace("    max_visits: 3\n", "    max_visits: 3\n    retry: 5\n")

    with pytest.raises(SkillLoadError) as raised:
        load_skill(write_skill(tmp_path, "plan-work", skill_yaml, PLAN_SKILL_FILES))

    assert any("blocks.create_plan" in problem and "'retry'" in problem for problem in raised.value.problems)


def test_the_id_must_match_the_folder_name(tmp_path: Path) -> None:
    with pytest.raises(SkillLoadError) as raised:
        load_skill(write_skill(tmp_path, "other-name", PLAN_SKILL, PLAN_SKILL_FILES))

    assert raised.value.problems == ["id: 'plan-work' does not match the folder name 'other-name'"]


def test_x_keys_hold_yaml_anchors(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace(
        'inputs:\n  topic: {type: string, description: "What to plan."}',
        'x-text: &text {type: string, description: "What to plan."}\ninputs:\n  topic: *text',
    )

    skill = load_skill(write_skill(tmp_path, "plan-work", skill_yaml, PLAN_SKILL_FILES))

    assert skill.inputs["topic"] == FieldSpec(type="string", description="What to plan.")


def test_a_broken_yaml_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(SkillLoadError) as raised:
        load_skill(write_skill(tmp_path, "plan-work", "schema: pskill/v1\nblocks: [unclosed\n"))

    assert raised.value.problems[0].startswith("skill.yaml is not valid YAML:")


ALL_BLOCKS_SKILL = """\
schema: pskill/v1
id: all-blocks
description: Every block type.
goal: Exercise every block.
entry: list_docs
blocks:
  list_docs:
    type: script
    run: [uv, run, "{{ skill.dir }}/scripts/list_docs.py"]
    parse: json
    next: check_docs
  check_docs:
    type: parallel
    for_each: "{{ steps.list_docs.json.files }}"
    agent: fact-checker
    instruction: "Check {{ item }}."
    output:
      wrong: {type: array, items: {type: string}, description: "Wrong claims."}
    next: review
  review:
    type: call
    skill: review-pr
    inputs: {pr: 1, post_verdict: false}
    next: done
  done:
    type: end
    status: succeeded
"""


def test_script_parallel_and_call_blocks_are_loaded(tmp_path: Path) -> None:
    skill = load_skill(write_skill(tmp_path, "all-blocks", ALL_BLOCKS_SKILL))

    script = skill.blocks["list_docs"]
    assert isinstance(script, ScriptBlock)
    assert script.run == ["uv", "run", "{{ skill.dir }}/scripts/list_docs.py"]
    assert script.parse == "json"
    parallel = skill.blocks["check_docs"]
    assert isinstance(parallel, ParallelBlock)
    assert parallel.for_each == "{{ steps.list_docs.json.files }}"
    assert parallel.agent == "fact-checker"
    assert parallel.task_name is None
    assert parallel.next == [Edge(to="review")]
    call = skill.blocks["review"]
    assert isinstance(call, CallBlock)
    assert call.skill == "review-pr"
    assert call.inputs == {"pr": 1, "post_verdict": False}


def test_a_script_parses_text_by_default(tmp_path: Path) -> None:
    skill = load_skill(write_skill(tmp_path, "all-blocks", ALL_BLOCKS_SKILL.replace("    parse: json\n", "")))

    script = skill.blocks["list_docs"]
    assert isinstance(script, ScriptBlock)
    assert script.parse == "text"


def test_a_block_can_set_its_own_retries_and_a_script_its_own_timeout(tmp_path: Path) -> None:
    skill_yaml = ALL_BLOCKS_SKILL.replace("    parse: json\n", "    parse: json\n    retries: 0\n    timeout_s: 30\n")

    script = load_skill(write_skill(tmp_path, "all-blocks", skill_yaml)).blocks["list_docs"]

    assert isinstance(script, ScriptBlock)
    assert (script.retries, script.timeout_s) == (0, 30)


def test_retries_and_timeout_are_unset_by_default(tmp_path: Path) -> None:
    skill = load_skill(write_skill(tmp_path, "plan-work", PLAN_SKILL, PLAN_SKILL_FILES))

    task = skill.blocks["create_plan"]
    assert isinstance(task, TaskBlock)
    assert task.retries is None


def test_only_a_script_takes_a_timeout_and_an_end_takes_no_retries(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace("    max_visits: 3\n", "    max_visits: 3\n    timeout_s: 30\n").replace(
        "    type: end\n    status: succeeded", "    type: end\n    retries: 1\n    status: succeeded"
    )

    with pytest.raises(SkillLoadError) as raised:
        load_skill(write_skill(tmp_path, "plan-work", skill_yaml, PLAN_SKILL_FILES))

    assert any("blocks.create_plan" in problem and "'timeout_s'" in problem for problem in raised.value.problems)
    assert any("blocks.done" in problem and "'retries'" in problem for problem in raised.value.problems)


def test_a_choice_can_take_an_edge_list(tmp_path: Path) -> None:
    decision = load_skill(write_skill(tmp_path, "per-item", PER_ITEM_SKILL)).blocks["ask_finding"]

    assert isinstance(decision, DecisionBlock)
    assert decision.next == {
        "fix": [
            Edge(to="ask_finding", when="{{ (history.ask_finding | length) < (inputs.findings | length) }}"),
            Edge(to="done"),
        ],
        "stop": [Edge(to="done")],
    }


def test_a_parallel_block_can_name_its_tasks(tmp_path: Path) -> None:
    skill_yaml = ALL_BLOCKS_SKILL.replace(
        "    agent: fact-checker\n", '    agent: fact-checker\n    task_name: "{{ item }}"\n'
    )

    parallel = load_skill(write_skill(tmp_path, "all-blocks", skill_yaml)).blocks["check_docs"]

    assert isinstance(parallel, ParallelBlock)
    assert parallel.task_name == "{{ item }}"
