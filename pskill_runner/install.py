"""`pskill init` and `pskill update` (SPEC.md D20).

A project commits only its entry script, `.pskill/pskill.py`. Its pin names one release of the
runner: the version, the URL of the release archive, and the archive's sha256. `init` writes the
entry script and the few project files; `update` moves the pin. Both put the release into the
user's cache, so the next run needs no download. Runner files of an older, vendored install
(pskill 0.21 and before) go away on `update`.
"""

import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pskill_runner.project import PSKILL_FOLDER_NAME
from pskill_runner.release import (
    DEFAULT_RELEASE_URL,
    VERSIONED_RELEASE_URL,
    ReleaseError,
    is_url,
    read_release,
    release_version,
    unpack_release,
)

# The entry script pskill.py repeats the variable name and the cache folder name; a test checks it.
CACHE_VARIABLE = "PSKILL_CACHE_DIR"
PIN_NAMES = ("PSKILL_VERSION", "PSKILL_URL", "PSKILL_SHA256")
# The runner files that a vendored install kept in `.pskill/`, before 0.22.
LEGACY_PATHS = ["AUTHORING.md", "VENDORED", "launchers", "pskill_runner", "viewer"]
PROJECT_GITIGNORE = "runs/\n__pycache__/\n"
DEFAULT_CONFIG = """\
# pskill settings (SPEC.md section 10.1). Every setting is optional; these are the defaults.
stub_folders: [.agents/skills, .claude/skills]          # where `pskill sync` writes the skill stubs
hook_files: [.claude/settings.json, .codex/hooks.json]  # where it writes the two hooks (or your own hooks source)
permissions: [claude-code, codex]                       # the apps that get the runner rule (and the profile agents)
"""


class InstallError(Exception):
    """The runner cannot be installed or updated."""


@dataclass(frozen=True)
class Pin:
    """The release that a project's entry script runs. An empty version means the latest release."""

    version: str
    url: str
    sha256: str


DEV_PIN = Pin(version="dev", url="", sha256="")


def pin_line_pattern(name: str) -> re.Pattern[str]:
    return re.compile(rf'^{name} = "(?P<value>[^"]*)"$', re.MULTILINE)


def read_pin(entry_script: str) -> Pin:
    values = []
    for name in PIN_NAMES:
        match = pin_line_pattern(name).search(entry_script)
        if match is None:
            raise InstallError(f"The entry script has no pin line `{name} = ...`.")
        values.append(match["value"])
    return Pin(*values)


def pin_entry_script(entry_script: str, pin: Pin) -> str:
    """The entry script with its three pin lines set to this pin."""
    for name, value in zip(PIN_NAMES, (pin.version, pin.url, pin.sha256), strict=True):
        entry_script = pin_line_pattern(name).sub(f'{name} = "{value}"', entry_script, count=1)
    return entry_script


def pin_url(source: str, version: str) -> str:
    """The URL that teammates download. The latest release becomes its versioned URL, which never changes."""
    if source == DEFAULT_RELEASE_URL:
        return VERSIONED_RELEASE_URL.format(version=version)
    return source if is_url(source) else Path(source).resolve().as_uri()


def cache_root(environment: Mapping[str, str] | None = None, os_name: str = os.name) -> Path:
    """Where the downloaded releases live: one folder per user, outside every project."""
    environment = os.environ if environment is None else environment
    if environment.get(CACHE_VARIABLE):
        return Path(environment[CACHE_VARIABLE])
    if os_name == "nt":
        return Path(environment.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "pskill"
    return Path(environment.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "pskill"


def cache_folder(pin: Pin, root: Path) -> Path:
    return root / f"{pin.version}-{pin.sha256[:12]}"


def init_project(project_root: Path, source: str) -> list[str]:
    """Create `.pskill/` with only what a project commits. Return one line per thing done."""
    pskill_folder = project_root / PSKILL_FOLDER_NAME
    if (pskill_folder / "pskill.py").exists():
        raise InstallError(f"{pskill_folder} already has the runner. Use `pskill update` instead.")
    pin, entry_script = install_release(source)
    (pskill_folder / "skills").mkdir(parents=True, exist_ok=True)
    write_if_missing(pskill_folder / ".gitignore", PROJECT_GITIGNORE)
    write_if_missing(pskill_folder / "config.yaml", DEFAULT_CONFIG)
    write_text(pskill_folder / "pskill.py", entry_script)
    return [
        f"Installed pskill {pin.version} in .pskill/pskill.py.",
        "Created .pskill/skills/, .pskill/config.yaml, and .pskill/.gitignore.",
    ]


def update_project(project_root: Path, source: str) -> list[str]:
    """Move the pin of `.pskill/pskill.py`. Never touch skills, agents, runs, or config.yaml."""
    pskill_folder = project_root / PSKILL_FOLDER_NAME
    entry_path = pskill_folder / "pskill.py"
    if not entry_path.is_file():
        raise InstallError(f"{entry_path} is missing. Run `pskill init` first.")
    old_version = installed_version(pskill_folder)
    if Path(source).is_dir():
        pin, entry_script = dev_release(project_root, Path(source))
    else:
        pin, entry_script = install_release(source)
    write_text(entry_path, entry_script)
    lines = [f"Updated pskill from {old_version} to {pin.version}."]
    removed = remove_legacy_files(pskill_folder)
    if removed:
        lines.append(f"Removed the old runner files: {', '.join(removed)}.")
    return lines


def install_release(source: str) -> tuple[Pin, str]:
    """Read a release, put it in the cache, and return its pin and its pinned entry script."""
    try:
        data = read_release(source)
        version = release_version(data)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            template = archive.read("pskill.py").decode("utf-8")
    except (OSError, KeyError, ReleaseError) as error:
        raise InstallError(f"{source} is not a pskill release that pskill can read: {error}") from error
    read_pin(template)  # a release before 0.22 has no pin lines, so it cannot be pinned
    pin = Pin(version=version, url=pin_url(source, version), sha256=hashlib.sha256(data).hexdigest())
    put_in_cache(pin, data)
    return pin, pin_entry_script(template, pin)


def dev_release(project_root: Path, source: Path) -> tuple[Pin, str]:
    """The pskill repository runs its own checkout: `update --from .` there writes the dev pin."""
    if source.resolve() != project_root.resolve() or not (source / "pskill_runner").is_dir():
        raise InstallError(
            "A folder source is only for the pskill repository itself (`update --from .` in its checkout). "
            "Give a release archive or its URL instead."
        )
    return DEV_PIN, pin_entry_script((source / "pskill.py").read_text(encoding="utf-8"), DEV_PIN)


def put_in_cache(pin: Pin, data: bytes) -> None:
    """Unpack the release where the entry script looks for it, as the entry script does."""
    folder = cache_folder(pin, cache_root())
    if (folder / "pskill_runner").is_dir():
        return
    folder.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{folder.name}-", dir=folder.parent))
    unpack_release(data, staging)
    try:
        staging.rename(folder)
    except OSError:  # another process unpacked the same release first
        shutil.rmtree(staging, ignore_errors=True)


def installed_version(pskill_folder: Path) -> str:
    """The version that the project runs now: its pin, or the version that a vendored install recorded."""
    try:
        version = read_pin((pskill_folder / "pskill.py").read_text(encoding="utf-8")).version
    except InstallError:
        version = ""
    if not version and (pskill_folder / "VENDORED").is_file():
        version = str(json.loads((pskill_folder / "VENDORED").read_text(encoding="utf-8")).get("version", ""))
    return version or "(no pin)"


def remove_legacy_files(pskill_folder: Path) -> list[str]:
    """Delete the runner files of a vendored install. Return their names, a folder with a trailing slash."""
    if not (pskill_folder / "VENDORED").is_file():
        return []
    removed = []
    for name in LEGACY_PATHS:
        path = pskill_folder / name
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(f"{name}/")
        elif path.is_file():
            path.unlink()
            removed.append(name)
    return removed


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_if_missing(path: Path, text: str) -> None:
    if not path.exists():
        write_text(path, text)
