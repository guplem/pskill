"""The project: the folder that contains `.pskill/`, and its settings in `.pskill/config.yaml`."""

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from pskill_runner.adapters import SPAWNING_HARNESSES, TIER_ROW_KEYS, TierRow
from pskill_runner.skill_model import MODEL_TIERS
from pskill_runner.yaml_loading import load_skill_yaml

PSKILL_FOLDER_NAME = ".pskill"
# The apps whose permission rules pskill knows how to write (claude_code.py and codex.py).
PERMISSION_APPS = ("claude-code", "codex")


class ProjectError(Exception):
    """The project folder or its settings cannot be used."""


@dataclass(frozen=True)
class Config:
    """Settings from `.pskill/config.yaml` (SPEC.md section 10.1). Every setting has a default."""

    stub_folders: list[str] = field(default_factory=lambda: [".agents/skills", ".claude/skills"])
    hook_files: list[str] = field(default_factory=lambda: [".claude/settings.json", ".codex/hooks.json"])
    permissions: list[str] = field(default_factory=lambda: list(PERMISSION_APPS))
    default_mode: str = "interactive"
    retries: int = 2
    autonomous_max_visits: int = 150
    script_timeout_s: int = 300
    stop_hook_max_blocks: int = 3
    viewer_port: int = 7777
    # The project's tier rows, per harness and tier. Each replaces the adapter's default row (adapters.py).
    tiers: Mapping[str, Mapping[str, TierRow]] = field(default_factory=dict)


@dataclass(frozen=True)
class Project:
    root: Path
    config: Config

    @property
    def pskill_folder(self) -> Path:
        return self.root / PSKILL_FOLDER_NAME

    @property
    def skills_folder(self) -> Path:
        return self.pskill_folder / "skills"

    @property
    def agents_folder(self) -> Path:
        return self.pskill_folder / "agents"

    @property
    def runs_folder(self) -> Path:
        return self.pskill_folder / "runs"


def find_project(start: Path) -> Project:
    """Find the nearest folder, from `start` upward, that contains `.pskill/`."""
    for folder in [start.resolve(), *start.resolve().parents]:
        if (folder / PSKILL_FOLDER_NAME).is_dir():
            return Project(root=folder, config=load_config(folder / PSKILL_FOLDER_NAME / "config.yaml"))
    raise ProjectError(f"No {PSKILL_FOLDER_NAME} folder in {start} or any parent folder. Run `pskill init` first.")


def load_config(path: Path) -> Config:
    if not path.is_file():
        return Config()
    raw = load_skill_yaml(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ProjectError(f"{path} must be a mapping of settings, such as 'retries: 2'")
    if "harnesses" in raw:
        raise ProjectError(
            f"{path}: 'harnesses' is now 'permissions' (the apps that get the permission rule), and the hooks go "
            "to the files in 'hook_files'. Rename the setting."
        )
    known_names = {setting.name for setting in fields(Config)}
    for name in raw:
        if name not in known_names:
            raise ProjectError(f"{path}: unknown setting {name!r} (known settings: {', '.join(sorted(known_names))})")
    for app in raw.get("permissions") or []:
        if app not in PERMISSION_APPS:
            raise ProjectError(f"{path}: unknown app {app!r} in permissions (known apps: {', '.join(PERMISSION_APPS)})")
    return Config(**{**raw, "tiers": load_tiers(path, raw.get("tiers"))})


def load_tiers(path: Path, raw: Any) -> dict[str, dict[str, TierRow]]:
    """The `tiers` setting: a mapping of harnesses, each a mapping of tiers, each a row with a model and an effort."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ProjectError(
            f"{path}: 'tiers' must be a mapping of harnesses, such as 'codex: {{fast: {{effort: low}}}}'"
        )
    for harness in raw:
        if harness not in SPAWNING_HARNESSES:
            raise ProjectError(
                f"{path}: unknown harness {harness!r} in tiers (known harnesses: {', '.join(SPAWNING_HARNESSES)})"
            )
    return {harness: load_harness_tiers(path, harness, rows) for harness, rows in raw.items()}


def load_harness_tiers(path: Path, harness: str, raw: Any) -> dict[str, TierRow]:
    location = f"tiers.{harness}"
    if not isinstance(raw, dict):
        raise ProjectError(f"{path}: {location!r} must be a mapping of tiers, such as 'fast: {{effort: low}}'")
    for tier in raw:
        if tier not in MODEL_TIERS:
            raise ProjectError(f"{path}: unknown tier {tier!r} in {location} (known tiers: {', '.join(MODEL_TIERS)})")
    return {tier: load_tier_row(path, f"{location}.{tier}", row) for tier, row in raw.items()}


def load_tier_row(path: Path, location: str, raw: Any) -> TierRow:
    if not isinstance(raw, dict):
        raise ProjectError(f"{path}: {location!r} must be a mapping, such as '{{model: haiku, effort: low}}'")
    for key, value in raw.items():
        if key not in TIER_ROW_KEYS:
            raise ProjectError(f"{path}: unknown key {key!r} in {location} (known keys: {', '.join(TIER_ROW_KEYS)})")
        if not isinstance(value, str) or not value.strip():
            raise ProjectError(f"{path}: '{location}.{key}' must be a non-empty text")
    return TierRow(model=raw.get("model"), effort=raw.get("effort"))
