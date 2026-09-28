"""YAML loading with the two rules that pskill needs.

- Skill files: only `true` and `false` are booleans (the YAML 1.2 rule). Plain PyYAML follows
  YAML 1.1, where `yes`, `no`, `on`, and `off` also become booleans, so a choice named `no` would break.
- Agent answers: every value arrives as text. The runner converts each field later, using the
  block's declared output types (see `field_types.convert_answer`).
"""

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


def load_skill_yaml(text: str) -> Any:
    """Load a skill file (or any pskill-owned YAML file)."""
    return yaml.load(text, Loader=SkillYamlLoader)  # SkillYamlLoader is a SafeLoader, so this is safe.


def load_answer_yaml(text: str) -> Any:
    """Load an agent answer. Every scalar value stays text."""
    return yaml.load(text, Loader=yaml.BaseLoader)  # BaseLoader builds only str, list, and dict.
