"""The example skill in AUTHORING.md must stay valid, because agents copy it."""

import re
from pathlib import Path

from pskill_runner.skill_loader import load_skill
from pskill_runner.validator import validate_skill
from tests.skill_files import write_skill

AUTHORING = Path(__file__).resolve().parent.parent / "AUTHORING.md"


def test_the_complete_example_in_authoring_md_is_a_valid_skill(tmp_path: Path) -> None:
    section = AUTHORING.read_text(encoding="utf-8").split("## A complete example", 1)[1]
    match = re.search(r"```yaml\n(?P<yaml>.*?)```", section, re.DOTALL)
    assert match is not None

    skill = load_skill(write_skill(tmp_path, "my-skill", match["yaml"]))

    assert [problem for problem in validate_skill(skill) if problem.level == "error"] == []
