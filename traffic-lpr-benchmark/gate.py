from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_gate_thresholds(args: Any) -> dict[str, float | None]:
    return {
        'minExactRate': _coerce_optional_float(getattr(args, 'min_exact_rate', None)),
        'minTop3Rate': _coerce_optional_float(getattr(args, 'min_top3_rate', None)),
        'maxMeanCer': _coerce_optional_float(getattr(args, 'max_mean_cer', None)),
        'maxReviewRequiredRate': _coerce_optional_float(getattr(args, 'max_review_required_rate', None)),
        'maxNoCandidateRate': _coerce_optional_float(getattr(args, 'max_no_candidate_rate', None)),
        'minPlateIou': _coerce_optional_float(getattr(args, 'min_plate_iou', None)),
        'maxP95LatencyMs': _coerce_optional_float(getattr(args, 'max_p95_latency_ms', None)),
    }


def evaluate_runtime_result_gate(
    runtime_result: dict[str, Any],
    thresholds: dict[str, float | None],
) -> dict[str, Any] | None:
    if not any(value is not None for value in thresholds.values()):
        return None

    metrics = runtime_result.get('metrics') if isinstance(runtime_result.get('metrics'), dict) else {}
    cases = runtime_result.get('cases') if isinstance(runtime_result.get('cases'), list) else []
    checks: list[dict[str, Any]] = []
    total_cases = _coerce_optional_int(metrics.get('totalCases')) or len(cases)

    _append_min_check(checks, 'exactMatchRate', metrics.get('exactMatchRate'), thresholds.get('minExactRate'), sample_size=total_cases)
    _append_min_check(checks, 'top3MatchRate', metrics.get('top3MatchRate'), thresholds.get('minTop3Rate'), sample_size=total_cases)
    _append_max_check(checks, 'meanCharacterErrorRate', metrics.get('meanCharacterErrorRate'), thresholds.get('maxMeanCer'))
    _append_max_check(
        checks,
        'reviewRequiredRate',
        _review_status_rate(metrics, cases, 'review-required'),
        thresholds.get('maxReviewRequiredRate'),
        sample_size=total_cases,
    )
    _append_max_check(
        checks,
        'noCandidateRate',
        _review_status_rate(metrics, cases, 'no-candidate'),
        thresholds.get('maxNoCandidateRate'),
        sample_size=total_cases,
    )
    plate_iou_values = _case_metric_values(cases, 'localization', 'plateMeanIoU')
    _append_min_check(checks, 'meanPlateIoU', _mean_values(plate_iou_values), thresholds.get('minPlateIou'), sample_size=len(plate_iou_values))
    latency_payload = metrics.get('latencyMs') if isinstance(metrics.get('latencyMs'), dict) else {}
    _append_max_check(checks, 'p95LatencyMs', latency_payload.get('p95'), thresholds.get('maxP95LatencyMs'), sample_size=total_cases)

    return {
        'passed': all(check['passed'] for check in checks),
        'checks': checks,
        'thresholds': {key: value for key, value in thresholds.items() if value is not None},
    }


def write_gate_result(path: Path, gate_result: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(gate_result, indent=2), encoding='utf-8')
    return str(path.resolve())


def _append_min_check(
    checks: list[dict[str, Any]],
    name: str,
    actual: Any,
    minimum: float | None,
    *,
    sample_size: int | None = None,
) -> None:
    if minimum is None:
        return
    actual_value = _coerce_optional_float(actual)
    passed = actual_value is not None and actual_value >= minimum
    check = {
        'metric': name,
        'operator': '>=',
        'expected': minimum,
        'actual': actual_value,
        'passed': passed,
    }
    if sample_size is not None:
        check['sampleSize'] = sample_size
        if sample_size < 5:
            check['advisory'] = 'low-sample-size'
    checks.append(check)


def _append_max_check(
    checks: list[dict[str, Any]],
    name: str,
    actual: Any,
    maximum: float | None,
    *,
    sample_size: int | None = None,
) -> None:
    if maximum is None:
        return
    actual_value = _coerce_optional_float(actual)
    passed = actual_value is not None and actual_value <= maximum
    check = {
        'metric': name,
        'operator': '<=',
        'expected': maximum,
        'actual': actual_value,
        'passed': passed,
    }
    if sample_size is not None:
        check['sampleSize'] = sample_size
        if sample_size < 5:
            check['advisory'] = 'low-sample-size'
    checks.append(check)


def _mean_case_metric(cases: list[Any], parent_key: str, value_key: str) -> float | None:
    values = _case_metric_values(cases, parent_key, value_key)
    return _mean_values(values)


def _case_metric_values(cases: list[Any], parent_key: str, value_key: str) -> list[float]:
    values: list[float] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        parent = case.get(parent_key)
        if not isinstance(parent, dict):
            continue
        value = _coerce_optional_float(parent.get(value_key))
        if value is not None:
            values.append(value)
    return values


def _mean_values(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _review_status_rate(metrics: dict[str, Any], cases: list[Any], status: str) -> float | None:
    metric_name = {
        'accepted': 'acceptedRate',
        'review-required': 'reviewRequiredRate',
        'no-candidate': 'noCandidateRate',
    }.get(status)
    if metric_name is not None:
        metric_value = _coerce_optional_float(metrics.get(metric_name))
        if metric_value is not None:
            return metric_value

    if not cases:
        return None

    matched = 0
    observed = 0
    for case in cases:
        normalized_status = _case_review_status(case)
        if normalized_status is None:
            continue
        observed += 1
        matched += 1 if normalized_status == status else 0
    if observed == 0:
        return None
    return matched / observed


def _case_review_status(case: Any) -> str | None:
    if not isinstance(case, dict):
        return None
    review_payload = case.get('review')
    if not isinstance(review_payload, dict):
        raise ValueError('Benchmark case is missing review payload.')

    status = str(review_payload.get('status') or '').strip()
    if status not in {'accepted', 'review-required', 'no-candidate'}:
        raise ValueError(f'Unsupported review status: {status!r}')
    return status


def _coerce_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None