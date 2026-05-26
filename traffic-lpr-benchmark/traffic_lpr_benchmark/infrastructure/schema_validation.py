from __future__ import annotations

from typing import Any


class SchemaValidationError(Exception):
    pass


def validate_payload(payload: Any, schema: dict[str, Any], source: str = '$') -> None:
    errors: list[str] = []
    _validate(payload, schema, source, errors)
    if errors:
        raise SchemaValidationError('\n'.join(errors))


def _validate(payload: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    expected_type = schema.get('type')
    if expected_type is not None and not _matches_type(payload, expected_type):
        errors.append(f'{path}: expected type {_describe_type(expected_type)}, got {type(payload).__name__}')
        return

    if 'const' in schema and payload != schema['const']:
        errors.append(f'{path}: expected constant value {schema["const"]!r}')
        return

    if 'enum' in schema and payload not in schema['enum']:
        errors.append(f'{path}: expected one of {schema["enum"]!r}, got {payload!r}')
        return

    if isinstance(payload, str):
        min_length = schema.get('minLength')
        if isinstance(min_length, int) and len(payload) < min_length:
            errors.append(f'{path}: string length must be at least {min_length}')

    if isinstance(payload, (int, float)) and not isinstance(payload, bool):
        minimum = schema.get('minimum')
        if isinstance(minimum, (int, float)) and payload < minimum:
            errors.append(f'{path}: value must be >= {minimum}')

    if isinstance(payload, list):
        min_items = schema.get('minItems')
        if isinstance(min_items, int) and len(payload) < min_items:
            errors.append(f'{path}: array length must be at least {min_items}')
        item_schema = schema.get('items')
        if isinstance(item_schema, dict):
            for index, item in enumerate(payload):
                _validate(item, item_schema, f'{path}[{index}]', errors)
        return

    if isinstance(payload, dict):
        required = schema.get('required') or []
        for key in required:
            if key not in payload:
                errors.append(f'{path}: missing required property {key!r}')

        properties = schema.get('properties') or {}
        for key, property_schema in properties.items():
            if key in payload and isinstance(property_schema, dict):
                _validate(payload[key], property_schema, f'{path}.{key}', errors)

        if schema.get('additionalProperties') is False:
            for key in payload:
                if key not in properties:
                    errors.append(f'{path}: unexpected property {key!r}')


def _matches_type(payload: Any, expected_type: Any) -> bool:
    if isinstance(expected_type, list):
        return any(_matches_type(payload, item) for item in expected_type)
    if expected_type == 'object':
        return isinstance(payload, dict)
    if expected_type == 'array':
        return isinstance(payload, list)
    if expected_type == 'string':
        return isinstance(payload, str)
    if expected_type == 'integer':
        return isinstance(payload, int) and not isinstance(payload, bool)
    if expected_type == 'number':
        return isinstance(payload, (int, float)) and not isinstance(payload, bool)
    if expected_type == 'boolean':
        return isinstance(payload, bool)
    if expected_type == 'null':
        return payload is None
    return True


def _describe_type(expected_type: Any) -> str:
    if isinstance(expected_type, list):
        return ' | '.join(str(item) for item in expected_type)
    return str(expected_type)