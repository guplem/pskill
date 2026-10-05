"""The release plan: on a merge to main, decide whether the runner version needs a release (SPEC.md M6).

Run it with: uv run python -m pskill_runner.release_plan <notes-file> <tag> <tag> ...
It prints the tag to create, and writes the version's CHANGELOG.md section to <notes-file> as the release notes.
It prints nothing when the version already has its tag. It stops with the reason when the version goes
backwards or has no CHANGELOG.md section.
"""

import re
import sys
from pathlib import Path

from pskill_runner import __version__
from pskill_runner.release import ReleaseError

VERSION_NUMBERS = re.compile(r"(\d+)\.(\d+)\.(\d+)")
SECTION_HEADING = re.compile(r"^## ", re.MULTILINE)


def version_numbers(version: str) -> tuple[int, int, int] | None:
    """(major, minor, patch) for a version like 0.24.2, or None when it is not three numbers."""
    match = VERSION_NUMBERS.fullmatch(version)
    if match is None:
        return None
    return int(match[1]), int(match[2]), int(match[3])


def changelog_section(changelog: str, version: str) -> str:
    """The text under the version's heading in CHANGELOG.md, up to the next version's heading."""
    heading = re.search(rf"^## {re.escape(version)}(?: .*)?$", changelog, re.MULTILINE)
    section = ""
    if heading is not None:
        next_heading = SECTION_HEADING.search(changelog, heading.end())
        section = changelog[heading.end() : next_heading.start() if next_heading else len(changelog)].strip()
    if not section:
        raise ReleaseError(f"CHANGELOG.md has no section for {version}. Add one before the release.")
    return section


def plan_release(version: str, tags: list[str], changelog: str) -> str | None:
    """The tag to create for the version, or None when it already has its tag."""
    tag = f"v{version}"
    if tag in tags:
        return None
    numbers = version_numbers(version)
    if numbers is None:
        raise ReleaseError(f"The version {version} is not three numbers, like 0.24.2.")
    released = [(tag_numbers, name) for name in tags if (tag_numbers := version_numbers(name.removeprefix("v")))]
    if released and numbers < max(released)[0]:
        raise ReleaseError(f"The version {version} is not above the newest release {max(released)[1]}.")
    changelog_section(changelog, version)
    return tag


def write_release_plan(source_root: Path, version: str, notes_path: Path, tags: list[str]) -> str:
    """The tag to create, with the release notes written to notes_path; "" when the version has its tag."""
    changelog = (source_root / "CHANGELOG.md").read_text(encoding="utf-8")
    tag = plan_release(version, tags, changelog)
    if tag is None:
        return ""
    notes_path.parent.mkdir(parents=True, exist_ok=True)
    notes_path.write_text(changelog_section(changelog, version) + "\n", encoding="utf-8")
    return tag


if __name__ == "__main__":
    try:
        print(write_release_plan(Path.cwd(), __version__, Path(sys.argv[1]), sys.argv[2:]))
    except ReleaseError as error:
        sys.exit(str(error))
