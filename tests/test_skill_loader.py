"""Tests for pskill_runner.skill_loader."""

from pathlib import Path

import pytest

from pskill_runner.field_types import FieldSpec
from pskill_runner.skill_loader import SkillLoadError, load_skill
from pskill_runner.skill_model import DecisionBlock, Edge, EndBlock, TaskBlock
from tests.skill_files import PLAN_SKILL, PLAN_SKILL_FILES, write_skill


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
    assert decision.next == {"approve": "done", "stop": "stopped"}
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

    assert raised.value.problems == ["blocks.done: unknown block type 'finish' (known types: decision, end, task)"]


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
