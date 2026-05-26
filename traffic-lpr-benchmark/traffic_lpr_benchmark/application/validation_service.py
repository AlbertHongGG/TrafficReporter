from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from ..domain.models import (
    BenchmarkCase,
    BenchmarkSuite,
    READABLE_EXPECTATION_KIND,
    normalize_expectation_kind,
    resolve_case_expectation,
)
from ..infrastructure.schema_registry import load_shared_schema
from ..infrastructure.schema_validation import SchemaValidationError, validate_payload
from .case_registry_service import build_suite_registry, summarize_suite_registry


ALLOWED_CASE_MODES = {'frame', 'interval'}
SUITE_SCHEMA = load_shared_schema('benchmark', 'benchmark-suite.schema.json')
RUN_BUNDLE_SCHEMA = load_shared_schema('benchmark', 'benchmark-run-bundle.schema.json')
ANALYSIS_PROFILE_CATALOG_SCHEMA = load_shared_schema('lpr', 'analysis-profile-catalog.schema.json')


class ValidationError(Exception):
    pass


@dataclass(slots=True, frozen=True)
class ValidatedSuite:
    source: str
    payload: dict[str, Any]
    suite: BenchmarkSuite


@dataclass(slots=True, frozen=True)
class ValidatedProfileCatalog:
    source: str
    payload: dict[str, Any]


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as error:
        raise ValidationError(f'{path}: invalid JSON: {error}') from error


def validated_suite_from_file(path: Path) -> ValidatedSuite:
    payload = load_json(path)
    return validated_suite_from_payload(payload, source=str(path))


def validated_suite_from_payload(payload: dict[str, Any], source: str = 'suite') -> ValidatedSuite:
    validate_suite_payload(payload, source=source)
    return ValidatedSuite(source=source, payload=payload, suite=BenchmarkSuite.from_payload(payload))


def validate_suite_file(path: Path) -> dict[str, Any]:
    return validated_suite_from_file(path).payload


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

        errors.extend(_semantic_case_errors(case, suite.analysis_profile_id, case_source))

    if suite.source is not None:
        source_kind = suite.source.get('kind')
        source_path = suite.source.get('path')
        if not isinstance(source_kind, str) or not source_kind.strip():
            errors.append(f'{source}.source.kind is required when source metadata is present')
        if not isinstance(source_path, str) or not source_path.strip():
            errors.append(f'{source}.source.path is required when source metadata is present')

    if errors:
        raise ValidationError('\n'.join(errors))


def _semantic_case_errors(case: BenchmarkCase, suite_analysis_profile_id: str | None, case_source: str) -> list[str]:
    errors: list[str] = []
    expectation_payload = case.payload.get('expectation') if isinstance(case.payload.get('expectation'), dict) else None
    expectation_kind, expected_text = resolve_case_expectation(case.payload)
    if expectation_kind == READABLE_EXPECTATION_KIND and expected_text is None:
        errors.append(f'{case_source} readable expectation requires expectedText or expectation.text')
    if expectation_payload is not None:
        declared_kind = normalize_expectation_kind(expectation_payload.get('kind'))
        if declared_kind is None:
            errors.append(f'{case_source}.expectation.kind must be one of ["readable", "unreadable"]')
        elif declared_kind == READABLE_EXPECTATION_KIND:
            declared_text = _normalize_expectation_text(expectation_payload.get('text'))
            payload_text = _normalize_expectation_text(case.payload.get('expectedText'))
            if declared_text is None and payload_text is None:
                errors.append(f'{case_source}.expectation.text is required for readable expectations when expectedText is absent')
            if declared_text is not None and payload_text is not None and declared_text != payload_text:
                errors.append(f'{case_source}.expectation.text must match expectedText when both are declared')
        elif _normalize_expectation_text(expectation_payload.get('text')) is not None:
            errors.append(f'{case_source}.expectation.text must be omitted for unreadable expectations')

    metadata = case.payload.get('metadata') if isinstance(case.payload.get('metadata'), dict) else None
    if metadata is None:
        errors.append(f'{case_source}.metadata is required for benchmark semantics')
    else:
        dataset = metadata.get('dataset')
        if not isinstance(dataset, str) or not dataset.strip():
            errors.append(f'{case_source}.metadata.dataset is required')
        if resolve_case_category(metadata) == 'uncategorized':
            errors.append(f'{case_source}.metadata.category or metadata.dominantCategory is required')
        source_mode = metadata.get('sourceMode')
        if source_mode is not None and source_mode != case.mode:
            errors.append(f'{case_source}.metadata.sourceMode must match case.mode')

    analysis_profile_id = case.payload.get('analysisProfileId')
    if not isinstance(suite_analysis_profile_id, str) and (not isinstance(analysis_profile_id, str) or not analysis_profile_id.strip()):
        errors.append(f'{case_source}.analysisProfileId is required unless suite.analysisProfileId is declared')

    tags = case.payload.get('tags') or []
    if isinstance(tags, list):
        normalized_tags = [tag.strip() for tag in tags if isinstance(tag, str) and tag.strip()]
        if len(normalized_tags) != len(set(normalized_tags)):
            errors.append(f'{case_source}.tags must be unique when provided')

    if case.mode == 'frame':
        time_ms = _coerce_optional_int(case.payload.get('timeMs'))
        if time_ms is None or time_ms < 0:
            errors.append(f'{case_source}.timeMs must be a non-negative integer')

    if case.mode == 'interval':
        interval = case.payload.get('interval') if isinstance(case.payload.get('interval'), dict) else None
        start_ms = _coerce_optional_int(interval.get('startMs')) if interval is not None else None
        end_ms = _coerce_optional_int(interval.get('endMs')) if interval is not None else None
        anchor_time_ms = _coerce_optional_int(case.payload.get('anchorTimeMs'))
        if start_ms is None or end_ms is None or end_ms <= start_ms:
            errors.append(f'{case_source}.interval must declare startMs < endMs')
        elif anchor_time_ms is not None and not (start_ms <= anchor_time_ms <= end_ms):
            errors.append(f'{case_source}.anchorTimeMs must lie within interval.startMs/endMs')

    return errors


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


def validated_profile_catalog_from_file(path: Path) -> ValidatedProfileCatalog:
    payload = load_json(path)
    validate_profile_catalog_payload(payload, source=str(path))
    return ValidatedProfileCatalog(source=str(path), payload=payload)


def validate_profile_catalog_file(path: Path) -> dict[str, Any]:
    return validated_profile_catalog_from_file(path).payload


def resolve_case_category(metadata: dict[str, Any]) -> str:
    for key in ('category', 'dominantCategory'):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return 'uncategorized'


def _coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_expectation_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = ''.join(character for character in value.strip().upper() if character.isalnum())
    return normalized or None


def inspect_suite_payload(payload: dict[str, Any], base_dir: Path | None = None) -> dict[str, Any]:
    suite = BenchmarkSuite.from_payload(payload)
    registry = build_suite_registry(payload, base_dir=base_dir)
    registry_summary = summarize_suite_registry(registry)
    dataset_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()
    missing_source_paths: list[dict[str, str]] = []

    for case in suite.cases:
        metadata = case.payload.get('metadata') if isinstance(case.payload.get('metadata'), dict) else {}
        dataset = str(metadata.get('dataset') or 'unknown')
        split = str(metadata.get('split') or 'unknown')
        category = resolve_case_category(metadata)
        dataset_counts[dataset] += 1
        split_counts[split] += 1
        category_counts[category] += 1

        source_path = Path(case.source_path)
        if not source_path.is_absolute() and base_dir is not None:
            source_path = (base_dir / source_path).resolve()
        if not source_path.exists():
            missing_source_paths.append({
                'id': case.id,
                'sourcePath': str(source_path),
            })

    return {
        'suiteId': suite.suite_id,
        'title': suite.title,
        'analysisProfileId': suite.analysis_profile_id,
        'cases': len(suite.cases),
        'modes': suite.mode_counts(),
        'suiteHash': registry_summary['suiteHash'],
        'datasets': dict(sorted(dataset_counts.items())),
        'splits': dict(sorted(split_counts.items())),
        'categories': dict(sorted(category_counts.items())),
        'topTags': suite.top_tags(),
        'missingSourcePathCount': len(missing_source_paths),
        'missingSourcePaths': missing_source_paths[:20],
        'validationCounts': registry_summary['validationCounts'],
        'sourceIntegrity': registry_summary['sourceIntegrity'],
        'readyToRun': len(missing_source_paths) == 0,
    }