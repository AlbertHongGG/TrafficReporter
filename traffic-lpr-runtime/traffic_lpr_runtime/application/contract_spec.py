from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from traffic_lpr_runtime.domain.errors import RuntimeFailure


PRIMITIVE_TYPES = {'string', 'number', 'boolean', 'json'}


def _spec_path() -> Path:
    return Path(__file__).resolve().parents[3] / 'schemas' / 'lpr' / 'lpr-contracts.json'


@lru_cache(maxsize=1)
def load_lpr_contract_spec() -> dict[str, Any]:
    return json.loads(_spec_path().read_text(encoding='utf-8'))


class LprContractRegistry:
    def __init__(self) -> None:
        spec = load_lpr_contract_spec()
        self._runtime_commands = dict(spec.get('runtimeCommands') or {})
        self._definitions = {
            definition['name']: definition
            for definition in spec.get('definitions') or []
            if isinstance(definition, dict) and isinstance(definition.get('name'), str)
        }
        self._externals = {
            name: value
            for name, value in (spec.get('externals') or {}).items()
            if isinstance(name, str) and isinstance(value, dict)
        }

    def validate_request(self, subcommand: str, payload: dict[str, Any]) -> None:
        command = self._runtime_commands.get(subcommand)
        request_name = command.get('request') if isinstance(command, dict) else None
        if isinstance(request_name, str):
            self._validate_named_type(request_name, payload, f'{subcommand}.request')

    def validate_response(self, subcommand: str, payload: dict[str, Any]) -> None:
        command = self._runtime_commands.get(subcommand)
        response_name = command.get('response') if isinstance(command, dict) else None
        if isinstance(response_name, str):
            self._validate_named_type(response_name, payload, f'{subcommand}.response')

    def _validate_named_type(self, type_name: str, value: Any, path: str) -> None:
        if type_name in self._definitions:
            definition = self._definitions[type_name]
        elif type_name in self._externals:
            definition = self._externals[type_name]
        else:
            raise RuntimeFailure(f'Unknown LPR contract type: {type_name}')
        self._validate_definition(definition, value, path)

    def _validate_definition(self, definition: dict[str, Any], value: Any, path: str) -> None:
        kind = definition.get('kind')
        if kind == 'stringUnion':
            if not isinstance(value, str):
                raise RuntimeFailure(f'{path} must be a string.')
            values = definition.get('values') or []
            if value not in values:
                raise RuntimeFailure(f'{path} must be one of {values}.')
            return
        if kind == 'alias':
            self._validate_primitive(str(definition.get('validatorType') or 'json'), value, path)
            return
        if kind == 'object':
            if not isinstance(value, dict):
                raise RuntimeFailure(f'{path} must be an object.')
            for field in definition.get('fields') or []:
                self._validate_field(field, value, path)
            return
        raise RuntimeFailure(f'{path} uses an unsupported contract kind: {kind}.')

    def _validate_field(self, field: dict[str, Any], payload: dict[str, Any], path: str) -> None:
        field_name = str(field['name'])
        field_path = f'{path}.{field_name}'
        if field_name not in payload:
            if field.get('optional'):
                return
            raise RuntimeFailure(f'{field_path} is required.')

        value = payload[field_name]
        if value is None:
            if field.get('nullable') or field.get('optional'):
                return
            raise RuntimeFailure(f'{field_path} cannot be null.')

        field_type = field.get('type')
        if field_type == 'array':
            if not isinstance(value, list):
                raise RuntimeFailure(f'{field_path} must be an array.')
            item_type = str(field.get('items'))
            for index, item in enumerate(value):
                self._validate_type_name(item_type, item, f'{field_path}[{index}]')
            return

        self._validate_type_name(str(field_type), value, field_path)

    def _validate_type_name(self, type_name: str, value: Any, path: str) -> None:
        if type_name in PRIMITIVE_TYPES:
            self._validate_primitive(type_name, value, path)
            return
        self._validate_named_type(type_name, value, path)

    def _validate_primitive(self, primitive: str, value: Any, path: str) -> None:
        if primitive == 'string':
            if not isinstance(value, str):
                raise RuntimeFailure(f'{path} must be a string.')
            return
        if primitive == 'number':
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise RuntimeFailure(f'{path} must be a number.')
            return
        if primitive == 'boolean':
            if not isinstance(value, bool):
                raise RuntimeFailure(f'{path} must be a boolean.')
            return
        if primitive == 'json':
            return
        raise RuntimeFailure(f'{path} uses an unknown primitive contract type: {primitive}.')
