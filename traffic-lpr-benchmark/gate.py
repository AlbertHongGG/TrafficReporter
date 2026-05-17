from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_gate_thresholds(args: Any) -> dict[str, float | None]:
    return {
        'minExactRate': _coerce_optional_float(getattr(args, 'min_exact_rate', None)),
        'minTop3Rate': _coerce_optional_float(getattr(args, 'min_top3_rate', None)),
        'maxMeanCer': _coerce_optional_float(getattr(args, 'max_mean_cer', None)),
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

    _append_min_check(checks, 'exactMatchRate', metrics.get('exactMatchRate'), thresholds.get('minExactRate'))
    _append_min_check(checks, 'top3MatchRate', metrics.get('top3MatchRate'), thresholds.get('minTop3Rate'))
    _append_max_check(checks, 'meanCharacterErrorRate', metrics.get('meanCharacterErrorRate'), thresholds.get('maxMeanCer'))
    _append_min_check(checks, 'meanPlateIoU', _mean_case_metric(cases, 'localization', 'plateMeanIoU'), thresholds.get('minPlateIou'))
    latency_payload = metrics.get('latencyMs') if isinstance(metrics.get('latencyMs'), dict) else {}
    _append_max_check(checks, 'p95LatencyMs', latency_payload.get('p95'), thresholds.get('maxP95LatencyMs'))

    return {
        'passed': all(check['passed'] for check in checks),
        'checks': checks,
        'thresholds': {key: value for key, value in thresholds.items() if value is not None},
    }


def write_gate_result(path: Path, gate_result: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(gate_result, indent=2), encoding='utf-8')
    return str(path.resolve())


def _append_min_check(checks: list[dict[str, Any]], name: str, actual: Any, minimum: float | None) -> None:
    if minimum is None:
        return
    actual_value = _coerce_optional_float(actual)
    passed = actual_value is not None and actual_value >= minimum
    checks.append({
        'metric': name,
        'operator': '>=',
        'expected': minimum,
        'actual': actual_value,
        'passed': passed,
    })


def _append_max_check(checks: list[dict[str, Any]], name: str, actual: Any, maximum: float | None) -> None:
    if maximum is None:
        return
    actual_value = _coerce_optional_float(actual)
    passed = actual_value is not None and actual_value <= maximum
    checks.append({
        'metric': name,
        'operator': '<=',
        'expected': maximum,
        'actual': actual_value,
        'passed': passed,
    })


def _mean_case_metric(cases: list[Any], parent_key: str, value_key: str) -> float | None:
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
    if not values:
        return None
    return sum(values) / len(values)


def _coerce_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None