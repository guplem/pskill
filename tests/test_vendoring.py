"""Tests for pskill_runner.vendoring: `pskill init` and `pskill update`."""

import json
from pathlib import Path

import pytest

from pskill_runner import __version__
from pskill_runner.vendoring import VendoringError, init_project, update_project, vendored_file_map

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def make_source(tmp_path: Path) -> Path:
    """A minimal pskill source checkout: the entry script and the runner package."""
    source = tmp_path / "source"
    (source / "pskill_runner").mkdir(parents=True)
    (source / "pskill.py").write_text("# entry\n", encoding="utf-8")
    (source / "pskill_runner" / "__init__.py").write_text('__version__ = "9.9.9"\n', encoding="utf-8")
    (source / "pskill_runner" / "engine.py").write_text("# engine\n", encoding="utf-8")
    (source / "pskill_runner" / "__pycache__").mkdir()
    (source / "pskill_runner" / "__pycache__" / "engine.pyc").write_bytes(b"compiled")
    (source / "AUTHORING.md").write_text("How to write skills.\n", encoding="utf-8")
    return source


def test_the_file_map_lists_the_vendored_files_without_caches(tmp_path: Path) -> None:
    files = vendored_file_map(make_source(tmp_path))

    assert sorted(files) == ["AUTHORING.md", "pskill.py", "pskill_runner/__init__.py", "pskill_runner/engine.py"]


def test_init_copies_the_runner_and_records_its_hashes(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    project_root = tmp_path / "project"
    project_root.mkdir()

    init_project(project_root, source)

    pskill_folder = project_root / ".pskill"
    assert (pskill_folder / "pskill.py").read_text(encoding="utf-8") == "# entry\n"
    assert (pskill_folder / "pskill_runner" / "engine.py").is_file()
    assert not (pskill_folder / "pskill_runner" / "__pycache__").exists()
    assert (pskill_folder / "skills").is_dir()
    assert (pskill_folder / ".gitignore").read_text(encoding="utf-8") == "runs/\n"
    assert "stub_folders:" in (pskill_folder / "config.yaml").read_text(encoding="utf-8")
    assert ".pskill/** text eol=lf" in (project_root / ".gitattributes").read_text(encoding="utf-8")
    vendored = json.loads((pskill_folder / "VENDORED").read_text(encoding="utf-8"))
    assert vendored["version"] == "9.9.9"
    assert vendored["source"] == source.resolve().as_posix()
    assert vendored["files"]["pskill.py"].startswith("sha256:")


def test_init_refuses_a_project_that_already_has_the_runner(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    project_root = tmp_path / "project"
    project_root.mkdir()
    init_project(project_root, source)

    with pytest.raises(VendoringError, match="update"):
        init_project(project_root, source)


def test_init_keeps_an_existing_gitattributes_file(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".gitattributes").write_text("*.png binary\n", encoding="utf-8")

    init_project(project_root, make_source(tmp_path))

    assert (project_root / ".gitattributes").read_text(encoding="utf-8") == "*.png binary\n.pskill/** text eol=lf\n"


def test_update_replaces_the_vendored_files_and_keeps_the_project_files(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    project_root = tmp_path / "project"
    project_root.mkdir()
    init_project(project_root, source)
    skill_file = project_root / ".pskill" / "skills" / "mine" / "skill.yaml"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text("mine\n", encoding="utf-8")
    (project_root / ".pskill" / "config.yaml").write_text("retries: 5\n", encoding="utf-8")
    (source / "pskill_runner" / "engine.py").write_text("# engine v2\n", encoding="utf-8")
    (source / "pskill_runner" / "packets.py").write_text("# new module\n", encoding="utf-8")
    (source / "AUTHORING.md").unlink()

    update_project(project_root, source, force=False)

    pskill_folder = project_root / ".pskill"
    assert (pskill_folder / "pskill_runner" / "engine.py").read_text(encoding="utf-8") == "# engine v2\n"
    assert (pskill_folder / "pskill_runner" / "packets.py").is_file()
    assert not (pskill_folder / "AUTHORING.md").exists()
    assert skill_file.read_text(encoding="utf-8") == "mine\n"
    assert (pskill_folder / "config.yaml").read_text(encoding="utf-8") == "retries: 5\n"


def test_update_stops_when_a_vendored_file_was_edited_by_hand(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    project_root = tmp_path / "project"
    project_root.mkdir()
    init_project(project_root, source)
    edited = project_root / ".pskill" / "pskill_runner" / "engine.py"
    edited.write_text("# my local change\n", encoding="utf-8")

    with pytest.raises(VendoringError, match=r"pskill_runner/engine\.py"):
        update_project(project_root, source, force=False)

    assert edited.read_text(encoding="utf-8") == "# my local change\n"
    update_project(project_root, source, force=True)
    assert edited.read_text(encoding="utf-8") == "# engine\n"


def test_a_vendored_copy_can_itself_be_the_source(tmp_path: Path) -> None:
    first_project = tmp_path / "first"
    first_project.mkdir()
    init_project(first_project, make_source(tmp_path))
    second_project = tmp_path / "second"
    second_project.mkdir()

    init_project(second_project, first_project / ".pskill")

    assert (second_project / ".pskill" / "pskill_runner" / "engine.py").is_file()


def test_this_repository_vendors_an_up_to_date_copy_of_its_own_runner() -> None:
    vendored_folder = REPOSITORY_ROOT / ".pskill"
    source_files = vendored_file_map(REPOSITORY_ROOT)

    for relative_path, source_path in source_files.items():
        vendored_path = vendored_folder / relative_path
        assert vendored_path.is_file(), f"{relative_path} is missing: run `uv run pskill.py update --from .`"
        assert vendored_path.read_bytes() == source_path.read_bytes(), (
            f"{relative_path} is out of date: run `uv run pskill.py update --from .`"
        )
    vendored = json.loads((vendored_folder / "VENDORED").read_text(encoding="utf-8"))
    assert vendored["version"] == __version__
    assert vendored["source"] == "."
