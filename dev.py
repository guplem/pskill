"""The developer commands of this repository.

uv run dev.py check   every CI check, in the order of CI; it stops at the first failure
uv run dev.py fast    a quick pass before a commit: lint, the tests up to the first failure, and the skill tests
uv run dev.py sync    rewrite every copy of a shared file from its source, then the dev pin and the stubs
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKILLS = ".pskill/skills"

STEPS: dict[str, list[list[str]]] = {
    "check": [
        [sys.executable, "-m", "ruff", "format", "--check", "."],
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "mypy"],
        [sys.executable, "-m", "pytest", "--cov"],
        [sys.executable, "pskill.py", "validate"],
        [sys.executable, "pskill.py", "test"],
    ],
    "fast": [
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "pytest", "-x", "-q"],
        [sys.executable, "pskill.py", "test"],
    ],
}

# Each shared file, from its source to its copies. The parity tests in tests/ fail while a copy differs.
COPIES: dict[str, list[str]] = {
    f"{SKILLS}/implement-issue/scripts/github_rest.py": [
        f"{SKILLS}/{skill}/scripts/github_rest.py"
        for skill in ["checkout-pr", "create-issue", "fix-ci", "resolve-pr-feedback", "review-head-check", "review-pr"]
    ],
    f"{SKILLS}/implement-issue/scripts/publish_body.py": [f"{SKILLS}/resolve-pr-feedback/scripts/publish_body.py"],
    f"{SKILLS}/review-pr/references/finding-acceptance.md": [
        f"{SKILLS}/{skill}/references/finding-acceptance.md"
        for skill in ["review-round", "review-doubt", "resolve-pr-feedback"]
    ],
}

SYNC_STEPS = [
    [sys.executable, "pskill.py", "update", "--from", "."],
    [sys.executable, "pskill.py", "sync"],
]


def run_steps(steps: list[list[str]]) -> int:
    """Run each command in the repository root, and stop at the first one that fails. Returns its exit code."""
    for command in steps:
        print(f"$ {' '.join(command[1:])}", flush=True)
        code = subprocess.call(command, cwd=ROOT)
        if code != 0:
            return code
    return 0


def sync_copies(root: Path) -> list[str]:
    """Copy each source over its copies that differ, and return the copies that changed."""
    changed: list[str] = []
    for source, targets in COPIES.items():
        text = (root / source).read_bytes()
        for target in targets:
            if (root / target).read_bytes() != text:
                shutil.copyfile(root / source, root / target)
                changed.append(target)
    return changed


def main(arguments: list[str]) -> int:
    command = arguments[0] if arguments else ""
    if command in STEPS:
        return run_steps(STEPS[command])
    if command == "sync":
        for target in sync_copies(ROOT):
            print(f"updated {target}")
        return run_steps(SYNC_STEPS)
    print("usage: uv run dev.py check, fast, or sync", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover - the tests call main()
    sys.exit(main(sys.argv[1:]))
