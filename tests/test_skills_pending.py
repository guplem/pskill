"""Every end of an example skill that a user starts says what is left (SPEC.md section 13.2)."""

import pytest

from pskill_runner.skill_loader import load_skill
from pskill_runner.skill_model import EndBlock
from tests.skill_scripts import SKILLS_FOLDER

STARTED_BY_USERS = [
    folder.name
    for folder in sorted(SKILLS_FOLDER.iterdir())
    if (folder / "skill.yaml").is_file() and load_skill(folder).invocation != "internal"
]


@pytest.mark.parametrize("skill_id", STARTED_BY_USERS)
def test_every_end_of_a_skill_that_users_start_has_a_pending_text(skill_id: str) -> None:
    skill = load_skill(SKILLS_FOLDER / skill_id)

    missing = [block.id for block in skill.blocks.values() if isinstance(block, EndBlock) and block.pending is None]

    assert missing == []


def test_the_skills_that_users_start_are_found() -> None:
    assert {"create-issue", "fix-ci", "implement-issue", "resolve-pr-feedback", "review-pr"} <= set(STARTED_BY_USERS)
