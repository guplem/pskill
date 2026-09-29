"""The structure of `skill.yaml`, as JSON Schema (SPEC.md sections 5 and 6).

The loader checks the top level first, then each block against the schema of its own type.
This gives one clear message per problem instead of one vague message for the whole file.
"""

from typing import Any

FIELD_TYPES = ["string", "integer", "number", "boolean", "array", "object"]

FIELD_SPEC_SCHEMA: dict[str, Any] = {
    "$defs": {
        "field": {
            "type": "object",
            "required": ["type"],
            "additionalProperties": False,
            "properties": {
                "type": {"enum": FIELD_TYPES},
                "description": {"type": "string"},
                "optional": {"type": "boolean"},
                "default": {},
                "enum": {"type": "array", "minItems": 1},
                "items": {"$ref": "#/$defs/field"},
                "properties": {"type": "object", "additionalProperties": {"$ref": "#/$defs/field"}},
            },
        },
        "field_map": {"type": "object", "additionalProperties": {"$ref": "#/$defs/field"}},
        "edges": {
            "oneOf": [
                {"type": "string"},
                {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["to"],
                        "additionalProperties": False,
                        "properties": {"to": {"type": "string"}, "when": {"type": "string"}},
                    },
                },
            ]
        },
        "choice_map": {"type": "object", "additionalProperties": {"type": "string"}},
    }
}

BLOCK_ID_PATTERN = "^[a-z0-9_]{1,64}$"

TOP_LEVEL_SCHEMA: dict[str, Any] = {
    **FIELD_SPEC_SCHEMA,
    "type": "object",
    "required": ["schema", "id", "description", "goal", "entry", "blocks"],
    "additionalProperties": False,
    "patternProperties": {"^x-": {}},
    "properties": {
        "schema": {"const": "pskill/v1"},
        "id": {"type": "string", "pattern": "^[a-z0-9]+(-[a-z0-9]+)*$", "maxLength": 64},
        "description": {"type": "string"},
        "goal": {"type": "string"},
        "invocation": {"enum": ["auto", "manual", "internal"]},
        "inputs": {"$ref": "#/$defs/field_map"},
        "outputs": {"$ref": "#/$defs/field_map"},
        "entry": {"$ref": "#/$defs/edges"},
        "blocks": {
            "type": "object",
            "minProperties": 1,
            "propertyNames": {"pattern": BLOCK_ID_PATTERN},
            "additionalProperties": {"type": "object", "required": ["type"]},
        },
    },
}

COMMON_BLOCK_PROPERTIES: dict[str, Any] = {
    "type": {"type": "string"},
    "description": {"type": "string"},
    "max_visits": {"type": "integer", "minimum": 1},
    "on_max_visits": {"type": "string"},
}


RETRIES_PROPERTY: dict[str, Any] = {"retries": {"type": "integer", "minimum": 0}}


def block_schema(required: list[str], properties: dict[str, Any]) -> dict[str, Any]:
    return {
        **FIELD_SPEC_SCHEMA,
        "type": "object",
        "required": required,
        "additionalProperties": False,
        "properties": {**COMMON_BLOCK_PROPERTIES, **properties},
    }


BLOCK_SCHEMAS: dict[str, dict[str, Any]] = {
    "task": block_schema(
        ["instruction", "output", "next"],
        {
            "instruction": {"type": "string"},
            "output": {"$ref": "#/$defs/field_map"},
            "next": {"$ref": "#/$defs/edges"},
            **RETRIES_PROPERTY,
        },
    ),
    "decision": block_schema(
        ["decider", "instruction", "next"],
        {
            "decider": {"enum": ["agent", "human"]},
            "instruction": {"type": "string"},
            "choices": {"type": "object", "minProperties": 2, "additionalProperties": {"type": "string"}},
            "output": {"$ref": "#/$defs/field_map"},
            "next": {"oneOf": [{"$ref": "#/$defs/edges"}, {"$ref": "#/$defs/choice_map"}]},
            **RETRIES_PROPERTY,
        },
    ),
    "parallel": block_schema(
        ["for_each", "instruction", "output", "next"],
        {
            "for_each": {"oneOf": [{"type": "array"}, {"type": "string"}]},
            "agent": {"type": "string"},
            "instruction": {"type": "string"},
            "output": {"$ref": "#/$defs/field_map"},
            "next": {"$ref": "#/$defs/edges"},
            **RETRIES_PROPERTY,
        },
    ),
    "script": block_schema(
        ["run", "next"],
        {
            "run": {"type": "array", "minItems": 1, "items": {"type": ["string", "number", "boolean"]}},
            "parse": {"enum": ["text", "json"]},
            "next": {"$ref": "#/$defs/edges"},
            "timeout_s": {"type": "integer", "minimum": 1},
            **RETRIES_PROPERTY,
        },
    ),
    "call": block_schema(
        ["skill", "next"],
        {
            "skill": {"type": "string"},
            "inputs": {"type": "object"},
            "next": {"$ref": "#/$defs/edges"},
        },
    ),
    "end": block_schema(
        ["status"],
        {
            "status": {"enum": ["succeeded", "failed", "cancelled"]},
            "outputs": {"type": "object"},
            "report": {"type": "string"},
        },
    ),
}
