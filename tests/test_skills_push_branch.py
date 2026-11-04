"""Every example step that pushes names the branch, and checks that its commit reached the remote.

A checkout can be detached (another worktree holds the branch), where a bare `git push` fails. And a cloud session
starts on its own `claude/` branch, so the step says which branch to push to.
"""

from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parent.parent / ".pskill" / "skills"
PUSHING_STEPS = [
    ("implement-issue/instructions/implement_step.md", "{{ steps.checkout_base.json.branch }}"),
    ("fix-ci/instructions/fix_ci.md", "{{ steps.checkout.outputs.branch }}"),
    ("resolve-pr-feedback/instructions/resolve_items.md", "{{ steps.checkout.outputs.branch }}"),
]
BRANCH_RULE = "Push to this branch, not to the session's `claude/` branch."


@pytest.mark.parametrize(("path", "branch"), PUSHING_STEPS)
def test_a_pushing_step_names_the_branch_and_checks_the_remote(path: str, branch: str) -> None:
    text = (SKILLS / path).read_text(encoding="utf-8")
    assert f"`git push origin HEAD:{branch}`" in text
    assert BRANCH_RULE in text
    assert f"`git branch -r --contains <hash>` lists `origin/{branch}`" in text
