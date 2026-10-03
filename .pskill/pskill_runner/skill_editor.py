"""The skill editor of the viewer (issue #3): change one block of `skill.yaml`, add a block, or delete one.

Only the lines of the changed block change. The rest of the file, comments and layout included, stays
byte for byte the same. `ruamel.yaml` keeps the comments, the quotes, and the anchors of the changed block.
It rewrites the block from a dump of the whole file, so an alias such as `*finding` stays an alias. A
change that leaves the skill with a structure error is refused, and the file stays as it was.
"""

import io
import os
import re
from pathlib import Path
from typing import Any

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from pskill_runner.project import Project
from pskill_runner.skill_loader import SKILL_FILE_NAME, SkillLoadError, load_skill, structure_problems
from pskill_runner.skill_model import next_targets
from pskill_runner.skill_schema import BLOCK_ID_PATTERN, is_skill_id
from pskill_runner.yaml_loading import load_skill_yaml

COMMON_KEYS = ("description", "max_visits", "on_max_visits")
EDITABLE_KEYS: dict[str, tuple[str, ...]] = {
    "task": ("instruction", "next", "retries"),
    "decision": ("decider", "instruction", "choices", "next", "retries"),
    "parallel": ("for_each", "agent", "task_name", "instruction", "next", "retries"),
    "script": ("run", "parse", "timeout_s", "next", "retries"),
    "call": ("skill", "next"),
    "end": ("status", "report"),
}
# The order of the keys in a block, as the skill files write them. A new key goes before the first later key.
KEY_ORDER = (
    "type",
    "description",
    "decider",
    "skill",
    "for_each",
    "agent",
    "task_name",
    "instruction",
    "run",
    "parse",
    "timeout_s",
    "inputs",
    "max_visits",
    "on_max_visits",
    "retries",
    "choices",
    "output",
    "status",
    "outputs",
    "report",
    "next",
)
FLOW_MAPPING_LIMIT = 60  # a longer mapping of plain values gets one line per key
INSTRUCTION_TEXT = "instruction_text"  # the new text of the block's `.md` instruction (or report) file


class EditError(Exception):
    """The change cannot be saved. `problems` lists every reason in plain words."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def round_trip_yaml() -> YAML:
    """The YAML reader and writer that keeps comments, quotes, and the layout of this project's skills."""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096  # never wrap a long line
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


# --- the three edits --------------------------------------------------------------------------------


def update_block(project: Project, skill_id: str, block_id: str, values: dict[str, Any]) -> None:
    """Set the given keys of one block (None removes a key), and write its instruction file."""
    folder = skill_folder(project, skill_id)
    text = read_skill_text(folder)
    document = round_trip_yaml().load(text)
    require_one_block_per_line(document)
    block = existing_block(document, block_id)
    allowed = COMMON_KEYS + EDITABLE_KEYS.get(str(block.get("type")), ())
    unknown = sorted(key for key in values if key not in allowed and key != INSTRUCTION_TEXT)
    if unknown:
        raise EditError([f"blocks.{block_id}: the editor cannot change {', '.join(unknown)}"])
    for key, value in values.items():
        if key == INSTRUCTION_TEXT:
            continue
        if value is None:
            block.pop(key, None)
        else:
            set_block_key(block, key, yaml_value(simple_next(value) if key == "next" else value))
    new_text = splice_block(text, document, block_id)
    instruction_file = instruction_file_of(folder, block, values)
    check_structure(new_text, folder.name)
    if instruction_file is not None:
        write_text_atomic(instruction_file, str(values[INSTRUCTION_TEXT]))
    if new_text != text:
        write_text_atomic(folder / SKILL_FILE_NAME, new_text)


def add_block(project: Project, skill_id: str, block_id: str, block_type: str) -> None:
    """Add a new block of a type at the end of `blocks`, with the least that makes it valid."""
    folder = skill_folder(project, skill_id)
    text = read_skill_text(folder)
    document = round_trip_yaml().load(text)
    require_one_block_per_line(document)
    if not re.match(BLOCK_ID_PATTERN, block_id):
        raise EditError([f"{block_id!r} is not a block id: use lower-case letters, digits, and _"])
    if block_id in document["blocks"]:
        raise EditError([f"The skill already has a block {block_id!r}."])
    if block_type not in EDITABLE_KEYS:
        raise EditError([f"{block_type!r} is not a block type (known types: {', '.join(sorted(EDITABLE_KEYS))})"])
    document["blocks"][block_id] = yaml_value(new_block(block_type, document, skill_id))
    document["blocks"][block_id].fa.set_block_style()
    lines = text.splitlines(True)
    _, end = block_regions(lines, round_trip_yaml().load(text))
    body = dumped_block_lines(document, block_id)
    before = [] if end == 0 or not lines[end - 1].strip() else ["\n"]
    after = ["\n"] if end < len(lines) else []
    new_text = "".join(lines[:end] + before + body + after + lines[end:])
    check_structure(new_text, folder.name)
    write_text_atomic(folder / SKILL_FILE_NAME, new_text)


def delete_block(project: Project, skill_id: str, block_id: str) -> None:
    """Delete a block that no edge leads to, with the comment lines just above it."""
    folder = skill_folder(project, skill_id)
    text = read_skill_text(folder)
    document = round_trip_yaml().load(text)
    require_one_block_per_line(document)
    existing_block(document, block_id)
    users = blocks_that_lead_to(folder, block_id)
    if users:
        raise EditError([f"These lead to {block_id!r}, so change them first: {', '.join(users)}"])
    lines = text.splitlines(True)
    starts, end = block_regions(lines, document)
    keys = list(starts)
    index = keys.index(block_id)
    stop = starts[keys[index + 1]] if index + 1 < len(keys) else end
    kept = lines[: starts[block_id]]
    if stop == len(lines):
        while kept and not kept[-1].strip():
            kept.pop()  # the last block goes, so the blank lines above it go too
    new_text = "".join(kept + lines[stop:])
    check_structure(new_text, folder.name)
    write_text_atomic(folder / SKILL_FILE_NAME, new_text)


# --- the text of one block ----------------------------------------------------------------------------


def is_comment_line(line: str) -> bool:
    return line.strip().startswith("#")


def block_regions(lines: list[str], document: CommentedMap) -> tuple[dict[str, int], int]:
    """The first line of each block (with the comment lines just above it), and the line after the last."""
    blocks = document["blocks"]
    starts = {}
    for key in blocks:
        starts[key] = with_comments_above(lines, blocks.lc.key(key)[0])
    top_keys = list(document)
    after_blocks = top_keys[top_keys.index("blocks") + 1 :]
    end = with_comments_above(lines, document.lc.key(after_blocks[0])[0]) if after_blocks else len(lines)
    return starts, end


def with_comments_above(lines: list[str], line: int) -> int:
    while line > 0 and is_comment_line(lines[line - 1]):
        line -= 1
    return line


def dumped_block_lines(document: CommentedMap, block_id: str) -> list[str]:
    """The lines of one block in a dump of the whole document, so its anchors and aliases stay as they are."""
    output = io.StringIO()
    round_trip_yaml().dump(document, output)
    lines = output.getvalue().splitlines(True)
    dumped = round_trip_yaml().load(output.getvalue())
    starts, end = block_regions(lines, dumped)
    keys = list(starts)
    index = keys.index(block_id)
    stop = starts[keys[index + 1]] if index + 1 < len(keys) else end
    body = lines[dumped["blocks"].lc.key(block_id)[0] : stop]
    while body and (not body[-1].strip() or is_comment_line(body[-1])):
        body.pop()  # the blank lines and the comments above the next block stay where they are
    return body


def splice_block(text: str, document: CommentedMap, block_id: str) -> str:
    """The file text with only the lines of one block replaced by its new lines."""
    lines = text.splitlines(True)
    starts, end = block_regions(lines, round_trip_yaml().load(text))
    keys = list(starts)
    index = keys.index(block_id)
    stop = starts[keys[index + 1]] if index + 1 < len(keys) else end
    key_line = document["blocks"].lc.key(block_id)[0]
    comments_above = lines[starts[block_id] : key_line]
    # The blank lines and comment lines after the block belong to the space between blocks: keep them.
    lines_after: list[str] = []
    for line in reversed(lines[starts[block_id] : stop]):  # pragma: no branch - a block always has its key line
        if line.strip() and not is_comment_line(line):
            break
        lines_after.insert(0, line)
    body = dumped_block_lines(document, block_id)
    return "".join(lines[: starts[block_id]] + comments_above + body + lines_after + lines[stop:])


# --- values ---------------------------------------------------------------------------------------------


def set_block_key(block: CommentedMap, key: str, value: Any) -> None:
    """Set a key. A new key goes where the skill files put it, so a block's blank line after it stays last."""
    if key in block:
        if isinstance(value, CommentedMap | CommentedSeq):
            # The old value's trailing comment would land between the key and the new items. The blank
            # lines after the block come back from the file text (see splice_block).
            block.ca.items.pop(key, None)
        block[key] = value
        return
    rank = KEY_ORDER.index(key)
    later = [
        index for index, existing in enumerate(block) if existing in KEY_ORDER and KEY_ORDER.index(existing) > rank
    ]
    if later:
        block.insert(later[0], key, value)
        return
    last_key = list(block)[-1]
    block[key] = value
    if last_key in block.ca.items:
        block.ca.items[key] = block.ca.items.pop(last_key)  # the blank line after the block moves down too


def simple_next(value: Any) -> Any:
    """Write `next` in its shortest form: a list with one edge and no `when` becomes the block id."""
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict) and not value[0].get("when"):
        return value[0]["to"]
    if isinstance(value, list):
        return [{key: edge[key] for key in ("when", "to") if edge.get(key)} for edge in value]
    if isinstance(value, dict):
        return {choice: simple_next(edges) for choice, edges in value.items()}
    return value


def yaml_value(value: Any) -> Any:
    """Plain lists and mappings as ruamel nodes, in the style of the skill files.

    A list of plain values, and a short mapping of plain values, go on one line (`run: [git, status]`,
    `next: {approve: done, stop: stopped}`). A list of mappings, such as an edge list, gets one line per key.
    A text with `{{ }}` gets double quotes.
    """
    if isinstance(value, dict):
        mapping = CommentedMap((key, yaml_value(item)) for key, item in value.items())
        plain = all(not isinstance(item, dict | list) for item in value.values())
        if plain and len(str(value)) <= FLOW_MAPPING_LIMIT:
            mapping.fa.set_flow_style()
        return mapping
    if isinstance(value, list):
        sequence = CommentedSeq(yaml_value(item) for item in value)
        for item in sequence:
            if isinstance(item, CommentedMap):
                item.fa.set_block_style()
        if all(not isinstance(item, dict | list) for item in value):
            sequence.fa.set_flow_style()
        return sequence
    if isinstance(value, str) and "{{" in value:
        return DoubleQuotedScalarString(value)
    return value


def new_block(block_type: str, document: CommentedMap, skill_id: str) -> dict[str, Any]:
    """The smallest valid block of a type. Its edge leads to the first end block, or to the first block."""
    blocks = document["blocks"]
    target = next((key for key, block in blocks.items() if block.get("type") == "end"), next(iter(blocks)))
    work_output = {"result": {"type": "string", "description": "What the step found or did."}}
    templates: dict[str, dict[str, Any]] = {
        "task": {"type": "task", "instruction": "Describe the work.", "output": work_output, "next": target},
        "decision": {"type": "decision", "decider": "human", "instruction": "Ask the user.", "next": target},
        "parallel": {
            "type": "parallel",
            "for_each": [],
            "instruction": "Describe the work for {{ item }}.",
            "output": work_output,
            "next": target,
        },
        "script": {"type": "script", "run": ["git", "status"], "next": target},
        "call": {"type": "call", "skill": skill_id, "next": target},
        "end": {"type": "end", "status": "succeeded"},
    }
    return templates[block_type]


def instruction_file_of(folder: Path, block: CommentedMap, values: dict[str, Any]) -> Path | None:
    """The `.md` file to write, when the change has an instruction text and the block names such a file."""
    if INSTRUCTION_TEXT not in values:
        return None
    reference = block.get("report" if block.get("type") == "end" else "instruction")
    if not isinstance(reference, str) or not reference.endswith(".md"):
        raise EditError(["This block has no instruction file: change its instruction text instead."])
    path = (folder / reference).resolve()
    if not path.is_relative_to(folder.resolve()):
        raise EditError([f"The instruction file {reference!r} is outside the skill folder."])
    return path


# --- files and checks -----------------------------------------------------------------------------------


def skill_folder(project: Project, skill_id: str) -> Path:
    folder = project.skills_folder / skill_id
    if not is_skill_id(skill_id) or not (folder / SKILL_FILE_NAME).is_file():
        raise EditError([f"There is no skill {skill_id!r}."])
    return folder


def read_skill_text(folder: Path) -> str:
    """The text with "\n" line ends. `write_text_atomic` writes the line ends that the file had."""
    return (folder / SKILL_FILE_NAME).read_text(encoding="utf-8")


def require_one_block_per_line(document: CommentedMap) -> None:
    """The editor finds a block by its lines, so `blocks:` written as a { } mapping cannot work."""
    blocks = document.get("blocks")
    if isinstance(blocks, CommentedMap) and blocks.fa.flow_style():
        raise EditError(
            [
                "skill.yaml writes `blocks:` as a { } mapping. The editor needs one block per line: "
                "change it in your code editor first."
            ]
        )


def existing_block(document: CommentedMap, block_id: str) -> CommentedMap:
    blocks = document.get("blocks")
    if not isinstance(blocks, CommentedMap) or block_id not in blocks:
        raise EditError([f"The skill has no block {block_id!r}."])
    block = blocks[block_id]
    if not isinstance(block, CommentedMap):
        raise EditError([f"blocks.{block_id} is not a mapping."])
    return block


def blocks_that_lead_to(folder: Path, block_id: str) -> list[str]:
    try:
        skill = load_skill(folder)
    except SkillLoadError as error:
        raise EditError(error.problems) from error
    users = ["the start"] if any(edge.to == block_id for edge in skill.entry) else []
    users += [other.id for other in skill.blocks.values() if other.id != block_id and block_id in next_targets(other)]
    return users


def check_structure(text: str, folder_name: str) -> None:
    """Refuse a change that leaves the skill with a structure error (the file would not load)."""
    try:
        raw = load_skill_yaml(text)
    except yaml.YAMLError as error:
        raise EditError([f"The change would leave skill.yaml not valid YAML: {error}"]) from error
    problems = structure_problems(raw, folder_name) if isinstance(raw, dict) else ["skill.yaml is not a mapping"]
    if problems:
        raise EditError(problems)


def write_text_atomic(path: Path, text: str) -> None:
    """Write to a temp file first, then replace the target, so a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    newline = "\r\n" if path.is_file() and b"\r\n" in path.read_bytes() else "\n"
    temp_path.write_text(text, encoding="utf-8", newline=newline)  # a CRLF file stays CRLF
    os.replace(temp_path, path)
