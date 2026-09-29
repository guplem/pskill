"""Tests for pskill_runner.validator."""

from pathlib import Path

from pskill_runner.skill_loader import load_catalog, load_skill
from pskill_runner.validator import Problem, validate_skill
from tests.skill_files import PER_ITEM_SKILL, PLAN_SKILL, PLAN_SKILL_FILES, write_skill


def problems_for(tmp_path: Path, skill_yaml: str, files: dict[str, str] | None = None) -> list[Problem]:
    skill = load_skill(write_skill(tmp_path, "plan-work", skill_yaml, PLAN_SKILL_FILES if files is None else files))
    return validate_skill(skill)


def messages(problems: list[Problem], level: str) -> list[str]:
    return [f"{problem.location}: {problem.message}" for problem in problems if problem.level == level]


def test_the_example_skill_has_no_problems(tmp_path: Path) -> None:
    assert problems_for(tmp_path, PLAN_SKILL) == []


def test_an_edge_to_a_missing_block_is_an_error(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace("next: {approve: done, stop: stopped}", "next: {approve: finish, stop: stopped}")

    assert "blocks.approve_plan: the target 'finish' is not a block" in messages(
        problems_for(tmp_path, skill_yaml), "error"
    )


def test_an_unreachable_block_is_an_error(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL + "  orphan:\n    type: end\n    status: failed\n"

    assert "blocks.orphan: no path from the entry reaches this block" in messages(
        problems_for(tmp_path, skill_yaml), "error"
    )


def test_a_choice_map_must_match_the_choices(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace("next: {approve: done, stop: stopped}", "next: {approve: done, later: stopped}")

    errors = messages(problems_for(tmp_path, skill_yaml), "error")

    assert "blocks.approve_plan: the choice 'stop' has no entry in next" in errors
    assert "blocks.approve_plan: next has 'later', which is not a choice" in errors


def test_a_decision_without_choices_needs_edges_and_a_human_decider(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace(
        '    decider: human\n    instruction: "Ask', '    decider: agent\n    instruction: "Ask'
    )

    assert "blocks.ask_user: an agent decision needs choices (use a task block for free-form work)" in messages(
        problems_for(tmp_path, skill_yaml), "error"
    )


def test_a_when_must_be_exactly_one_expression(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace(
        "when: \"{{ steps.create_plan.status == 'question' }}\"", "when: \"steps.create_plan.status == 'question'\""
    )

    assert "blocks.create_plan: a when must be exactly one {{ ... }}" in messages(
        problems_for(tmp_path, skill_yaml), "error"
    )


def test_a_broken_expression_is_an_error(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace(
        'instruction: "Write a plan for {{ inputs.topic }}."', 'instruction: "{{ inputs. }}"'
    )

    errors = messages(problems_for(tmp_path, skill_yaml), "error")

    assert any(error.startswith("blocks.create_plan: the {{ }} does not compile") for error in errors)


def test_references_to_unknown_inputs_and_blocks_are_errors(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace("{{ inputs.topic }}", "{{ inputs.subject }} {{ steps.draft.text }}")

    errors = messages(problems_for(tmp_path, skill_yaml), "error")

    assert "blocks.create_plan: 'inputs.subject' is not a declared input" in errors
    assert "blocks.create_plan: 'steps.draft' is not a block" in errors


def test_references_inside_instruction_files_are_checked(tmp_path: Path) -> None:
    files = {"instructions/approve_plan.md": "Show {{ history.nothing }}"}

    assert "blocks.approve_plan: 'history.nothing' is not a block" in messages(
        problems_for(tmp_path, PLAN_SKILL, files), "error"
    )


def test_a_missing_instruction_file_is_an_error(tmp_path: Path) -> None:
    assert "blocks.approve_plan: the file 'instructions/approve_plan.md' does not exist" in messages(
        problems_for(tmp_path, PLAN_SKILL, files={}), "error"
    )


def test_top_level_fields_need_a_description(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace(
        'plan: {type: string, description: "The plan so far."}', "plan: {type: string}"
    ).replace('topic: {type: string, description: "What to plan."}', "topic: {type: string}")

    errors = messages(problems_for(tmp_path, skill_yaml), "error")

    assert "blocks.create_plan: the output field 'plan' needs a description" in errors
    assert "inputs: the field 'topic' needs a description" in errors


def test_a_succeeded_end_must_give_every_required_output(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace("outputs: {result: approved}", "outputs: {}")

    assert "blocks.done: a succeeded end must give the required output 'result'" in messages(
        problems_for(tmp_path, skill_yaml), "error"
    )


def test_an_end_cannot_give_an_undeclared_output(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace("outputs: {result: stopped}", "outputs: {result: stopped, reason: x}")

    assert "blocks.stopped: 'reason' is not a declared skill output" in messages(
        problems_for(tmp_path, skill_yaml), "error"
    )


def test_a_long_description_is_an_error(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace("description: Plan a piece of work with the user.", "description: " + "x" * 1025)

    assert "description: the skill description has 1025 characters (the limit is 1024)" in messages(
        problems_for(tmp_path, skill_yaml), "error"
    )


def test_a_loop_with_no_visit_cap_is_a_warning(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace("    max_visits: 3\n    on_max_visits: stopped\n", "")

    assert messages(problems_for(tmp_path, skill_yaml), "warning") == [
        "blocks.ask_user: this loop (ask_user, create_plan) has no block with max_visits"
    ]


def test_a_condition_list_that_ends_with_a_when_is_a_warning(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace(
        "      - to: approve_plan",
        "      - when: \"{{ steps.create_plan.status == 'finished' }}\"\n        to: approve_plan",
    )

    assert "blocks.create_plan: the last edge has a when, so no edge may match" in messages(
        problems_for(tmp_path, skill_yaml), "warning"
    )


def test_an_unused_instruction_file_is_a_warning(tmp_path: Path) -> None:
    files = {**PLAN_SKILL_FILES, "instructions/old.md": "Not used."}

    assert messages(problems_for(tmp_path, PLAN_SKILL, files), "warning") == [
        "instructions/old.md: no block uses this instruction file"
    ]


CALLER_SKILL = """\
schema: pskill/v1
id: caller
description: Calls another skill.
goal: Use the child.
entry: research
blocks:
  research:
    type: parallel
    for_each:
      - {agent: scout, focus: code}
      - {agent: ghost, focus: docs}
    agent: "{{ item.agent }}"
    instruction: "Look at the {{ item.focus }}."
    output:
      report: {type: string, description: "What you found."}
    next: fetch
  fetch:
    type: script
    run: [echo, "{{ steps.research.results }}"]
    next: child
  child:
    type: call
    skill: callee
    inputs: {topic: "{{ steps.fetch.stdout }}", extra: 1}
    next: done
  done:
    type: end
    status: succeeded
"""

CALLEE_SKILL = """\
schema: pskill/v1
id: callee
description: Is called.
goal: Answer the caller.
inputs:
  topic: {type: string, description: "The topic."}
  depth: {type: integer, description: "How deep."}
entry: done
blocks:
  done:
    type: end
    status: succeeded
"""


def catalog_problems(tmp_path: Path, caller_yaml: str = CALLER_SKILL, callee_yaml: str = CALLEE_SKILL) -> list[str]:
    skills_folder = tmp_path / "skills"
    write_skill(skills_folder, "caller", caller_yaml)
    write_skill(skills_folder, "callee", callee_yaml)
    agents_folder = tmp_path / "agents"
    agents_folder.mkdir()
    (agents_folder / "scout.md").write_text("You find code.", encoding="utf-8")
    catalog = load_catalog(skills_folder, agents_folder)
    return messages(validate_skill(catalog.skills["caller"], catalog), "error")


def test_a_call_needs_known_inputs_and_every_required_input(tmp_path: Path) -> None:
    errors = catalog_problems(tmp_path)

    assert "blocks.child: 'extra' is not an input of the skill 'callee'" in errors
    assert "blocks.child: the required input 'depth' of the skill 'callee' is missing" in errors


def test_a_call_to_an_unknown_skill_is_an_error(tmp_path: Path) -> None:
    errors = catalog_problems(tmp_path, CALLER_SKILL.replace("skill: callee", "skill: nobody"))

    assert "blocks.child: there is no skill 'nobody'" in errors


def test_a_call_cycle_is_an_error(tmp_path: Path) -> None:
    looping_callee = CALLEE_SKILL.replace(
        "entry: done\nblocks:\n",
        "entry: back\nblocks:\n  back:\n    type: call\n    skill: caller\n    next: done\n",
    )

    errors = catalog_problems(tmp_path, callee_yaml=looping_callee)

    assert "blocks.child: the call to 'callee' makes a cycle (caller > callee > caller)" in errors


def test_a_missing_agent_file_is_an_error(tmp_path: Path) -> None:
    assert "blocks.research: there is no agent file 'ghost.md' in .pskill/agents/" in catalog_problems(tmp_path)


def test_references_in_script_arguments_and_call_inputs_are_checked(tmp_path: Path) -> None:
    errors = catalog_problems(tmp_path, CALLER_SKILL.replace("{{ steps.fetch.stdout }}", "{{ steps.fetched.stdout }}"))

    assert "blocks.child: 'steps.fetched' is not a block" in errors


def test_parallel_output_fields_need_a_description(tmp_path: Path) -> None:
    errors = catalog_problems(tmp_path, CALLER_SKILL.replace(', description: "What you found."', ""))

    assert "blocks.research: the output field 'report' needs a description" in errors


def per_item_problems(tmp_path: Path, skill_yaml: str = PER_ITEM_SKILL) -> list[Problem]:
    return validate_skill(load_skill(write_skill(tmp_path, "per-item", skill_yaml)))


def test_a_choice_with_an_edge_list_is_valid(tmp_path: Path) -> None:
    assert per_item_problems(tmp_path) == []


def test_a_choice_edge_list_is_checked_like_any_edge_list(tmp_path: Path) -> None:
    skill_yaml = PER_ITEM_SKILL.replace(
        "        - to: done\n", '        - when: "{{ true }}"\n          to: done\n'
    ).replace(
        "      stop: done\n",
        '      stop:\n        - when: "steps.ask_finding.choice"\n          to: done\n        - to: done\n',
    )

    problems = per_item_problems(tmp_path, skill_yaml)

    assert "blocks.ask_finding: the choice 'fix': the last edge has a when, so no edge may match" in messages(
        problems, "warning"
    )
    assert "blocks.ask_finding: a when must be exactly one {{ ... }}" in messages(problems, "error")


def test_an_edge_list_for_a_missing_choice_is_reported(tmp_path: Path) -> None:
    skill_yaml = PER_ITEM_SKILL.replace("      fix:\n        - when", "      mend:\n        - when")

    errors = messages(per_item_problems(tmp_path, skill_yaml), "error")

    assert "blocks.ask_finding: the choice 'fix' has no entry in next" in errors
    assert "blocks.ask_finding: next has 'mend', which is not a choice" in errors
