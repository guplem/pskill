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
from tests.test_engine_blocks import (
    CHILD_SKILL,
    NAMED_PARALLEL_SKILL,
    PARALLEL_SKILL,
    PARENT_SKILL,
    PICKED_PARALLEL_SKILL,
)

REPOSITORY = Path(__file__).resolve().parent.parent
EXAMPLE_SKILLS = ["implement-issue", "review-pr", "resolve-pr-feedback", "fix-ci", "create-issue"]

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
    run: [uv, run, "{{ skill.dir }}/scripts/verify.py"]
    input: {pr: "{{ inputs.pr }}", quotes: [a, b]}
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
        {"scripts/verify.py": "import json, sys\nprint(json.load(sys.stdin))\n"},
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
    assert (
        "Do this step at most 3 times. The 4th time, ask the user whether to do it more times (in an autonomous "
        "run, decide yourself, and keep the extra times few). If not, go to step 4 (`stopped`) instead."
    ) in markdown


def test_a_cap_with_no_target_tells_the_agent_to_stop(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    uncapped = PLAN_SKILL.replace("    on_max_visits: stopped\n", "")
    write_skill(project.skills_folder, "plan-work", uncapped, PLAN_SKILL_FILES)

    markdown = skill_markdown(project, "plan-work")

    assert "The 4th time, stop instead, and tell the user that this step reached its limit." in markdown


def test_a_cap_that_never_asks_goes_on_at_once(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    capped = PLAN_SKILL.replace("    max_visits: 3\n", "    max_visits: 3\n    ask_on_max_visits: false\n")
    write_skill(project.skills_folder, "plan-work", capped, PLAN_SKILL_FILES)

    markdown = skill_markdown(project, "plan-work")

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


def test_a_script_step_names_its_command_its_input_and_its_files(tmp_path: Path) -> None:
    files = export_skill(make_project(tmp_path), "checker")
    markdown = files["checker/SKILL.md"].decode("utf-8")

    assert "`uv run <this skill's folder>/scripts/verify.py`" in markdown
    sent_input = '- `pr`: `inputs.pr`\n- `quotes`: `["a", "b"]`'
    assert f"Send it this JSON object on its standard input:\n\n{sent_input}" in markdown
    assert "The command prints JSON: write it down as `verify.json`." in markdown
    assert "If the command fails, stop and tell the user why." in markdown
    assert files["checker/scripts/verify.py"].startswith(b"import json")


def test_the_scripts_folder_ships_its_subfolders_but_not_the_python_cache(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    scripts_folder = project.skills_folder / "checker" / "scripts"
    (scripts_folder / "helpers").mkdir()
    (scripts_folder / "helpers" / "quotes.py").write_text("QUOTE = 1\n", encoding="utf-8")
    (scripts_folder / "__pycache__").mkdir()
    (scripts_folder / "__pycache__" / "verify.cpython-311.pyc").write_bytes(b"\x00")

    files = export_skill(project, "checker")

    assert sorted(path for path in files if "/scripts/" in path) == [
        "checker/scripts/helpers/quotes.py",
        "checker/scripts/verify.py",
    ]


def test_a_script_step_with_a_text_input_sends_that_text(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    skill_yaml = STATE_SKILL.replace(
        'input: {pr: "{{ inputs.pr }}", quotes: [a, b]}', 'input: "Pull request {{ inputs.pr }}"'
    )
    write_skill(project.skills_folder, "checker", skill_yaml)

    markdown = export_skill(project, "checker")["checker/SKILL.md"].decode("utf-8")

    assert "Send it this text on its standard input: Pull request `inputs.pr`" in markdown


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


# --- the example skills ---------------------------------------------------------------------------


@pytest.mark.parametrize("skill_id", EXAMPLE_SKILLS)
def test_each_example_skill_exports_to_a_plain_skill_that_an_agent_can_follow(skill_id: str) -> None:
    project = find_project(REPOSITORY)

    files = export_skill(project, skill_id)

    for path, content in files.items():
        if path.endswith("/SKILL.md"):
            exported_id = path.split("/")[0]
            skill = load_skill(project.skills_folder / exported_id)
            check_plain_skill(content.decode("utf-8"), exported_id, list(skill.blocks))


def test_an_id_that_is_not_a_skill_id_cannot_be_exported(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    outside = tmp_path / "outside" / "evil"
    write_skill(outside.parent, "evil", PLAN_SKILL.replace("id: plan-work", "id: evil"), PLAN_SKILL_FILES)

    with pytest.raises(ExportError):
        export_skill(project, "../../outside/evil")


def test_a_missing_instruction_file_stops_the_export_with_its_name(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    (project.skills_folder / "plan-work" / "instructions" / "approve_plan.md").unlink()

    with pytest.raises(ExportError, match=r"approve_plan\.md"):
        export_skill(project, "plan-work")


def test_whitespace_control_in_a_value_leaves_no_dash() -> None:
    assert plain_text("x {{- steps.a.b -}} z") == "x `a.b` z"


def test_a_list_item_with_a_when_names_its_condition_in_words(tmp_path: Path) -> None:
    write_skill(tmp_path / ".pskill" / "skills", "picked", PICKED_PARALLEL_SKILL)

    markdown = export_skill(find_project(tmp_path), "picked")["picked/SKILL.md"].decode("utf-8")

    assert '- `{"name": "always"}`\n' in markdown
    assert """- `{"name": "api"}` (only when `inputs.paths | select('matches', '^api/') | list`)""" in markdown
    assert "{{" not in markdown


def test_a_parallel_step_names_its_tasks(tmp_path: Path) -> None:
    write_skill(tmp_path / ".pskill" / "skills", "fanout", NAMED_PARALLEL_SKILL)
    (tmp_path / ".pskill" / "agents").mkdir(parents=True)
    (tmp_path / ".pskill" / "agents" / "checker.md").write_text("You check facts.", encoding="utf-8")

    markdown = export_skill(find_project(tmp_path), "fanout")["fanout/SKILL.md"].decode("utf-8")

    assert f"Name each task: {plain_text('Check {{ item }}')}." in markdown


ROLES_SKILL = """\
schema: pskill/v1
id: roles
description: Notes the files, then reviews and checks each one.
goal: Review every file.
inputs:
  files: {type: array, items: {type: string}, description: "The documents."}
entry: note
blocks:
  note:
    type: task
    instruction: "Note the files."
    output: {}
    next: review
  review:
    type: parallel
    for_each: "{{ inputs.files }}"
    agent: "{{ item }}"
    instruction: "Review {{ item }}."
    output:
      ok: {type: boolean, description: "True when the file is fine."}
    next: check
  check:
    type: parallel
    for_each: "{{ inputs.files }}"
    instruction: "Check {{ item }}."
    output:
      ok: {type: boolean, description: "True when the file is fine."}
    next: done
  done:
    type: end
    status: succeeded
"""


def roles_export(tmp_path: Path) -> dict[str, bytes]:
    write_skill(tmp_path / ".pskill" / "skills", "roles", ROLES_SKILL)
    return export_skill(find_project(tmp_path), "roles")


def test_a_step_with_no_fields_writes_down_that_it_is_done(tmp_path: Path) -> None:
    markdown = roles_export(tmp_path)["roles/SKILL.md"].decode("utf-8")

    assert "Note the files.\n\n**Write down:** that this step is done." in markdown


def test_a_skill_without_outputs_has_no_outputs_section(tmp_path: Path) -> None:
    markdown = roles_export(tmp_path)["roles/SKILL.md"].decode("utf-8")

    assert "## Outputs" not in markdown
    assert "## Inputs" in markdown


def test_a_computed_agent_over_a_computed_list_names_the_role_file_by_its_value(tmp_path: Path) -> None:
    files = roles_export(tmp_path)
    markdown = files["roles/SKILL.md"].decode("utf-8")

    assert "Give each subagent a role first: the file `subagents/<name>.md`, where the name is `item`." in markdown
    assert list(files) == ["roles/SKILL.md"]


def test_a_parallel_step_without_an_agent_gives_no_role(tmp_path: Path) -> None:
    markdown = roles_export(tmp_path)["roles/SKILL.md"].decode("utf-8")
    check_step = markdown.split("## Step 3: `check`", 1)[1].split("## Step", 1)[0]

    assert "Check `item`." in check_step
    assert "role" not in check_step


def test_a_missing_agent_file_is_left_out_of_the_export(tmp_path: Path) -> None:
    write_skill(tmp_path / ".pskill" / "skills", "fanout", PARALLEL_SKILL)

    files = export_skill(find_project(tmp_path), "fanout")

    assert list(files) == ["fanout/SKILL.md"]
    assert "`subagents/checker.md`" in files["fanout/SKILL.md"].decode("utf-8")


def test_a_skill_that_does_not_load_cannot_be_exported(tmp_path: Path) -> None:
    write_skill(tmp_path / ".pskill" / "skills", "broken", "schema: pskill/v1\nid: broken\n")

    with pytest.raises(ExportError, match=r"The skill 'broken' does not load: .*description"):
        export_skill(find_project(tmp_path), "broken")


def test_an_elif_tag_reads_as_else_when() -> None:
    text = "{% if a %}one{% elif b %}two{% else %}three{% endif %}"

    assert plain_text(text) == "(only when `a`:) one(else, when `b`:) two(otherwise:) three(end)"
