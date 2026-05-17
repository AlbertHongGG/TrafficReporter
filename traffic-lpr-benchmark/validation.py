from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from models import BenchmarkSuite
from schema_registry import load_shared_schema
from schema_validation import SchemaValidationError, validate_payload


ALLOWED_CASE_MODES = {'frame', 'interval'}
SUITE_SCHEMA = load_shared_schema('benchmark', 'benchmark-suite.schema.json')
RUN_BUNDLE_SCHEMA = load_shared_schema('benchmark', 'benchmark-run-bundle.schema.json')
ANALYSIS_PROFILE_CATALOG_SCHEMA = load_shared_schema('lpr', 'analysis-profile-catalog.schema.json')


class ValidationError(Exception):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as error:
        raise ValidationError(f'{path}: invalid JSON: {error}') from error


def validate_suite_file(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    validate_suite_payload(payload, source=str(path))
    return payload


def validate_suite_payload(payload: dict[str, Any], source: str = 'suite') -> None:
    try:
        validate_payload(payload, SUITE_SCHEMA, source)
    except SchemaValidationError as error:
        raise ValidationError(str(error)) from error

    suite = BenchmarkSuite.from_payload(payload)
    errors: list[str] = []
    seen_case_ids: set[str] = set()
    for index, case in enumerate(suite.cases):
        case_source = f'{source}: cases[{index}]'
        if case.id in seen_case_ids:
            errors.append(f'{case_source}.id duplicates {case.id}')
        else:
            seen_case_ids.add(case.id)

        if case.mode not in ALLOWED_CASE_MODES:
            errors.append(f'{case_source}.mode must be one of {sorted(ALLOWED_CASE_MODES)}')
            continue

        if case.mode == 'frame' and 'timeMs' not in case.payload:
            errors.append(f'{case_source}.timeMs is required for frame cases')
        if case.mode == 'interval':
            interval = case.payload.get('interval')
            if not isinstance(interval, dict):
                errors.append(f'{case_source}.interval is required for interval cases')
            if 'anchorTimeMs' not in case.payload:
                errors.append(f'{case_source}.anchorTimeMs is required for interval cases')
            if not isinstance(case.payload.get('selectedTargetBox'), dict):
                errors.append(f'{case_source}.selectedTargetBox is required for interval cases')

    if errors:
        raise ValidationError('\n'.join(errors))


def validate_run_bundle_payload(payload: dict[str, Any], source: str = 'run-bundle') -> None:
    try:
        validate_payload(payload, RUN_BUNDLE_SCHEMA, source)
    except SchemaValidationError as error:
        raise ValidationError(str(error)) from error


def validate_profile_catalog_payload(payload: dict[str, Any], source: str = 'analysis-profile-catalog') -> None:
    try:
        validate_payload(payload, ANALYSIS_PROFILE_CATALOG_SCHEMA, source)
    except SchemaValidationError as error:
        raise ValidationError(str(error)) from error

    profile_ids = [str(profile.get('id')) for profile in payload.get('profiles') or [] if isinstance(profile, dict)]
    if payload.get('defaultProfileId') not in profile_ids:
        raise ValidationError(f'{source}: defaultProfileId must match one of the declared profiles')
    if len(profile_ids) != len(set(profile_ids)):
        raise ValidationError(f'{source}: profile ids must be unique')


def validate_profile_catalog_file(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    validate_profile_catalog_payload(payload, source=str(path))
    return payload
