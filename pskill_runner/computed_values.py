"""Computed values: everything inside `{{ }}` (SPEC.md section 7.1).

Rules:
- A value that is exactly one `{{ ... }}` keeps the type of its result (a number, a list, true or false).
- Any other text with `{{ }}` or `{% %}` renders to text.
- Plain values (no braces) stay as they are.
- A missing value (a block that has not run, an optional field that was not given) can be chained,
  compared (the result is false), tested with `is defined`, or replaced with `| default(x)`.
  Printing it, iterating over it, or using it as a whole value is an error. This prevents silent
  empty text, such as an empty comment posted to GitHub.
"""

import re
from typing import Any, NoReturn

from jinja2 import ChainableUndefined, TemplateSyntaxError, UndefinedError, nodes
from jinja2.sandbox import SandboxedEnvironment

SINGLE_EXPRESSION = re.compile(r"^\s*\{\{(?P<expression>(?:(?!\{\{|\}\}).)*)\}\}\s*$", re.DOTALL)
REFERENCE_NAMESPACES = ("inputs", "steps", "history")


class ComputedValueError(Exception):
    """A `{{ }}` value could not be computed."""


class MissingValue(ChainableUndefined):
    """An undefined value that fails loudly when someone prints it or iterates over it."""

    def _fail_as_missing(self) -> NoReturn:
        raise UndefinedError(f"{self._undefined_name or 'a value'} is missing")

    def __str__(self) -> str:
        self._fail_as_missing()

    def __iter__(self) -> Any:
        self._fail_as_missing()

    def __len__(self) -> int:
        self._fail_as_missing()


def matches(text: Any, pattern: str) -> bool:
    """True when the regular expression `pattern` matches anywhere in the text. Use `^` and `$` to anchor it."""
    return re.search(pattern, str(text)) is not None


class PskillEnvironment(SandboxedEnvironment):
    """The Jinja environment of pskill.

    `a.b` reads the key "b" of a mapping before any Python attribute. Without this, a field named
    `items`, `keys`, or `values` would return a dictionary method instead of the field.
    """

    def getattr(self, obj: Any, attribute: str) -> Any:
        if isinstance(obj, dict) and attribute in obj:
            return obj[attribute]
        return super().getattr(obj, attribute)


ENVIRONMENT = PskillEnvironment(undefined=MissingValue, keep_trailing_newline=True, autoescape=False)
ENVIRONMENT.tests["matches"] = matches


def is_single_expression(value: str) -> bool:
    return SINGLE_EXPRESSION.match(value) is not None


def compute(value: Any, context: dict[str, Any]) -> Any:
    """Compute a YAML value: plain values stay, `{{ }}` values are evaluated, lists and mappings recurse."""
    if isinstance(value, list):
        return [compute(item, context) for item in value]
    if isinstance(value, dict):
        return {key: compute(item, context) for key, item in value.items()}
    if not isinstance(value, str) or ("{{" not in value and "{%" not in value):
        return value
    match = SINGLE_EXPRESSION.match(value)
    if match is None:
        return render_text(value, context)
    try:
        result = ENVIRONMENT.compile_expression(match["expression"], undefined_to_none=False)(**context)
    except (UndefinedError, TemplateSyntaxError) as error:
        raise ComputedValueError(f"{value.strip()!r}: {error}") from error
    if isinstance(result, MissingValue):
        raise ComputedValueError(f"{value.strip()!r}: the value is missing")
    return result


def render_text(template_text: str, context: dict[str, Any]) -> str:
    """Render text that contains `{{ }}` or `{% %}` (instructions, reports, script arguments)."""
    try:
        return ENVIRONMENT.from_string(template_text).render(**context)
    except (UndefinedError, TemplateSyntaxError) as error:
        raise ComputedValueError(f"{error} (in {template_text.strip()[:80]!r})") from error


def is_true(condition: str, context: dict[str, Any]) -> bool:
    """Evaluate a `when` condition."""
    return bool(compute(condition, context))


def syntax_errors(text: str) -> list[str]:
    """Return the syntax problems of a text with `{{ }}`. An empty list means it compiles."""
    try:
        ENVIRONMENT.parse(text)
    except TemplateSyntaxError as error:
        return [str(error)]
    return []


def find_references(text: str) -> set[tuple[str, str]]:
    """List the (namespace, name) pairs that a text reads, such as ("steps", "plan")."""
    references: set[tuple[str, str]] = set()
    for attribute in ENVIRONMENT.parse(text).find_all(nodes.Getattr):
        if isinstance(attribute.node, nodes.Name) and attribute.node.name in REFERENCE_NAMESPACES:
            references.add((attribute.node.name, attribute.attr))
    return references
