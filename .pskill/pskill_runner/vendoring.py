"""`pskill init` and `pskill update`: copy the runner into a project (SPEC.md D20).

The vendored files are the same in the source repository and in a project's `.pskill/` folder:
the entry script, the runner package, the viewer, the launchers, and `AUTHORING.md`. So a vendored
`.pskill/` folder can itself be the source of another install. `VENDORED` records the version and a
hash of every vendored file, so `update` can refuse to overwrite a file that someone edited by hand.
"""

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from pskill_runner.project import PSKILL_FOLDER_NAME

VENDORED_FILE_NAME = "VENDORED"
VENDORED_FILES = ["pskill.py", "AUTHORING.md"]
VENDORED_FOLDERS = ["pskill_runner", "viewer", "launchers"]
SKIPPED_PARTS = {"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
GITATTRIBUTES_LINE = ".pskill/** text eol=lf"
VERSION_PATTERN = re.compile(r'^__version__ = "(?P<version>[^"]+)"$', re.MULTILINE)
DEFAULT_CONFIG = """\
# pskill settings (SPEC.md section 10.1). Every setting is optional; these are the defaults.
harnesses: [claude-code, codex]                # harnesses that get hooks and the permission rule
stub_folders: [.agents/skills, .claude/skills]  # where `pskill sync` writes the skill stubs
"""


class VendoringError(Exception):
    """The runner cannot be installed or updated safely."""


def vendored_file_map(source_root: Path) -> dict[str, Path]:
    """Relative path (with forward slashes) -> source file, for every file that gets vendored."""
    files: dict[str, Path] = {}
    for name in VENDORED_FILES:
        if (source_root / name).is_file():
            files[name] = source_root / name
    for folder_name in VENDORED_FOLDERS:
        folder = source_root / folder_name
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            if path.is_file() and not SKIPPED_PARTS.intersection(path.relative_to(source_root).parts):
                files[path.relative_to(source_root).as_posix()] = path
    if "pskill.py" not in files or not any(name.startswith("pskill_runner/") for name in files):
        raise VendoringError(f"{source_root} is not a pskill source: it needs pskill.py and pskill_runner/.")
    return files


def file_hash(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def source_version(source_root: Path) -> str:
    match = VERSION_PATTERN.search((source_root / "pskill_runner" / "__init__.py").read_text(encoding="utf-8"))
    return match["version"] if match else "unknown"


def init_project(project_root: Path, source_root: Path) -> list[str]:
    """Create `.pskill/` in a project. Return one line per thing done."""
    pskill_folder = project_root / PSKILL_FOLDER_NAME
    if (pskill_folder / "pskill.py").exists():
        raise VendoringError(f"{pskill_folder} already has the runner. Use `pskill update` instead.")
    lines = copy_vendored_files(source_root, pskill_folder, old_files=[])
    (pskill_folder / "skills").mkdir(parents=True, exist_ok=True)
    write_if_missing(pskill_folder / ".gitignore", "runs/\n__pycache__/\n")
    write_if_missing(pskill_folder / "config.yaml", DEFAULT_CONFIG)
    created = "Created .pskill/skills/, .pskill/config.yaml, and .pskill/.gitignore"
    if add_gitattributes_line(project_root / ".gitattributes"):
        return [*lines, f"{created}, and added a line to .gitattributes."]
    return [*lines, f"{created}."]


def update_project(project_root: Path, source_root: Path, force: bool) -> list[str]:
    """Replace the vendored files. Never touch skills, agents, runs, or config.yaml."""
    pskill_folder = project_root / PSKILL_FOLDER_NAME
    vendored = read_vendored(pskill_folder)
    edited = [
        relative_path
        for relative_path, recorded_hash in vendored["files"].items()
        if (pskill_folder / relative_path).is_file() and file_hash(pskill_folder / relative_path) != recorded_hash
    ]
    if edited and not force:
        listed = "\n- ".join(edited)
        raise VendoringError(
            f"These vendored files were edited by hand, so update would lose the changes:\n- {listed}\n"
            "Move the changes to the pskill repository, or run `pskill update --force` to overwrite them."
        )
    return copy_vendored_files(source_root, pskill_folder, old_files=list(vendored["files"]))


def read_vendored(pskill_folder: Path) -> dict[str, Any]:
    path = pskill_folder / VENDORED_FILE_NAME
    if not path.is_file():
        raise VendoringError(f"{path} is missing. Run `pskill init` first.")
    return dict(json.loads(path.read_text(encoding="utf-8")))


def copy_vendored_files(source_root: Path, pskill_folder: Path, old_files: list[str]) -> list[str]:
    """Copy the source's vendored files, delete the ones that the source no longer has, write VENDORED."""
    files = vendored_file_map(source_root)
    if source_root.resolve() == pskill_folder.resolve():
        raise VendoringError("The source and the target are the same folder.")
    for relative_path in old_files:
        if relative_path not in files:
            (pskill_folder / relative_path).unlink(missing_ok=True)
    for relative_path, source_path in files.items():
        target = pskill_folder / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source_path, target)  # copy keeps the executable bit of the launchers
    version = source_version(source_root)
    record = {
        "version": version,
        "source": source_label(source_root, project_root=pskill_folder.parent),
        "files": {relative_path: file_hash(pskill_folder / relative_path) for relative_path in files},
    }
    (pskill_folder / VENDORED_FILE_NAME).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    return [f"Vendored pskill {version} from {record['source']} ({len(files)} files)."]


def source_label(source_root: Path, project_root: Path) -> str:
    """The source as VENDORED records it: relative when it is inside the project, so no local path leaks."""
    try:
        return source_root.resolve().relative_to(project_root.resolve()).as_posix() or "."
    except ValueError:
        return source_root.resolve().as_posix()


def write_if_missing(path: Path, text: str) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")


def add_gitattributes_line(path: Path) -> bool:
    """Keep the vendored files and the skills in LF line endings, also on Windows checkouts.

    Return True when the line was missing and this call added it.
    """
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if GITATTRIBUTES_LINE in existing.splitlines():
        return False
    separator = "" if not existing or existing.endswith("\n") else "\n"
    path.write_text(existing + separator + GITATTRIBUTES_LINE + "\n", encoding="utf-8", newline="\n")
    return True
