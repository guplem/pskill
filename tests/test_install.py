"""Tests for pskill_runner.install: `pskill init` and `pskill update` with a pinned entry script (SPEC.md D20)."""

import hashlib
from pathlib import Path

import pytest

from pskill_runner import __version__
from pskill_runner.install import (
    CACHE_VARIABLE,
    DEV_PIN,
    LEGACY_PATHS,
    InstallError,
    Pin,
    cache_folder,
    cache_root,
    init_project,
    pin_entry_script,
    pin_url,
    read_pin,
    update_project,
)
from pskill_runner.release import DEFAULT_RELEASE_URL, build_release_archive

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = (REPOSITORY_ROOT / "pskill.py").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cache = tmp_path / "cache"
    monkeypatch.setenv(CACHE_VARIABLE, str(cache))
    return cache


@pytest.fixture
def archive(tmp_path: Path) -> Path:
    return build_release_archive(REPOSITORY_ROOT, tmp_path / "release" / "pskill.zip")


def make_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "project"
    project_root.mkdir()
    return project_root


def files_under(folder: Path) -> list[str]:
    return sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*"))


# --- the pin ------------------------------------------------------------------------------------


def test_the_template_has_no_pin() -> None:
    assert read_pin(TEMPLATE) == Pin(version="", url="", sha256="")


def test_a_pin_changes_only_the_three_pin_lines() -> None:
    pin = Pin(version="1.2.3", url="https://example.com/pskill.zip", sha256="ab" * 32)

    text = pin_entry_script(TEMPLATE, pin)

    assert read_pin(text) == pin
    assert len(text.splitlines()) == len(TEMPLATE.splitlines())
    changed = [line for line, before in zip(text.splitlines(), TEMPLATE.splitlines(), strict=True) if line != before]
    assert changed == [
        'PSKILL_VERSION = "1.2.3"',
        'PSKILL_URL = "https://example.com/pskill.zip"',
        f'PSKILL_SHA256 = "{"ab" * 32}"',
    ]


def test_a_script_without_the_pin_lines_is_not_an_entry_script() -> None:
    with pytest.raises(InstallError, match="pin"):
        read_pin("print('hello')\n")


def test_the_latest_release_is_pinned_by_its_versioned_url(tmp_path: Path) -> None:
    assert (
        pin_url(DEFAULT_RELEASE_URL, "1.2.3") == "https://github.com/guplem/pskill/releases/download/v1.2.3/pskill.zip"
    )
    assert pin_url("https://mirror.example.com/pskill.zip", "1.2.3") == "https://mirror.example.com/pskill.zip"
    local_zip = tmp_path / "pskill.zip"
    assert pin_url(str(local_zip), "1.2.3") == local_zip.resolve().as_uri()


# --- the cache ----------------------------------------------------------------------------------


def test_the_cache_root_follows_the_variable_then_the_os(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    assert cache_root() == tmp_path / "cache"
    assert cache_root({"LOCALAPPDATA": str(tmp_path / "local")}, os_name="nt") == tmp_path / "local" / "pskill"
    assert cache_root({}, os_name="nt") == tmp_path / "home" / "AppData" / "Local" / "pskill"
    assert cache_root({"XDG_CACHE_HOME": str(tmp_path / "xdg")}, os_name="posix") == tmp_path / "xdg" / "pskill"
    assert cache_root({}, os_name="posix") == tmp_path / "home" / ".cache" / "pskill"


def test_each_release_gets_its_own_cache_folder() -> None:
    pin = Pin(version="1.2.3", url="https://example.com/pskill.zip", sha256="ab" * 32)

    assert cache_folder(pin, Path("cache")) == Path("cache") / f"1.2.3-{'ab' * 6}"


def test_the_entry_script_and_the_installer_name_the_same_cache() -> None:
    assert f'CACHE_VARIABLE = "{CACHE_VARIABLE}"' in TEMPLATE
    assert 'f"{PSKILL_VERSION}-{PSKILL_SHA256[:12]}"' in TEMPLATE


# --- init ---------------------------------------------------------------------------------------


def test_init_creates_only_the_files_that_a_project_needs(tmp_path: Path, archive: Path) -> None:
    project_root = make_project(tmp_path)

    lines = init_project(project_root, str(archive))

    assert files_under(project_root) == [
        ".pskill",
        ".pskill/.gitignore",
        ".pskill/config.yaml",
        ".pskill/pskill.py",
        ".pskill/skills",
    ]
    assert (project_root / ".pskill" / ".gitignore").read_text(encoding="utf-8") == "runs/\n__pycache__/\n"
    pin = read_pin((project_root / ".pskill" / "pskill.py").read_text(encoding="utf-8"))
    assert pin == Pin(__version__, archive.resolve().as_uri(), hashlib.sha256(archive.read_bytes()).hexdigest())
    assert lines[0] == f"Installed pskill {__version__} in .pskill/pskill.py."


def test_init_puts_the_release_in_the_cache_so_the_first_run_needs_no_download(
    tmp_path: Path, archive: Path, isolated_cache: Path
) -> None:
    project_root = make_project(tmp_path)

    init_project(project_root, str(archive))

    pin = read_pin((project_root / ".pskill" / "pskill.py").read_text(encoding="utf-8"))
    assert (cache_folder(pin, isolated_cache) / "pskill_runner" / "cli.py").is_file()


def test_a_second_project_reuses_the_cached_release(tmp_path: Path, archive: Path, isolated_cache: Path) -> None:
    init_project(make_project(tmp_path), str(archive))
    second_project = tmp_path / "second"
    second_project.mkdir()

    init_project(second_project, str(archive))

    assert len(list(isolated_cache.iterdir())) == 1


def test_init_refuses_a_project_that_already_has_the_runner(tmp_path: Path, archive: Path) -> None:
    project_root = make_project(tmp_path)
    init_project(project_root, str(archive))

    with pytest.raises(InstallError, match="pskill update"):
        init_project(project_root, str(archive))


def test_init_keeps_an_existing_config_file(tmp_path: Path, archive: Path) -> None:
    project_root = make_project(tmp_path)
    (project_root / ".pskill").mkdir()
    (project_root / ".pskill" / "config.yaml").write_text("default_mode: autonomous\n", encoding="utf-8")

    init_project(project_root, str(archive))

    assert (project_root / ".pskill" / "config.yaml").read_text(encoding="utf-8") == "default_mode: autonomous\n"


def test_a_source_that_is_not_a_release_is_refused(tmp_path: Path) -> None:
    not_a_release = tmp_path / "notes.zip"
    not_a_release.write_bytes(b"not a zip file")

    with pytest.raises(InstallError, match="not a pskill release"):
        init_project(make_project(tmp_path), str(not_a_release))


# --- update -------------------------------------------------------------------------------------


def test_update_moves_the_pin_and_keeps_the_project_files(tmp_path: Path, archive: Path) -> None:
    project_root = make_project(tmp_path)
    pskill_folder = project_root / ".pskill"
    pskill_folder.mkdir()
    (pskill_folder / "pskill.py").write_text(
        pin_entry_script(TEMPLATE, Pin("0.1.0", "https://example.com/old.zip", "cd" * 32)), encoding="utf-8"
    )
    (pskill_folder / "skills" / "mine").mkdir(parents=True)
    (pskill_folder / "skills" / "mine" / "skill.yaml").write_text("id: mine\n", encoding="utf-8")
    (pskill_folder / "config.yaml").write_text("default_mode: autonomous\n", encoding="utf-8")

    lines = update_project(project_root, str(archive))

    assert read_pin((pskill_folder / "pskill.py").read_text(encoding="utf-8")).version == __version__
    assert (pskill_folder / "skills" / "mine" / "skill.yaml").read_text(encoding="utf-8") == "id: mine\n"
    assert (pskill_folder / "config.yaml").read_text(encoding="utf-8") == "default_mode: autonomous\n"
    assert lines == [f"Updated pskill from 0.1.0 to {__version__}."]


def test_update_removes_the_runner_files_of_a_vendored_project(tmp_path: Path, archive: Path) -> None:
    project_root = make_project(tmp_path)
    pskill_folder = project_root / ".pskill"
    for relative_path in ("pskill_runner/engine.py", "viewer/app.js", "launchers/view.sh", "AUTHORING.md"):
        (pskill_folder / relative_path).parent.mkdir(parents=True, exist_ok=True)
        (pskill_folder / relative_path).write_text("old\n", encoding="utf-8")
    (pskill_folder / "pskill_runner" / "__pycache__").mkdir()
    (pskill_folder / "VENDORED").write_text('{"version": "0.21.0"}\n', encoding="utf-8")
    (pskill_folder / "pskill.py").write_text("# the entry script of 0.21, with no pin lines\n", encoding="utf-8")
    (pskill_folder / "skills").mkdir()

    lines = update_project(project_root, str(archive))

    assert sorted(path.name for path in pskill_folder.iterdir()) == ["pskill.py", "skills"]
    assert set(LEGACY_PATHS) == {"pskill_runner", "viewer", "launchers", "AUTHORING.md", "VENDORED"}
    assert lines == [
        f"Updated pskill from 0.21.0 to {__version__}.",
        "Removed the old runner files: AUTHORING.md, VENDORED, launchers/, pskill_runner/, viewer/.",
    ]


def test_update_removes_only_the_old_runner_files_that_are_there(tmp_path: Path, archive: Path) -> None:
    project_root = make_project(tmp_path)
    pskill_folder = project_root / ".pskill"
    pskill_folder.mkdir()
    (pskill_folder / "VENDORED").write_text("{}\n", encoding="utf-8")
    (pskill_folder / "pskill.py").write_text(TEMPLATE, encoding="utf-8")

    lines = update_project(project_root, str(archive))

    assert lines == [f"Updated pskill from (no pin) to {__version__}.", "Removed the old runner files: VENDORED."]


def test_a_release_that_another_process_cached_first_is_kept(
    tmp_path: Path, archive: Path, isolated_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def lose_the_race(staging: Path, target: Path) -> Path:
        (Path(target) / "pskill_runner").mkdir(parents=True)  # the other process finished first
        raise OSError("the target exists")

    monkeypatch.setattr(Path, "rename", lose_the_race)

    init_project(make_project(tmp_path), str(archive))

    [folder] = list(isolated_cache.iterdir())
    assert (folder / "pskill_runner").is_dir()


def test_update_needs_an_installed_project(tmp_path: Path, archive: Path) -> None:
    with pytest.raises(InstallError, match="pskill init"):
        update_project(make_project(tmp_path), str(archive))


def test_update_from_the_checkout_itself_pins_the_dev_runner(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    (checkout / "pskill_runner").mkdir(parents=True)
    (checkout / "pskill.py").write_text(TEMPLATE, encoding="utf-8")
    (checkout / ".pskill").mkdir()
    (checkout / ".pskill" / "pskill.py").write_text(TEMPLATE, encoding="utf-8")

    lines = update_project(checkout, str(checkout))

    assert (checkout / ".pskill" / "pskill.py").read_text(encoding="utf-8") == pin_entry_script(TEMPLATE, DEV_PIN)
    assert lines == ["Updated pskill from (no pin) to dev."]


def test_a_folder_source_must_be_the_pskill_checkout_itself(tmp_path: Path) -> None:
    project_root = make_project(tmp_path)
    (project_root / ".pskill").mkdir()
    (project_root / ".pskill" / "pskill.py").write_text(TEMPLATE, encoding="utf-8")

    with pytest.raises(InstallError, match="only for the pskill repository"):
        update_project(project_root, str(tmp_path))


def test_this_repository_runs_its_own_checkout() -> None:
    entry_script = (REPOSITORY_ROOT / ".pskill" / "pskill.py").read_text(encoding="utf-8")

    assert entry_script == pin_entry_script(TEMPLATE, DEV_PIN), "run `uv run pskill.py update --from .`"
    assert not (REPOSITORY_ROOT / ".pskill" / "pskill_runner").exists()
