"""Tests for pskill_runner.skill_export: a skill as plain Markdown skills that work without pskill."""

import io
import re
import zipfile
from pathlib import Path

import pytest

from pskill_runner.project import Project, find_project
from pskill_runner.skill_export import ExportError, export_skill, export_zip, plain_text
from pskill_runner.skill_loader import load_skill
from tests.skill_files import PER_ITEM_SKILL, PLAN_SKILL, PLAN_SKILL_FILES, write_skill
from tests.test_engine_blocks import CHILD_SKILL, PARALLEL_SKILL, PARENT_SKILL

REPOSITORY = Path(__file__).resolve().parent.parent
PROOF_SKILLS = ["implement-issue", "review-pr", "create-issue"]

STATE_SKILL = """\
schema: pskill/v1
id: checker
description: Checks quotes with a script.
goal: Keep only the real quotes.
inputs:
  pr: {type: integer, description: "The pull request."}
outputs:
  kept: {type: integer, description: "How many quotes are real."}
entry: verify
blocks:
  verify:
    type: script
    run: [uv, run, "{{ skill.dir }}/scripts/verify.py", "{{ inputs.pr }}"]
    parse: json
    retries: 0
    next: done
  done:
    type: end
    status: succeeded
    outputs: {kept: "{{ steps.verify.json.kept | length }}"}
"""


def make_project(tmp_path: Path) -> Project:
    skills_folder = tmp_path / ".pskill" / "skills"
    write_skill(skills_folder, "plan-work", PLAN_SKILL, PLAN_SKILL_FILES)
    write_skill(skills_folder, "parent", PARENT_SKILL)
    write_skill(skills_folder, "child", CHILD_SKILL.replace("id: child\n", "id: child\ninvocation: internal\n"))
    write_skill(skills_folder, "fanout", PARALLEL_SKILL)
    write_skill(skills_folder, "per-item", PER_ITEM_SKILL)
    write_skill(
        skills_folder,
        "checker",
        STATE_SKILL,
        {"scripts/verify.py": "import os\nprint(open(os.environ['PSKILL_STATE_FILE']).read())\n"},
    )
    agents_folder = tmp_path / ".pskill" / "agents"
    agents_folder.mkdir(parents=True)
    (agents_folder / "checker.md").write_bytes(b"You check facts.\n")
    return find_project(tmp_path)


def skill_markdown(project: Project, skill_id: str) -> str:
    return export_skill(project, skill_id)[f"{skill_id}/SKILL.md"].decode("utf-8")


def step_numbers(markdown: str) -> dict[str, int]:
    return {match[1]: int(match[0]) for match in re.findall(r"^## Step (\d+): `([a-z0-9_]+)`", markdown, re.M)}


def check_plain_skill(markdown: str, skill_id: str, block_ids: list[str]) -> None:
    """What every export must hold: frontmatter, every block as a step, valid step links, no pskill syntax."""
    assert markdown.startswith(f"---\nname: {skill_id}\ndescription: ")
    steps = step_numbers(markdown)
    assert sorted(steps) == sorted(block_ids)
    assert sorted(steps.values()) == list(range(1, len(block_ids) + 1))
    for number in re.findall(r"go to step (\d+)", markdown):
        assert 1 <= int(number) <= len(block_ids)
    for pskill_only in ("{{", "}}", "{%", "%}", "pskill.py"):
        assert pskill_only not in markdown


# --- the Markdown ---------------------------------------------------------------------------------


def test_the_export_has_the_frontmatter_and_every_block_as_a_step_in_graph_order(tmp_path: Path) -> None:
    markdown = skill_markdown(make_project(tmp_path), "plan-work")

    check_plain_skill(markdown, "plan-work", ["create_plan", "ask_user", "approve_plan", "done", "stopped"])
    assert '\ndescription: "Plan a piece of work with the user."\n---\n' in markdown
    assert step_numbers(markdown) == {"create_plan": 1, "ask_user": 2, "approve_plan": 3, "stopped": 4, "done": 5}


def test_a_step_has_its_instruction_its_fields_and_its_edges_in_plain_words(tmp_path: Path) -> None:
    markdown = skill_markdown(make_project(tmp_path), "plan-work")

    assert "Write a plan for `inputs.topic`." in markdown
    assert "- `status` (text, one of: `finished`, `question`): finished when nothing is open." in markdown
    assert "- `question` (text, optional): The open question." in markdown
    assert "- When `create_plan.status == 'question'`: go to step 2 (`ask_user`)." in markdown
    assert "- Otherwise: go to step 3 (`approve_plan`)." in markdown
    assert "Do this step at most 3 times. The 4th time, go to step 4 (`stopped`) instead." in markdown


def test_a_human_decision_asks_the_user_and_offers_the_choices(tmp_path: Path) -> None:
    markdown = skill_markdown(make_project(tmp_path), "plan-work")

    assert "Ask the user one question, and wait for the answer." in markdown
    assert "Show the plan:\n\n`create_plan.plan`" in markdown
    assert "- `approve`: Accept the plan." in markdown
    assert "- If the choice is `approve`: go to step 5 (`done`)." in markdown
    assert "- `choice`: the choice that was picked." in markdown


def test_an_end_step_names_its_status_outputs_and_report(tmp_path: Path) -> None:
    markdown = skill_markdown(make_project(tmp_path), "plan-work")

    assert "The skill ends here with the status **succeeded**." in markdown
    assert "- `result`: approved" in markdown
    assert "Tell the user: Tell the user the plan is approved." in markdown


def test_a_choice_with_an_edge_list_names_each_condition(tmp_path: Path) -> None:
    markdown = skill_markdown(make_project(tmp_path), "per-item")

    assert (
        "- If the choice is `fix` and `(ask_finding.all_visits | length) < (inputs.findings | length)`: "
        "go to step 1 (`ask_finding`)." in markdown
    )
    assert "- If the choice is `fix`, and no condition above matches: go to step 2 (`done`)." in markdown


def test_a_script_step_names_its_command_its_files_and_the_state_file(tmp_path: Path) -> None:
    files = export_skill(make_project(tmp_path), "checker")
    markdown = files["checker/SKILL.md"].decode("utf-8")

    assert "`uv run <this skill's folder>/scripts/verify.py <inputs.pr>`" in markdown
    assert "The command prints JSON: write it down as `verify.json`." in markdown
    assert "PSKILL_STATE_FILE" in markdown
    assert "If the command fails, stop and tell the user why." in markdown
    assert files["checker/scripts/verify.py"].startswith(b"import os")


def test_a_parallel_step_uses_subagents_and_ships_the_agent_role(tmp_path: Path) -> None:
    files = export_skill(make_project(tmp_path), "fanout")
    markdown = files["fanout/SKILL.md"].decode("utf-8")

    assert "For each item of `inputs.files`" in markdown
    assert "one subagent per item" in markdown
    assert "do the items one by one yourself" in markdown
    assert "`subagents/checker.md`" in markdown
    assert files["fanout/subagents/checker.md"] == b"You check facts.\n"


def test_a_call_step_exports_the_child_skill_next_to_it(tmp_path: Path) -> None:
    files = export_skill(make_project(tmp_path), "parent")
    markdown = files["parent/SKILL.md"].decode("utf-8")
    child = files["child/SKILL.md"].decode("utf-8")

    assert "Follow the skill `child` in the folder `child/` next to this skill's folder" in markdown
    assert "- `name`: Ada" in markdown
    assert "`child.status`" in markdown
    check_plain_skill(child, "child", ["greet", "done"])
    assert "disable-model-invocation: true" in child


def test_an_unknown_skill_cannot_be_exported(tmp_path: Path) -> None:
    with pytest.raises(ExportError):
        export_skill(make_project(tmp_path), "missing")


def test_the_zip_holds_every_file_of_the_export(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    archive = zipfile.ZipFile(io.BytesIO(export_zip(project, "parent")))

    assert sorted(archive.namelist()) == ["child/SKILL.md", "parent/SKILL.md"]


def test_a_value_inside_code_stays_a_bare_name() -> None:
    text = (
        "Run `gh issue view {{ steps.read.number }}`, then:\n```\necho {{ inputs.topic }}\n```\nand {{ inputs.topic }}."
    )

    assert (
        plain_text(text) == "Run `gh issue view read.number`, then:\n```\necho inputs.topic\n```\nand `inputs.topic`."
    )


# --- the proof skills -----------------------------------------------------------------------------


@pytest.mark.parametrize("skill_id", PROOF_SKILLS)
def test_each_proof_skill_exports_to_a_plain_skill_that_an_agent_can_follow(skill_id: str) -> None:
    project = find_project(REPOSITORY)

    files = export_skill(project, skill_id)

    for path, content in files.items():
        if path.endswith("/SKILL.md"):
            exported_id = path.split("/")[0]
            skill = load_skill(project.skills_folder / exported_id)
            check_plain_skill(content.decode("utf-8"), exported_id, list(skill.blocks))
