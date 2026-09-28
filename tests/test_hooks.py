"""Tests for pskill_runner.hooks: the Stop and session-start hook logic, independent of any harness."""

from pathlib import Path

from pskill_runner.engine import pause_run, read_run_info, start_run, submit_answer
from pskill_runner.hooks import session_start_text, stop_hook_reason
from pskill_runner.project import Project, find_project
from pskill_runner.skill_loader import load_catalog
from pskill_runner.stubs import sync_stubs
from tests.skill_files import PLAN_SKILL, PLAN_SKILL_FILES, write_skill


def make_project(tmp_path: Path) -> Project:
    write_skill(tmp_path / ".pskill" / "skills", "plan-work", PLAN_SKILL, PLAN_SKILL_FILES)
    return find_project(tmp_path)


def start(project: Project, harness: str = "claude-code") -> str:
    run_id, _ = start_run(project, "plan-work", {"topic": "x"}, mode="interactive", harness=harness)
    return run_id


def test_the_stop_is_allowed_when_no_run_is_active(tmp_path: Path) -> None:
    assert stop_hook_reason(make_project(tmp_path), "claude-code") is None


def test_the_stop_is_blocked_while_a_block_is_open(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)

    reason = stop_hook_reason(project, "claude-code")

    assert reason is not None
    assert f"pskill run {run_id} has an open block" in reason
    assert f"current {run_id}" in reason
    assert read_run_info(project, run_id)["stop_blocks"] == 1


def test_after_three_blocks_in_a_row_the_stop_is_allowed_and_the_run_pauses(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)

    reasons = [stop_hook_reason(project, "claude-code") for _ in range(4)]

    assert [reason is not None for reason in reasons] == [True, True, True, False]
    info = read_run_info(project, run_id)
    assert info["status"] == "paused"
    assert info["pause_reason"] == "agent_stopped"


def test_a_submission_resets_the_block_count(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)
    stop_hook_reason(project, "claude-code")
    stop_hook_reason(project, "claude-code")

    submit_answer(project, run_id, "status: question\nplan: Draft.\nquestion: Why?\n")

    assert read_run_info(project, run_id)["stop_blocks"] == 0


def test_the_stop_is_allowed_while_the_run_waits_for_the_human(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)
    submit_answer(project, run_id, "status: question\nplan: Draft.\nquestion: Why?\n")

    assert read_run_info(project, run_id)["status"] == "waiting_for_human"
    assert stop_hook_reason(project, "claude-code") is None


def test_a_paused_run_or_a_run_of_another_harness_does_not_block(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    paused_run = start(project)
    pause_run(project, paused_run)
    start(project, harness="generic")

    assert stop_hook_reason(project, "claude-code") is None


def test_session_start_refreshes_stale_stubs_and_lists_open_runs(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)

    text = session_start_text(project)

    assert "pskill: updated 4 stubs (plan-work, pskill)." in text
    assert (tmp_path / ".claude" / "skills" / "plan-work" / "SKILL.md").is_file()
    assert f"- {run_id}  plan-work  create_plan  active" in text
    assert f"current {run_id}" in text


def test_session_start_is_silent_when_nothing_needs_attention(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    sync_stubs(project, load_catalog(project.skills_folder, project.agents_folder), check_only=False)

    assert session_start_text(project) == ""


def test_session_start_lists_only_the_three_newest_open_runs(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_ids = [start(project) for _ in range(4)]

    text = session_start_text(project)

    assert sum(run_id in text for run_id in run_ids) == 3
    assert "runs --open" in text


def test_session_start_warns_about_a_skill_that_does_not_load(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    broken = project.skills_folder / "broken"
    broken.mkdir()
    (broken / "skill.yaml").write_text("schema: pskill/v1\nblocks: [\n", encoding="utf-8")

    text = session_start_text(project)

    assert "pskill: the skill 'broken' does not load" in text
    assert (tmp_path / ".claude" / "skills" / "plan-work" / "SKILL.md").is_file()
