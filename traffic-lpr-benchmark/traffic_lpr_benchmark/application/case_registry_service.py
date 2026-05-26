from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from ..domain.models import resolve_case_expectation


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_string_list(values: Any) -> tuple[str, ...]:
    if not isinstance(values, list):
        return ()
    normalized = [item.strip() for item in values if isinstance(item, str) and item.strip()]
    return tuple(normalized)


def _normalize_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get('metadata') if isinstance(payload.get('metadata'), dict) else {}
    category = _normalize_text(metadata.get('category')) or _normalize_text(metadata.get('dominantCategory'))
    dataset = _normalize_text(metadata.get('dataset'))
    split = _normalize_text(metadata.get('split'))
    normalized = dict(metadata)
    if dataset is not None:
        normalized['dataset'] = dataset
    if split is not None:
        normalized['split'] = split
    if category is not None:
        normalized['category'] = category
    return normalized


def _resolve_source_path(source_path: str, base_dir: Path | None) -> Path:
    candidate = Path(source_path)
    if candidate.is_absolute() or base_dir is None:
        return candidate.resolve()
    return (base_dir / candidate).resolve()


@dataclass(slots=True, frozen=True)
class SourceReference:
    declared_path: str
    resolved_path: str
    exists: bool
    path_kind: str
    source_hash: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            'declaredPath': self.declared_path,
            'resolvedPath': self.resolved_path,
            'exists': self.exists,
            'pathKind': self.path_kind,
            'sourceHash': self.source_hash,
        }


@dataclass(slots=True, frozen=True)
class GroundTruth:
    expectation_kind: str
    expected_text: str | None
    frame_time_ms: int | None
    anchor_time_ms: int | None
    interval: dict[str, Any] | None
    selected_target_box: dict[str, Any] | None
    selected_target_track_id: str | None
    ground_truth_frames: tuple[dict[str, Any], ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            'expectationKind': self.expectation_kind,
            'expectedText': self.expected_text,
            'timeMs': self.frame_time_ms,
            'anchorTimeMs': self.anchor_time_ms,
            'interval': self.interval,
            'selectedTargetBox': self.selected_target_box,
            'selectedTargetTrackId': self.selected_target_track_id,
            'groundTruthFrames': [dict(frame) for frame in self.ground_truth_frames],
        }


@dataclass(slots=True, frozen=True)
class CaseValidation:
    status: str
    messages: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            'status': self.status,
            'messages': list(self.messages),
        }


@dataclass(slots=True, frozen=True)
class BenchmarkCaseRecord:
    declared_id: str
    content_id: str
    mode: str
    analysis_profile_id: str | None
    tags: tuple[str, ...]
    metadata: dict[str, Any]
    source: SourceReference
    ground_truth: GroundTruth
    validation: CaseValidation

    def to_payload(self) -> dict[str, Any]:
        return {
            'declaredId': self.declared_id,
            'contentId': self.content_id,
            'mode': self.mode,
            'analysisProfileId': self.analysis_profile_id,
            'tags': list(self.tags),
            'metadata': dict(self.metadata),
            'source': self.source.to_payload(),
            'groundTruth': self.ground_truth.to_payload(),
            'validation': self.validation.to_payload(),
        }


@dataclass(slots=True, frozen=True)
class BenchmarkSuiteRegistry:
    suite_id: str
    title: str | None
    analysis_profile_id: str | None
    source: dict[str, Any] | None
    suite_hash: str
    warnings: tuple[str, ...]
    cases: tuple[BenchmarkCaseRecord, ...]

    def to_payload(self) -> dict[str, Any]:
        validation_counts: dict[str, int] = {}
        for case in self.cases:
            validation_counts[case.validation.status] = validation_counts.get(case.validation.status, 0) + 1
        return {
            'suiteId': self.suite_id,
            'title': self.title,
            'analysisProfileId': self.analysis_profile_id,
            'source': dict(self.source) if self.source is not None else None,
            'suiteHash': self.suite_hash,
            'caseCount': len(self.cases),
            'warnings': list(self.warnings),
            'validationCounts': validation_counts,
            'cases': [case.to_payload() for case in self.cases],
        }

    def validation_counts(self) -> dict[str, int]:
        payload = self.to_payload()
        return dict(payload.get('validationCounts') or {})


def build_suite_registry(suite_payload: dict[str, Any], base_dir: Path | None = None) -> BenchmarkSuiteRegistry:
    suite_source = dict(suite_payload.get('source') or {}) if isinstance(suite_payload.get('source'), dict) else None
    default_profile = _normalize_text(suite_payload.get('analysisProfileId'))
    case_records: list[BenchmarkCaseRecord] = []
    warnings: list[str] = []

    for case_payload in suite_payload.get('cases') or []:
        if not isinstance(case_payload, dict):
            continue
        case_record = _build_case_record(case_payload, base_dir=base_dir, default_profile=default_profile)
        case_records.append(case_record)
        if case_record.validation.status != 'ready':
            warnings.append(f'{case_record.declared_id}:{case_record.validation.status}')

    suite_hash = _sha256_text(_canonical_json([
        suite_payload.get('suiteId'),
        suite_payload.get('analysisProfileId'),
        [case.content_id for case in case_records],
    ]))
    return BenchmarkSuiteRegistry(
        suite_id=str(suite_payload.get('suiteId') or ''),
        title=_normalize_text(suite_payload.get('title')),
        analysis_profile_id=default_profile,
        source=suite_source,
        suite_hash=suite_hash,
        warnings=tuple(warnings),
        cases=tuple(case_records),
    )


def summarize_suite_registry(registry: BenchmarkSuiteRegistry) -> dict[str, Any]:
    dataset_counts: dict[str, int] = {}
    split_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    source_integrity = {
        'missingSourceCount': 0,
        'hashedSourceCount': 0,
        'readyCaseCount': 0,
        'warningCaseCount': 0,
        'blockedCaseCount': 0,
    }

    for case in registry.cases:
        metadata = case.metadata
        dataset = str(metadata.get('dataset') or 'unknown')
        split = str(metadata.get('split') or 'unknown')
        category = str(metadata.get('category') or 'uncategorized')
        dataset_counts[dataset] = dataset_counts.get(dataset, 0) + 1
        split_counts[split] = split_counts.get(split, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1
        if not case.source.exists:
            source_integrity['missingSourceCount'] += 1
        if case.source.source_hash is not None:
            source_integrity['hashedSourceCount'] += 1
        if case.validation.status == 'ready':
            source_integrity['readyCaseCount'] += 1
        elif case.validation.status == 'blocked':
            source_integrity['blockedCaseCount'] += 1
        else:
            source_integrity['warningCaseCount'] += 1

    return {
        'suiteHash': registry.suite_hash,
        'datasets': dict(sorted(dataset_counts.items())),
        'splits': dict(sorted(split_counts.items())),
        'categories': dict(sorted(category_counts.items())),
        'sourceIntegrity': source_integrity,
        'validationCounts': registry.validation_counts(),
    }


def _build_case_record(
    case_payload: dict[str, Any],
    *,
    base_dir: Path | None,
    default_profile: str | None,
) -> BenchmarkCaseRecord:
    expectation_kind, expected_text = resolve_case_expectation(case_payload)
    declared_path = str(case_payload.get('sourcePath') or '')
    resolved_path = _resolve_source_path(declared_path, base_dir=base_dir)
    exists = resolved_path.exists()
    source_hash = _sha256_file(resolved_path) if exists and resolved_path.is_file() else None
    metadata = _normalize_metadata(case_payload)
    messages: list[str] = []
    if not exists:
        messages.append('missing-source')
    if _normalize_text(metadata.get('dataset')) is None:
        messages.append('missing-dataset')
    if _normalize_text(metadata.get('split')) is None:
        messages.append('missing-split')
    if _normalize_text(metadata.get('category')) is None:
        messages.append('missing-category')
    if not messages:
        validation_status = 'ready'
    elif 'missing-source' in messages:
        validation_status = 'blocked'
    else:
        validation_status = 'warning'

    content_id = _sha256_text(_canonical_json({
        'id': case_payload.get('id'),
        'mode': case_payload.get('mode'),
        'sourcePath': declared_path,
        'expectationKind': expectation_kind,
        'expectedText': expected_text,
        'timeMs': case_payload.get('timeMs'),
        'anchorTimeMs': case_payload.get('anchorTimeMs'),
        'interval': case_payload.get('interval'),
        'selectedTargetBox': case_payload.get('selectedTargetBox'),
        'selectedTargetTrackId': case_payload.get('selectedTargetTrackId'),
        'groundTruthFrames': case_payload.get('groundTruthFrames'),
        'analysisProfileId': case_payload.get('analysisProfileId') or default_profile,
        'tags': case_payload.get('tags') or [],
        'metadata': metadata,
    }))
    return BenchmarkCaseRecord(
        declared_id=str(case_payload.get('id') or ''),
        content_id=content_id,
        mode=str(case_payload.get('mode') or ''),
        analysis_profile_id=_normalize_text(case_payload.get('analysisProfileId')) or default_profile,
        tags=_normalize_string_list(case_payload.get('tags')),
        metadata=metadata,
        source=SourceReference(
            declared_path=declared_path,
            resolved_path=str(resolved_path),
            exists=exists,
            path_kind='absolute' if Path(declared_path).is_absolute() else 'relative',
            source_hash=source_hash,
        ),
        ground_truth=GroundTruth(
            expectation_kind=expectation_kind,
            expected_text=expected_text,
            frame_time_ms=_coerce_optional_int(case_payload.get('timeMs')),
            anchor_time_ms=_coerce_optional_int(case_payload.get('anchorTimeMs')),
            interval=dict(case_payload.get('interval')) if isinstance(case_payload.get('interval'), dict) else None,
            selected_target_box=dict(case_payload.get('selectedTargetBox')) if isinstance(case_payload.get('selectedTargetBox'), dict) else None,
            selected_target_track_id=_normalize_text(case_payload.get('selectedTargetTrackId')),
            ground_truth_frames=tuple(
                dict(frame)
                for frame in (case_payload.get('groundTruthFrames') or [])
                if isinstance(frame, dict)
            ),
        ),
        validation=CaseValidation(
            status=validation_status,
            messages=tuple(messages),
        ),
    )


def _coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None