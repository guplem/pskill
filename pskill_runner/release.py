"""The release archive `pskill.zip`: the runner, published on every tagged release (SPEC.md M6).

Build it with: uv run python -m pskill_runner.release dist/pskill.zip
A project's pinned entry script downloads it once per computer (SPEC.md D20).
"""

import io
import os
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

RELEASE_FILES = ["pskill.py", "AUTHORING.md"]
RELEASE_FOLDERS = ["pskill_runner", "viewer"]
SKIPPED_PARTS = {"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
VERSION_PATTERN = re.compile(r'^__version__ = "(?P<version>[^"]+)"$', re.MULTILINE)
# The entry script pskill.py repeats this URL, because it must work before the runner is installed.
DEFAULT_RELEASE_URL = "https://github.com/guplem/pskill/releases/latest/download/pskill.zip"
VERSIONED_RELEASE_URL = "https://github.com/guplem/pskill/releases/download/v{version}/pskill.zip"
RELEASE_URL_VARIABLE = "PSKILL_RELEASE_URL"


class ReleaseError(Exception):
    """A source that is not a pskill release."""


def release_url() -> str:
    """The latest release archive, unless PSKILL_RELEASE_URL names another one (a mirror or a test file)."""
    return os.environ.get(RELEASE_URL_VARIABLE, DEFAULT_RELEASE_URL)


def release_file_map(source_root: Path) -> dict[str, Path]:
    """Relative path (with forward slashes) -> source file, for every file that the release archive holds."""
    files: dict[str, Path] = {}
    for name in RELEASE_FILES:
        if (source_root / name).is_file():
            files[name] = source_root / name
    for folder_name in RELEASE_FOLDERS:
        for path in sorted((source_root / folder_name).rglob("*")):
            if path.is_file() and not SKIPPED_PARTS.intersection(path.relative_to(source_root).parts):
                files[path.relative_to(source_root).as_posix()] = path
    if "pskill.py" not in files or not any(name.startswith("pskill_runner/") for name in files):
        raise ReleaseError(f"{source_root} is not a pskill source: it needs pskill.py and pskill_runner/.")
    return files


def build_release_archive(source_root: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative_path, source_path in release_file_map(source_root).items():
            archive.write(source_path, relative_path)
    return output_path


def is_url(source: str) -> bool:
    return source.startswith(("http://", "https://", "file://"))


def read_release(source: str) -> bytes:
    """The bytes of a release archive: a URL, or a path to a zip file."""
    if is_url(source):
        with urllib.request.urlopen(source) as response:
            return bytes(response.read())
    return Path(source).read_bytes()


def release_version(data: bytes) -> str:
    """The runner version inside a release archive."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            init_text = archive.read("pskill_runner/__init__.py").decode("utf-8")
    except (zipfile.BadZipFile, KeyError) as error:
        raise ReleaseError("The source is not a pskill release: it has no pskill_runner/__init__.py.") from error
    match = VERSION_PATTERN.search(init_text)
    if match is None:
        raise ReleaseError("The source is not a pskill release: its pskill_runner/__init__.py has no __version__.")
    return match["version"]


def unpack_release(data: bytes, folder: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        archive.extractall(folder)


if __name__ == "__main__":
    print(build_release_archive(Path.cwd(), Path(sys.argv[1])))
