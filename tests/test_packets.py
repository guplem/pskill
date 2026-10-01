"""Tests for pskill_runner.packets."""

from dataclasses import replace

from pskill_runner.field_types import parse_field_map
from pskill_runner.packets import (
    AgentPacket,
    TaskPrompt,
    render_agent_packet,
    render_final_packet,
    render_parallel_packet,
    render_pause_packet,
)

PLAN_PACKET = AgentPacket(
    run_id="r-20260927-1432-ab12",
    chain=["plan-work"],
    block_id="create_plan",
    visit=2,
    mode="interactive",
    goal="Produce a plan that the user approved.",
    instruction="Write a plan for the login page.",
    return_fields=parse_field_map(
        {
            "status": {"type": "string", "enum": ["finished", "question"], "description": "finished when done."},
            "plan": {"type": "string", "description": "The plan so far."},
            "question": {"type": "string", "optional": True, "description": "The open question."},
        }
    ),
    choices=None,
    decider=None,
    errors=[],
    runner_command="uv run .pskill/pskill.py",
    shell="bash",
    question_wording="Ask the user in chat, then wait for the answer.",
)

DECISION_PACKET = replace(
    PLAN_PACKET,
    block_id="approve_plan",
    visit=1,
    instruction="Show the plan.",
    return_fields=parse_field_map(
        {
            "choice": {"type": "string", "enum": ["approve", "stop"], "description": "The choice."},
            "rationale": {"type": "string", "description": "Why."},
        }
    ),
    choices={"approve": "Accept the plan.", "stop": "Stop without a plan."},
    decider="human",
)


def test_a_step_shows_only_the_header_the_instruction_and_the_return() -> None:
    text = render_agent_packet(PLAN_PACKET)

    assert text.startswith("## pskill · plan-work · create_plan (visit 2)\nRun r-20260927-1432-ab12 · interactive\n")
    assert "### Instruction\nWrite a plan for the login page.\n" in text
    assert "### Return" in text
    assert "### Goal" not in text
    assert "### Rules" not in text
    assert "### Errors" not in text


def test_a_packet_can_show_the_goal() -> None:
    text = render_agent_packet(replace(PLAN_PACKET, show_goal=True))

    assert "### Goal\nProduce a plan that the user approved.\n" in text
    assert "### Rules" not in text


def test_the_return_section_is_one_submit_command_with_an_annotated_example() -> None:
    text = render_agent_packet(PLAN_PACKET)

    assert "uv run .pskill/pskill.py submit r-20260927-1432-ab12 <<'PSKILL'\n" in text
    assert "status: finished  # required, finished | question: finished when done.\n" in text
    assert "plan: ...  # required, text: The plan so far.\n" in text
    assert "question: ...  # optional, text: The open question.\n" in text
    assert "\nPSKILL\n" in text


def test_the_rules_name_the_escape_and_the_pause_command() -> None:
    text = render_agent_packet(replace(PLAN_PACKET, show_rules=True))

    assert "- Do only this block. The runner gives you the next one." in text
    assert "`$cannot_complete: <reason>`" in text
    assert "uv run .pskill/pskill.py pause r-20260927-1432-ab12" in text


def test_errors_appear_on_a_retry() -> None:
    text = render_agent_packet(replace(PLAN_PACKET, errors=["'plan' is a required field"]))

    assert "### Errors\nYour last answer was rejected. Fix these problems and submit again:\n" in text
    assert "- 'plan' is a required field\n" in text


def test_a_human_decision_in_interactive_mode_asks_the_user() -> None:
    text = render_agent_packet(DECISION_PACKET)

    assert "- approve: Accept the plan.\n- stop: Stop without a plan.\n" in text
    assert "Ask the user in chat, then wait for the answer." in text
    assert "Do not decide for the user." in text
    assert "$answered_by: human\n" in text


def test_a_human_decision_in_autonomous_mode_is_taken_by_the_agent() -> None:
    text = render_agent_packet(replace(DECISION_PACKET, mode="autonomous"))

    assert "This run is autonomous. Decide as the user would" in text
    assert "$answered_by" not in text


def test_the_parent_chain_appears_in_the_header() -> None:
    text = render_agent_packet(replace(PLAN_PACKET, chain=["implement-issue", "review-pr"]))

    assert text.startswith("## pskill · implement-issue > review-pr · create_plan (visit 2)")


def test_the_powershell_form_is_used_for_powershell() -> None:
    text = render_agent_packet(replace(PLAN_PACKET, shell="powershell"))

    assert "'@ | uv run .pskill/pskill.py submit r-20260927-1432-ab12" in text


def test_the_final_packet_reports_the_status_outputs_and_report() -> None:
    text = render_final_packet("r-1", "plan-work", "succeeded", "Tell the user the plan is approved.", {"result": "ok"})

    assert "Run r-1 finished with status succeeded." in text
    assert "Tell the user the plan is approved." in text
    assert "result: ok" in text
    assert "The run is finished. No more pskill commands are needed." in text


def test_the_pause_packet_explains_the_reason_and_the_next_commands() -> None:
    text = render_pause_packet("r-1", "plan-work", "create_plan", "block_failed", "plan: required", "uv run pskill.py")

    assert "Run r-1 is paused at block create_plan (block_failed)." in text
    assert "plan: required" in text
    assert "uv run pskill.py resume r-1" in text
    assert "uv run pskill.py cancel r-1" in text


def test_lists_of_groups_get_a_nested_example() -> None:
    fields = parse_field_map(
        {
            "angles": {
                "type": "array",
                "description": "One entry per subagent.",
                "items": {
                    "type": "object",
                    "properties": {
                        "focus": {"type": "string", "enum": ["security", "tests"]},
                        "brief": {"type": "string"},
                    },
                },
            }
        }
    )

    text = render_agent_packet(replace(PLAN_PACKET, return_fields=fields))

    assert "angles:  # required, list: One entry per subagent.\n  - focus: security\n    brief: ...\n" in text


def test_a_task_packet_submits_with_its_task_number() -> None:
    text = render_agent_packet(replace(PLAN_PACKET, task_index=3))

    assert "uv run .pskill/pskill.py submit r-20260927-1432-ab12 --task 3 <<'PSKILL'" in text


def test_the_parallel_packet_lists_one_full_prompt_per_task() -> None:
    fields = parse_field_map({"wrong": {"type": "array", "items": {"type": "string"}, "description": "Wrong claims."}})
    tasks = [
        TaskPrompt(index=0, agent_text="You check facts.", instruction="Check a.md.", return_fields=fields),
        TaskPrompt(index=2, agent_text=None, instruction="Check c.md.", return_fields=fields),
    ]

    text = render_parallel_packet(PLAN_PACKET, tasks, total_tasks=3)

    assert text.startswith("## pskill · plan-work · create_plan (visit 2)")
    assert (
        "Spawn one subagent per task below, all at once, each with a fresh context (none of this conversation)." in text
    )
    assert "2 of 3 tasks are still open." in text
    assert "#### Task 0\n" in text and "#### Task 2\n" in text and "#### Task 1\n" not in text
    assert "You check facts.\n" in text
    assert "Goal: Produce a plan that the user approved." in text
    assert "submit r-20260927-1432-ab12 --task 2 <<'PSKILL'" in text
    assert "uv run .pskill/pskill.py current r-20260927-1432-ab12" in text


def test_the_parallel_packet_names_the_harness_spawn_tool() -> None:
    fields = parse_field_map({"wrong": {"type": "string", "description": "Wrong claims."}})
    task = TaskPrompt(index=0, agent_text=None, instruction="Check a.md.", return_fields=fields)
    packet = replace(PLAN_PACKET, subagent_wording="Use the Agent tool, one call per task.")

    assert "Use the Agent tool, one call per task." in render_parallel_packet(packet, [task], total_tasks=1)


def test_a_named_task_shows_its_name_in_its_heading() -> None:
    fields = parse_field_map({"wrong": {"type": "string", "description": "Wrong claims."}})
    tasks = [TaskPrompt(index=0, agent_text=None, instruction="Check a.md.", return_fields=fields, name="security")]

    text = render_parallel_packet(PLAN_PACKET, tasks, total_tasks=1)

    assert "#### Task 0 · security\nYou are a subagent of a pskill run." in text
