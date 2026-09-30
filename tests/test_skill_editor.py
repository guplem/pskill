"""Tests for pskill_runner.skill_editor: saving changes to `skill.yaml` without losing comments."""

import difflib
import shutil
from pathlib import Path

import pytest

from pskill_runner.project import Project, find_project
from pskill_runner.skill_editor import EditError, add_block, delete_block, update_block
from pskill_runner.skill_loader import load_skill
from pskill_runner.skill_model import DecisionBlock, Edge
from tests.skill_files import PLAN_SKILL, PLAN_SKILL_FILES, write_skill

REPOSITORY = Path(__file__).resolve().parent.parent

COMMENTED_SKILL = PLAN_SKILL.replace(
    "blocks:\n  create_plan:\n", "blocks:\n  # The planning loop.\n  create_plan:  # the first block\n"
).replace("  ask_user:\n", "  # Questions go here.\n  ask_user:\n")


def make_project(tmp_path: Path, skill_yaml: str = COMMENTED_SKILL) -> Project:
    write_skill(tmp_path / ".pskill" / "skills", "plan-work", skill_yaml, PLAN_SKILL_FILES)
    return find_project(tmp_path)


def skill_text(project: Project, skill_id: str = "plan-work") -> str:
    return (project.skills_folder / skill_id / "skill.yaml").read_text(encoding="utf-8")


def changed_lines(before: str, after: str) -> list[str]:
    return [
        line
        for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]


# --- update ----------------------------------------------------------------------------------------


def test_an_update_changes_only_the_lines_of_its_block_and_keeps_every_comment(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    before = skill_text(project)

    update_block(project, "plan-work", "ask_user", {"description": "Ask one question.", "max_visits": 4})

    after = skill_text(project)
    assert changed_lines(before, after) == ["+    description: Ask one question.", "+    max_visits: 4"]
    assert "  # The planning loop.\n  create_plan:  # the first block\n" in after
    assert "  # Questions go here.\n" in after


def test_none_removes_a_key(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    update_block(project, "plan-work", "create_plan", {"max_visits": None, "on_max_visits": None})

    block = load_skill(project.skills_folder / "plan-work").blocks["create_plan"]
    assert (block.max_visits, block.on_max_visits) == (None, None)


def test_next_is_written_in_its_shortest_form(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    update_block(project, "plan-work", "ask_user", {"next": [{"when": "", "to": "approve_plan"}]})
    update_block(
        project,
        "plan-work",
        "approve_plan",
        {"next": {"approve": [{"to": "done"}], "stop": [{"when": "{{ true }}", "to": "stopped"}, {"to": "done"}]}},
    )

    text = skill_text(project)
    assert "    next: approve_plan\n" in text
    assert (
        '      approve: done\n      stop:\n        - when: "{{ true }}"\n          to: stopped\n        - to: done\n'
        in text
    )
    approve_plan = load_skill(project.skills_folder / "plan-work").blocks["approve_plan"]
    assert isinstance(approve_plan, DecisionBlock)
    assert approve_plan.next == {
        "approve": [Edge(to="done")],
        "stop": [Edge(to="stopped", when="{{ true }}"), Edge(to="done")],
    }


def test_a_change_with_a_structure_error_is_refused_and_the_file_stays(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    before = skill_text(project)

    with pytest.raises(EditError) as raised:
        update_block(project, "plan-work", "create_plan", {"max_visits": 0})

    assert any("max_visits" in problem for problem in raised.value.problems)
    assert skill_text(project) == before


def test_a_key_that_the_editor_does_not_know_is_refused(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    with pytest.raises(EditError, match="output"):
        update_block(project, "plan-work", "create_plan", {"output": {}})


def test_an_instruction_file_gets_its_new_text(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    update_block(project, "plan-work", "approve_plan", {"instruction_text": "Show the plan, then ask.\n"})

    instruction_file = project.skills_folder / "plan-work" / "instructions" / "approve_plan.md"
    assert instruction_file.read_text(encoding="utf-8") == "Show the plan, then ask.\n"


def test_an_update_keeps_an_alias_as_an_alias(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace(
        "blocks:\n", "x-status: &status {type: string, enum: [finished, question]}\nblocks:\n"
    )
    skill_yaml = skill_yaml.replace(
        '      status: {type: string, enum: [finished, question], description: "finished when nothing is open."}',
        '      status: {<<: *status, description: "finished when nothing is open."}',
    )
    project = make_project(tmp_path, skill_yaml)

    update_block(project, "plan-work", "create_plan", {"description": "Plan."})

    assert '      status: {<<: *status, description: "finished when nothing is open."}\n' in skill_text(project)


@pytest.mark.parametrize(
    ("skill_id", "middle_block"),
    [("implement-issue", "check_applies"), ("review-pr", "plan_review"), ("create-issue", "judge_duplicates")],
)
def test_editing_a_proof_skill_block_changes_nothing_else(tmp_path: Path, skill_id: str, middle_block: str) -> None:
    shutil.copytree(REPOSITORY / ".pskill" / "skills" / skill_id, tmp_path / ".pskill" / "skills" / skill_id)
    project = find_project(tmp_path)
    before = skill_text(project, skill_id)
    block_ids = list(load_skill(project.skills_folder / skill_id).blocks)
    for block_id in (middle_block, block_ids[-1]):
        # Every proof block has a description: remove it, then add it back as a new key.
        update_block(project, skill_id, block_id, {"description": None})
        without = skill_text(project, skill_id)
        assert [line[:17] for line in changed_lines(before, without)] == ["-    description:"]

        update_block(project, skill_id, block_id, {"description": f"{block_id} edited."})

        after = skill_text(project, skill_id)
        assert changed_lines(without, after) == [f"+    description: {block_id} edited."]
        block_lines = after.split(f"\n  {block_id}:\n", 1)[1].splitlines()
        assert block_lines[0].startswith("    type: ")
        assert block_lines[1] == f"    description: {block_id} edited."  # a new key goes where authors put it
        before = after


def test_changing_the_last_key_of_a_middle_block_keeps_the_blank_line_after_it(tmp_path: Path) -> None:
    shutil.copytree(REPOSITORY / ".pskill" / "skills" / "review-pr", tmp_path / ".pskill" / "skills" / "review-pr")
    project = find_project(tmp_path)
    before = skill_text(project, "review-pr")

    update_block(
        project,
        "review-pr",
        "plan_review",
        {"next": [{"when": "{{ inputs.pr > 0 }}", "to": "analyze"}, {"to": "report"}]},
    )

    assert changed_lines(before, skill_text(project, "review-pr")) == [
        "-    next: analyze",
        "+    next:",
        '+      - when: "{{ inputs.pr > 0 }}"',
        "+        to: analyze",
        "+      - to: report",
    ]


def test_a_comment_between_two_blocks_stays_when_the_block_above_changes(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace(
        "    next: create_plan\n  approve_plan:", "    next: create_plan\n  # between blocks\n\n  approve_plan:"
    )
    project = make_project(tmp_path, skill_yaml)
    before = skill_text(project)

    update_block(project, "plan-work", "ask_user", {"description": "Ask."})

    assert changed_lines(before, skill_text(project)) == ["+    description: Ask."]


def test_a_broken_alias_is_a_problem_not_a_crash(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace("    next: create_plan\n", "    next: &back create_plan\n").replace(
        "    status: cancelled\n", "    status: cancelled\n    description: *back\n"
    )
    project = make_project(tmp_path, skill_yaml)

    with pytest.raises(EditError, match="not valid YAML"):
        update_block(project, "plan-work", "ask_user", {"next": "approve_plan"})


def test_a_file_with_crlf_line_ends_keeps_them(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    path = project.skills_folder / "plan-work" / "skill.yaml"
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))

    update_block(project, "plan-work", "ask_user", {"description": "Ask."})

    data = path.read_bytes()
    assert b"\n" not in data.replace(b"\r\n", b"")
    assert b"    description: Ask.\r\n" in data


# --- add and delete --------------------------------------------------------------------------------


@pytest.mark.parametrize("block_type", ["task", "decision", "parallel", "script", "call", "end"])
def test_a_new_block_of_each_type_loads(tmp_path: Path, block_type: str) -> None:
    project = make_project(tmp_path)

    add_block(project, "plan-work", "new_step", block_type)

    skill = load_skill(project.skills_folder / "plan-work")
    assert type(skill.blocks["new_step"]).__name__.lower().startswith(block_type)
    assert list(skill.blocks)[-1] == "new_step"


def test_a_new_block_needs_a_new_valid_id(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    with pytest.raises(EditError, match="already has"):
        add_block(project, "plan-work", "done", "end")
    with pytest.raises(EditError, match="not a block id"):
        add_block(project, "plan-work", "New Step", "end")


def test_a_block_that_an_edge_leads_to_cannot_be_deleted(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    with pytest.raises(EditError, match="create_plan, approve_plan"):
        delete_block(project, "plan-work", "stopped")


def test_deleting_a_block_removes_its_lines_and_its_comments(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    add_block(project, "plan-work", "extra", "end")
    before = skill_text(project)

    delete_block(project, "plan-work", "extra")

    assert "extra" not in skill_text(project)
    assert "  # Questions go here.\n" in skill_text(project)
    assert skill_text(project) == before.replace("\n  extra:\n    type: end\n    status: succeeded\n", "")


def test_an_id_that_is_not_a_skill_id_cannot_be_edited(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    with pytest.raises(EditError, match="no skill"):
        update_block(project, "../plan-work", "done", {"description": "x"})
