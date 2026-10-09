"""Helpers that write skill folders for tests."""

import textwrap
from pathlib import Path


def write_skill(skills_folder: Path, skill_id: str, skill_yaml: str, files: dict[str, str] | None = None) -> Path:
    """Write `<skills_folder>/<skill_id>/skill.yaml` and any extra files. Return the skill folder."""
    folder = skills_folder / skill_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "skill.yaml").write_text(textwrap.dedent(skill_yaml), encoding="utf-8")
    for relative_path, content in (files or {}).items():
        path = folder / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
    return folder


PLAN_SKILL = """\
schema: pskill/v1
id: plan-work
description: Plan a piece of work with the user.
goal: Produce a plan that the user approved.
inputs:
  topic: {type: string, description: "What to plan."}
outputs:
  result: {type: string, enum: [approved, stopped], description: "How the skill ended."}
entry: create_plan
blocks:
  create_plan:
    type: task
    instruction: "Write a plan for {{ inputs.topic }}."
    max_visits: 3
    on_max_visits: stopped
    output:
      status: {type: string, enum: [finished, question], description: "finished when nothing is open."}
      plan: {type: string, description: "The plan so far."}
      question: {type: string, optional: true, description: "The open question."}
    next:
      - when: "{{ steps.create_plan.status == 'question' }}"
        to: ask_user
      - to: approve_plan
  ask_user:
    type: decision
    decider: human
    instruction: "Ask the user: {{ steps.create_plan.question }}"
    next: create_plan
  approve_plan:
    type: decision
    decider: human
    instruction: instructions/approve_plan.md
    choices:
      approve: Accept the plan.
      stop: Stop without a plan.
    next: {approve: done, stop: stopped}
  done:
    type: end
    status: succeeded
    outputs: {result: approved}
    report: "Tell the user the plan is approved."
  stopped:
    type: end
    status: cancelled
    outputs: {result: stopped}
"""

PLAN_SKILL_FILES = {"instructions/approve_plan.md": "Show the plan:\n\n{{ steps.create_plan.plan }}\n"}

# A per-item loop: each choice goes back for the next finding, or on once every finding has an answer.
PER_ITEM_SKILL = """\
schema: pskill/v1
id: per-item
description: Decide about each finding.
goal: Decide about every finding.
inputs:
  findings: {type: array, items: {type: string}, description: "The findings."}
outputs:
  fixed: {type: integer, description: "How many findings to fix."}
entry: ask_finding
blocks:
  ask_finding:
    type: decision
    decider: agent
    instruction: "Decide about the next finding."
    max_visits: 10
    on_max_visits: done
    choices:
      fix: Fix the finding.
      stop: Stop asking.
    next:
      fix:
        - when: "{{ (history.ask_finding | length) < (inputs.findings | length) }}"
          to: ask_finding
        - to: done
      stop: done
  done:
    type: end
    status: succeeded
    outputs: {fixed: "{{ history.ask_finding | selectattr('choice', 'equalto', 'fix') | list | length }}"}
"""
