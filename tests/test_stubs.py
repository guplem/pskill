"""Tests for pskill_runner.stubs: the generated SKILL.md files that make skills visible to harnesses."""

from pathlib import Path

import pytest

from pskill_runner.project import Project, find_project
from pskill_runner.skill_loader import load_catalog, load_skill
from pskill_runner.stubs import GENERATED_MARKER, StubError, render_pskill_stub, render_stub, sync_stubs
from tests.skill_files import PLAN_SKILL, PLAN_SKILL_FILES, write_skill


def make_project(tmp_path: Path, skill_yaml: str = PLAN_SKILL) -> Project:
    write_skill(tmp_path / ".pskill" / "skills", "plan-work", skill_yaml, PLAN_SKILL_FILES)
    return find_project(tmp_path)


def test_a_stub_has_the_frontmatter_and_the_start_command(tmp_path: Path) -> None:
    skill = load_skill(make_project(tmp_path).skills_folder / "plan-work")

    stub = render_stub(skill)

    assert stub.startswith('---\nname: plan-work\ndescription: "Plan a piece of work with the user."\n---\n')
    assert GENERATED_MARKER in stub
    assert "- `topic` (string): What to plan." in stub
    assert "uv run .pskill/pskill.py start plan-work --harness auto --input topic=<value>" in stub
    assert "--inputs -" in stub
    assert "--mode autonomous" in stub


TOPIC_INPUT = '  topic: {type: string, description: "What to plan."}\n'
OPTIONAL_INPUTS_SKILL = PLAN_SKILL.replace(
    TOPIC_INPUT,
    TOPIC_INPUT
    + '  depth: {type: integer, optional: true, default: 2, description: "How deep."}\n'
    + '  notes: {type: string, optional: true, description: "Extra notes."}\n',
)


def test_a_stub_tells_the_agent_to_ask_for_a_missing_required_input(tmp_path: Path) -> None:
    skill = load_skill(make_project(tmp_path).skills_folder / "plan-work")

    stub = render_stub(skill)

    assert "   Ask the user for each required input that the request does not give, before you run `start`.\n" in stub


def test_a_skill_with_only_optional_inputs_asks_for_nothing(tmp_path: Path) -> None:
    only_optional = PLAN_SKILL.replace(TOPIC_INPUT, TOPIC_INPUT.replace("string,", "string, optional: true,"))
    skill = load_skill(make_project(tmp_path, only_optional).skills_folder / "plan-work")

    stub = render_stub(skill)

    assert "Ask the user" not in stub
    assert "start plan-work --harness auto`" in stub


def test_an_optional_input_shows_its_default(tmp_path: Path) -> None:
    skill = load_skill(make_project(tmp_path, OPTIONAL_INPUTS_SKILL).skills_folder / "plan-work")

    stub = render_stub(skill)

    assert "- `depth` (integer, optional, default: 2): How deep." in stub
    assert "- `notes` (string, optional): Extra notes." in stub


def test_the_start_command_names_only_the_required_inputs(tmp_path: Path) -> None:
    skill = load_skill(make_project(tmp_path, OPTIONAL_INPUTS_SKILL).skills_folder / "plan-work")

    stub = render_stub(skill)

    assert "Run: `uv run .pskill/pskill.py start plan-work --harness auto --input topic=<value>`\n" in stub
    assert "   Add `--input <name>=<value>` for each optional input that the request gives.\n" in stub


def test_a_stub_holds_the_goal_and_the_loop_rules_once(tmp_path: Path) -> None:
    skill = load_skill(make_project(tmp_path).skills_folder / "plan-work")

    stub = render_stub(skill)

    assert "Goal: Produce a plan that the user approved.\n" in stub
    assert "Do only that step, then run the submit command at its end." in stub
    assert "never stop before the end" in stub
    assert "`$cannot_complete: <reason>`" in stub
    assert "uv run .pskill/pskill.py pause <run-id>" in stub


def test_a_manual_skill_stub_forbids_model_invocation(tmp_path: Path) -> None:
    skill = load_skill(
        make_project(tmp_path, PLAN_SKILL.replace("goal:", "invocation: manual\ngoal:")).skills_folder / "plan-work"
    )

    assert "disable-model-invocation: true\n" in render_stub(skill)


def test_sync_writes_one_stub_per_folder_plus_the_pskill_stub(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    changes = sync_stubs(project, load_catalog(project.skills_folder, project.agents_folder), check_only=False)

    for folder in (".agents/skills", ".claude/skills"):
        assert (tmp_path / folder / "plan-work" / "SKILL.md").is_file()
        assert (tmp_path / folder / "pskill" / "SKILL.md").is_file()
    assert len(changes) == 4
    assert {change.action for change in changes} == {"created"}


def test_the_pskill_stub_tells_how_to_wait_on_background_work() -> None:
    assert (
        "- Wait on background work, in the background (Claude Code only): "
        '`uv run .pskill/pskill.py wait <run-id> --reason "<what>"`' in render_pskill_stub()
    )


def test_sync_updates_a_stub_when_a_parent_folder_has_the_name_of_the_skill(tmp_path: Path) -> None:
    project = make_project(tmp_path / "pskill")
    stub = tmp_path / "pskill" / ".claude" / "skills" / "pskill" / "SKILL.md"
    stub.parent.mkdir(parents=True)
    stub.write_text(f"{GENERATED_MARKER}\nold text\n", encoding="utf-8")

    sync_stubs(project, load_catalog(project.skills_folder, project.agents_folder), check_only=False)

    assert stub.read_text(encoding="utf-8") == render_pskill_stub()


def test_sync_is_idempotent(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    catalog = load_catalog(project.skills_folder, project.agents_folder)
    sync_stubs(project, catalog, check_only=False)

    assert sync_stubs(project, catalog, check_only=False) == []


def test_check_only_reports_changes_without_writing(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    changes = sync_stubs(project, load_catalog(project.skills_folder, project.agents_folder), check_only=True)

    assert len(changes) == 4
    assert not (tmp_path / ".claude").exists()


def test_a_changed_description_updates_the_stub(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    sync_stubs(project, load_catalog(project.skills_folder, project.agents_folder), check_only=False)
    make_project(tmp_path, PLAN_SKILL.replace("Plan a piece of work with the user.", "Plan work."))

    changes = sync_stubs(project, load_catalog(project.skills_folder, project.agents_folder), check_only=False)

    assert {(change.path.parent.name, change.action) for change in changes} == {("plan-work", "updated")}
    assert 'description: "Plan work."' in (tmp_path / ".claude/skills/plan-work/SKILL.md").read_text(encoding="utf-8")


def test_the_stub_of_a_removed_skill_is_deleted(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    sync_stubs(project, load_catalog(project.skills_folder, project.agents_folder), check_only=False)
    (project.skills_folder / "plan-work" / "skill.yaml").unlink()

    changes = sync_stubs(project, load_catalog(project.skills_folder, project.agents_folder), check_only=False)

    assert {(change.path.parent.name, change.action) for change in changes} == {("plan-work", "deleted")}
    assert not (tmp_path / ".claude/skills/plan-work").exists()


def test_a_hand_written_skill_with_the_same_name_stops_sync(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    hand_written = tmp_path / ".claude" / "skills" / "plan-work" / "SKILL.md"
    hand_written.parent.mkdir(parents=True)
    hand_written.write_text("---\nname: plan-work\n---\nMine.\n", encoding="utf-8")

    with pytest.raises(StubError, match="hand-written"):
        sync_stubs(project, load_catalog(project.skills_folder, project.agents_folder), check_only=False)

    assert hand_written.read_text(encoding="utf-8").endswith("Mine.\n")


def test_other_hand_written_skills_are_left_alone(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    other = tmp_path / ".claude" / "skills" / "write-commit" / "SKILL.md"
    other.parent.mkdir(parents=True)
    other.write_text("---\nname: write-commit\n---\nRules.\n", encoding="utf-8")

    sync_stubs(project, load_catalog(project.skills_folder, project.agents_folder), check_only=False)

    assert other.read_text(encoding="utf-8").endswith("Rules.\n")


def test_internal_skills_get_no_stub(tmp_path: Path) -> None:
    project = make_project(tmp_path, PLAN_SKILL.replace("goal:", "invocation: internal\ngoal:"))

    sync_stubs(project, load_catalog(project.skills_folder, project.agents_folder), check_only=False)

    assert not (tmp_path / ".claude/skills/plan-work").exists()
    assert (tmp_path / ".claude/skills/pskill/SKILL.md").is_file()


def test_stub_folders_come_from_the_config(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    (tmp_path / ".pskill" / "config.yaml").write_text("stub_folders: [.agents/skills]\n", encoding="utf-8")
    project = find_project(tmp_path)

    sync_stubs(project, load_catalog(project.skills_folder, project.agents_folder), check_only=False)

    assert (tmp_path / ".agents/skills/plan-work/SKILL.md").is_file()
    assert not (tmp_path / ".claude").exists()


def test_stubs_are_written_with_lf_line_endings(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    sync_stubs(project, load_catalog(project.skills_folder, project.agents_folder), check_only=False)

    assert b"\r\n" not in (tmp_path / ".claude/skills/plan-work/SKILL.md").read_bytes()


def test_the_stub_of_a_protected_skill_is_kept(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    sync_stubs(project, load_catalog(project.skills_folder, project.agents_folder), check_only=False)
    (project.skills_folder / "plan-work" / "skill.yaml").write_text("schema: pskill/v1\nblocks: [\n", encoding="utf-8")

    changes = sync_stubs(
        project,
        load_catalog(project.skills_folder, project.agents_folder),
        check_only=False,
        protected_names={"plan-work"},
    )

    assert changes == []
    assert (tmp_path / ".claude/skills/plan-work/SKILL.md").is_file()


MANUAL_SKILL = PLAN_SKILL.replace("goal:", "invocation: manual\ngoal:")


def test_a_manual_skill_gets_the_codex_sidecar_that_forbids_implicit_use(tmp_path: Path) -> None:
    project = make_project(tmp_path, MANUAL_SKILL)

    sync_stubs(project, load_catalog(project.skills_folder, project.agents_folder), check_only=False)

    sidecar = tmp_path / ".agents/skills/plan-work/agents/openai.yaml"
    assert "allow_implicit_invocation: false" in sidecar.read_text(encoding="utf-8")
    assert not (tmp_path / ".agents/skills/pskill/agents/openai.yaml").exists()


def test_the_sidecar_goes_away_when_the_skill_is_no_longer_manual(tmp_path: Path) -> None:
    project = make_project(tmp_path, MANUAL_SKILL)
    sync_stubs(project, load_catalog(project.skills_folder, project.agents_folder), check_only=False)
    make_project(tmp_path)

    sync_stubs(project, load_catalog(project.skills_folder, project.agents_folder), check_only=False)

    assert not (tmp_path / ".agents/skills/plan-work/agents/openai.yaml").exists()
    assert (tmp_path / ".agents/skills/plan-work/SKILL.md").is_file()


def test_deleting_a_manual_skill_removes_its_whole_stub_folder(tmp_path: Path) -> None:
    project = make_project(tmp_path, MANUAL_SKILL)
    sync_stubs(project, load_catalog(project.skills_folder, project.agents_folder), check_only=False)
    (project.skills_folder / "plan-work" / "skill.yaml").unlink()

    sync_stubs(project, load_catalog(project.skills_folder, project.agents_folder), check_only=False)

    assert not (tmp_path / ".agents/skills/plan-work").exists()
