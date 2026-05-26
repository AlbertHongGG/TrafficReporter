from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from registry import BenchmarkSuiteRegistry, summarize_suite_registry


@dataclass(slots=True, frozen=True)
class BenchmarkCaseLedgerEntry:
    declared_id: str
    content_id: str
    mode: str
    dataset: str
    split: str
    category: str
    source_hash: str | None
    expectation_kind: str
    expected_text: str | None
    best_text: str | None
    exact_match: bool | None
    top3_match: bool | None
    character_error_rate: float | None
    accepted_confidence: float | None
    latency_ms: float | None
    failure_reason: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            'declaredId': self.declared_id,
            'contentId': self.content_id,
            'mode': self.mode,
            'dataset': self.dataset,
            'split': self.split,
            'category': self.category,
            'sourceHash': self.source_hash,
            'expectationKind': self.expectation_kind,
            'expectedText': self.expected_text,
            'bestText': self.best_text,
            'exactMatch': self.exact_match,
            'top3Match': self.top3_match,
            'characterErrorRate': self.character_error_rate,
            'acceptedConfidence': self.accepted_confidence,
            'latencyMs': self.latency_ms,
            'failureReason': self.failure_reason,
        }


def build_run_ledger(
    run_id: str,
    generated_at: str,
    suite_registry: BenchmarkSuiteRegistry,
    runtime_result: dict[str, Any],
) -> dict[str, Any]:
    case_results = runtime_result.get('cases') if isinstance(runtime_result.get('cases'), list) else []
    results_by_id = {
        str(case.get('id') or ''): case
        for case in case_results
        if isinstance(case, dict) and isinstance(case.get('id'), str)
    }
    entries = [
        _build_case_ledger_entry(case, results_by_id.get(case.declared_id))
        for case in suite_registry.cases
    ]
    registry_summary = summarize_suite_registry(suite_registry)
    missing_results = sum(1 for case in suite_registry.cases if case.declared_id not in results_by_id)
    completed_results = len(entries) - missing_results

    return {
        'runId': run_id,
        'generatedAt': generated_at,
        'suiteId': suite_registry.suite_id,
        'suiteHash': suite_registry.suite_hash,
        'analysisProfileId': suite_registry.analysis_profile_id,
        'caseCount': len(entries),
        'completedCaseCount': completed_results,
        'missingResultCount': missing_results,
        'sourceIntegrity': registry_summary['sourceIntegrity'],
        'validationCounts': registry_summary['validationCounts'],
        'cases': [entry.to_payload() for entry in entries],
    }


def _build_case_ledger_entry(case: Any, result_payload: dict[str, Any] | None) -> BenchmarkCaseLedgerEntry:
    metadata = case.metadata
    return BenchmarkCaseLedgerEntry(
        declared_id=case.declared_id,
        content_id=case.content_id,
        mode=case.mode,
        dataset=str(metadata.get('dataset') or 'unknown'),
        split=str(metadata.get('split') or 'unknown'),
        category=str(metadata.get('category') or 'uncategorized'),
        source_hash=case.source.source_hash,
        expectation_kind=case.ground_truth.expectation_kind,
        expected_text=case.ground_truth.expected_text,
        best_text=_coerce_optional_str(result_payload.get('bestText') if isinstance(result_payload, dict) else None),
        exact_match=_coerce_optional_bool(result_payload.get('exactMatch') if isinstance(result_payload, dict) else None),
        top3_match=_coerce_optional_bool(result_payload.get('top3Match') if isinstance(result_payload, dict) else None),
        character_error_rate=_coerce_optional_float(result_payload.get('characterErrorRate') if isinstance(result_payload, dict) else None),
        accepted_confidence=_coerce_optional_float(result_payload.get('acceptedConfidence') if isinstance(result_payload, dict) else None),
        latency_ms=_coerce_optional_float(result_payload.get('latencyMs') if isinstance(result_payload, dict) else None),
        failure_reason=_coerce_optional_str(result_payload.get('failureReason') if isinstance(result_payload, dict) else None),
    )


def _coerce_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _coerce_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None