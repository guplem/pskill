"""Tests for the release plan: a merge to main that raises the version publishes a release (SPEC.md milestone M6)."""

import runpy
import sys
from pathlib import Path

import pytest

from pskill_runner import __version__
from pskill_runner.release import ReleaseError
from pskill_runner.release_plan import changelog_section, plan_release, write_release_plan

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
RELEASE_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"
CHANGELOG = """# Changelog

## 0.3.0 (2026-10-05)

New things.

- **A:** one.

## 0.2.0 (2026-10-04)

Old things.
"""


def test_a_version_above_the_newest_tag_gets_its_tag() -> None:
    assert plan_release("0.3.0", ["v0.1.0", "v0.2.0"], CHANGELOG) == "v0.3.0"


def test_a_version_that_has_its_tag_needs_no_release() -> None:
    assert plan_release("0.3.0", ["v0.2.0", "v0.3.0"], CHANGELOG) is None


def test_the_first_release_needs_no_older_tag() -> None:
    assert plan_release("0.3.0", [], CHANGELOG) == "v0.3.0"


def test_versions_compare_as_numbers_not_as_text() -> None:
    changelog = "## 0.10.0 (2026-10-05)\n\nTen.\n"

    assert plan_release("0.10.0", ["v0.9.0"], changelog) == "v0.10.0"


def test_a_version_below_the_newest_tag_fails() -> None:
    with pytest.raises(ReleaseError, match=r"0\.3\.0 is not above the newest release v0\.4\.0"):
        plan_release("0.3.0", ["v0.2.0", "v0.4.0"], CHANGELOG)


def test_tags_that_are_not_versions_are_ignored() -> None:
    assert plan_release("0.3.0", ["v0.2.0", "v9.0.0-rc1", "latest"], CHANGELOG) == "v0.3.0"


def test_a_version_that_is_not_three_numbers_fails() -> None:
    with pytest.raises(ReleaseError, match="not three numbers"):
        plan_release("0.3", ["v0.2.0"], CHANGELOG)


def test_a_version_without_a_changelog_section_fails() -> None:
    with pytest.raises(ReleaseError, match=r"CHANGELOG\.md has no section for 0\.4\.0"):
        plan_release("0.4.0", ["v0.3.0"], CHANGELOG)


def test_the_section_is_the_text_under_the_heading_up_to_the_next_version() -> None:
    assert changelog_section(CHANGELOG, "0.3.0") == "New things.\n\n- **A:** one."
    assert changelog_section(CHANGELOG, "0.2.0") == "Old things."


def test_an_empty_section_fails() -> None:
    with pytest.raises(ReleaseError, match=r"no section for 0\.5\.0"):
        changelog_section("## 0.5.0 (2026-10-06)\n\n## 0.4.0\n\nText.\n", "0.5.0")


def test_the_plan_writes_the_section_as_the_release_notes(tmp_path: Path) -> None:
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")

    tag = write_release_plan(tmp_path, "0.3.0", tmp_path / "dist" / "notes.md", ["v0.2.0"])

    assert tag == "v0.3.0"
    assert (tmp_path / "dist" / "notes.md").read_text(encoding="utf-8") == "New things.\n\n- **A:** one.\n"


def test_the_plan_writes_no_notes_when_the_version_has_its_tag(tmp_path: Path) -> None:
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")

    assert write_release_plan(tmp_path, "0.3.0", tmp_path / "notes.md", ["v0.3.0"]) == ""
    assert not (tmp_path / "notes.md").exists()


def test_the_current_version_has_its_changelog_section() -> None:
    changelog = (REPOSITORY_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert changelog_section(changelog, __version__)  # else the merge to main fails to release


# runpy warns that this test file has already imported the module. That is harmless here.
@pytest.mark.filterwarnings("ignore:'pskill_runner.release_plan' found in sys.modules:RuntimeWarning")
def test_running_the_module_prints_the_tag_to_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(REPOSITORY_ROOT)
    monkeypatch.setattr(sys, "argv", ["release_plan.py", str(tmp_path / "notes.md"), "v0.0.1"])

    runpy.run_module("pskill_runner.release_plan", run_name="__main__")

    assert capsys.readouterr().out.strip() == f"v{__version__}"
    assert (tmp_path / "notes.md").read_text(encoding="utf-8").strip()


@pytest.mark.filterwarnings("ignore:'pskill_runner.release_plan' found in sys.modules:RuntimeWarning")
def test_running_the_module_stops_with_the_reason_when_the_version_goes_backwards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPOSITORY_ROOT)
    monkeypatch.setattr(sys, "argv", ["release_plan.py", str(tmp_path / "notes.md"), "v999.0.0"])

    with pytest.raises(SystemExit, match=r"is not above the newest release v999\.0\.0"):
        runpy.run_module("pskill_runner.release_plan", run_name="__main__")


def test_a_merge_to_main_publishes_the_release_in_one_workflow() -> None:
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "branches: [main]" in workflow
    assert "tags:" not in workflow  # a tag that a workflow pushes starts no other workflow
    assert "group: release" in workflow  # two quick merges release one after the other
    assert "fetch-depth: 0" in workflow  # the plan needs every tag
    assert "python -m pskill_runner.release_plan" in workflow
    assert '--target "$GITHUB_SHA"' in workflow  # the tag goes on the merge commit
    assert "--notes-file" in workflow
