"""YAML loading with the two rules that pskill needs.

- Skill files: only `true` and `false` are booleans (the YAML 1.2 rule). Plain PyYAML follows
  YAML 1.1, where `yes`, `no`, `on`, and `off` also become booleans, so a choice named `no` would break.
- Agent answers: every value arrives as text. The runner converts each field later, using the
  block's declared output types (see `field_types.convert_answer`). A plain value that holds `: `
  (`summary: api/src/a.ts:12: unused import`) is not valid YAML, yet it can only mean text, so it is
  read as text.
"""

import json
import re
from typing import Any

import yaml

BOOLEAN_TAG = "tag:yaml.org,2002:bool"
YAML_1_2_BOOLEAN = re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$")


class SkillYamlLoader(yaml.SafeLoader):
    """A safe loader where only true and false are booleans."""


# Replace the YAML 1.1 boolean rule with the YAML 1.2 one, for this loader only.
SkillYamlLoader.yaml_implicit_resolvers = {
    first_character: [(tag, pattern) for tag, pattern in resolvers if tag != BOOLEAN_TAG]
    for first_character, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
SkillYamlLoader.add_implicit_resolver(BOOLEAN_TAG, YAML_1_2_BOOLEAN, list("tTfF"))

COLON_IN_VALUE = "mapping values are not allowed here"
# A field line: indent, list dashes, a key, `: `, and a plain value (no quote, flow, block, or tag start).
FIELD_LINE = re.compile(r"(?P<head>\s*(?:-\s+)*[^\s#'\"][^\n]*?:\s+)(?P<value>[^\s'\"\[{|>&*!%@`][^\n]*)")


def load_skill_yaml(text: str) -> Any:
    """Load a skill file (or any pskill-owned YAML file)."""
    return yaml.load(text, Loader=SkillYamlLoader)  # SkillYamlLoader is a SafeLoader, so this is safe.


def load_answer_yaml(text: str) -> Any:
    """Load an agent answer. Every scalar value stays text, also a plain value that holds `: `.

    Each failed parse on such a value quotes that one line and parses again. A line that quoting cannot
    fix raises the first error, so the agent sees where its own answer broke.
    """
    first_error: yaml.MarkedYAMLError | None = None
    while True:
        try:
            return yaml.load(text, Loader=yaml.BaseLoader)  # BaseLoader builds only str, list, and dict.
        except yaml.MarkedYAMLError as error:
            first_error = first_error or error
            quoted = with_colon_value_quoted(text, error)
            if quoted is None:
                raise first_error from None
            text = quoted


def with_colon_value_quoted(text: str, error: yaml.MarkedYAMLError) -> str | None:
    """The text with the plain value of the error's line in double quotes, or None when that does not apply.

    In plain YAML, ` #` starts a comment, so the quoted value ends there too.
    """
    if error.problem != COLON_IN_VALUE or error.problem_mark is None:
        return None
    lines = text.split("\n")
    match = FIELD_LINE.fullmatch(lines[error.problem_mark.line])
    if match is None:
        return None
    value = match["value"].split(" #")[0].rstrip()
    lines[error.problem_mark.line] = match["head"] + json.dumps(value, ensure_ascii=False)
    return "\n".join(lines)
