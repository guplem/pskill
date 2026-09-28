"""Field maps: the typed fields of skill inputs, skill outputs, and block outputs.

A field map is a small subset of JSON Schema written in YAML (SPEC.md section 5.3). Agent answers
arrive as text (see `yaml_loading.load_answer_yaml`), so `check_answer` converts each value to its
declared type and reports every problem in plain words.
"""

import re
from dataclasses import dataclass, field
from typing import Any

INTEGER_TEXT = re.compile(r"^[+-]?\d+$")
TRUE_TEXTS = {"true", "True", "TRUE"}
FALSE_TEXTS = {"false", "False", "FALSE"}


@dataclass(frozen=True)
class FieldSpec:
    """One declared field."""

    type: str
    description: str | None = None
    optional: bool = False
    default: Any = None
    enum: tuple[Any, ...] | None = None
    items: "FieldSpec | None" = None
    properties: dict[str, "FieldSpec"] = field(default_factory=dict)


FieldMap = dict[str, FieldSpec]


def parse_field_spec(raw: dict[str, Any]) -> FieldSpec:
    """Build a FieldSpec from its YAML form. The skill loader has already checked the structure."""
    enum = raw.get("enum")
    items = raw.get("items")
    return FieldSpec(
        type=raw["type"],
        description=raw.get("description"),
        optional=raw.get("optional", False),
        default=raw.get("default"),
        enum=tuple(enum) if enum is not None else None,
        items=parse_field_spec(items) if items is not None else None,
        properties=parse_field_map(raw.get("properties", {})),
    )


def parse_field_map(raw: dict[str, Any]) -> FieldMap:
    return {name: parse_field_spec(spec) for name, spec in raw.items()}


def check_answer(raw_answer: Any, fields: FieldMap) -> tuple[dict[str, Any], list[str]]:
    """Convert an answer to the declared types. Return the converted answer and the problems found."""
    if not isinstance(raw_answer, dict):
        return {}, ["The answer must be a list of 'field: value' lines, not plain text."]
    errors: list[str] = []
    converted = _check_mapping(raw_answer, fields, path="", errors=errors)
    return converted, errors


def _check_mapping(raw: dict[str, Any], fields: FieldMap, path: str, errors: list[str]) -> dict[str, Any]:
    converted: dict[str, Any] = {}
    for name, spec in fields.items():
        if name not in raw:
            if not spec.optional:
                errors.append(f"'{path}{name}' is a required field")
            continue
        converted[name] = _check_value(raw[name], spec, f"{path}{name}", errors)
    for name in raw:
        if name not in fields:
            errors.append(f"{path}{name}: this field is not part of the return format")
    return converted


def _check_value(raw: Any, spec: FieldSpec, path: str, errors: list[str]) -> Any:
    value = _convert(raw, spec, path, errors)
    if spec.enum is not None and value is not None and value not in spec.enum:
        allowed = ", ".join(str(option) for option in spec.enum)
        errors.append(f"{path}: {raw!r} is not one of: {allowed}")
    return value


def _convert(raw: Any, spec: FieldSpec, path: str, errors: list[str]) -> Any:
    """Convert one raw value. Report a problem and return None when it does not convert."""
    if spec.type == "array":
        if not isinstance(raw, list):
            errors.append(f"{path}: must be a list ('- item' lines)")
            return None
        item_spec = spec.items or FieldSpec(type="string")
        return [_check_value(item, item_spec, f"{path}[{index}]", errors) for index, item in enumerate(raw)]
    if spec.type == "object":
        if not isinstance(raw, dict):
            errors.append(f"{path}: must be a group of 'field: value' lines")
            return None
        return _check_mapping(raw, spec.properties, path=f"{path}.", errors=errors)
    if not isinstance(raw, str):
        errors.append(f"{path}: must be a single value, not a list or a group")
        return None
    return _convert_text(raw, spec.type, path, errors)


def _convert_text(text: str, type_name: str, path: str, errors: list[str]) -> Any:
    if type_name == "string":
        return text
    if type_name == "integer":
        if INTEGER_TEXT.match(text.strip()):
            return int(text)
        errors.append(f"{path}: {text!r} is not an integer")
        return None
    if type_name == "number":
        try:
            return int(text) if INTEGER_TEXT.match(text.strip()) else float(text)
        except ValueError:
            errors.append(f"{path}: {text!r} is not a number")
            return None
    if type_name == "boolean":
        if text in TRUE_TEXTS:
            return True
        if text in FALSE_TEXTS:
            return False
        errors.append(f"{path}: {text!r} is not true or false")
        return None
    raise ValueError(f"Unknown field type: {type_name}")
