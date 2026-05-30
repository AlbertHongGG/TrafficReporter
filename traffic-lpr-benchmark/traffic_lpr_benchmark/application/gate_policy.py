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
        'minMeanTrackingCoverageRatio': _coerce_optional_float(getattr(args, 'min_mean_tracking_coverage_ratio', None)),
        'maxDegradedTrackingRate': _coerce_optional_float(getattr(args, 'max_degraded_tracking_rate', None)),
        'minAcceptedUnderDegradedTrackingRate': _coerce_optional_float(getattr(args, 'min_accepted_under_degraded_tracking_rate', None)),
        'maxDetectionFallbackReviewRequiredRate': _coerce_optional_float(getattr(args, 'max_detection_fallback_review_required_rate', None)),
        'minMeanDecisionAgreementRatio': _coerce_optional_float(getattr(args, 'min_mean_decision_agreement_ratio', None)),
        'minMeanDecisionSupportFrameCount': _coerce_optional_float(getattr(args, 'min_mean_decision_support_frame_count', None)),
        'minTemporalDecisionRate': _coerce_optional_float(getattr(args, 'min_temporal_decision_rate', None)),
        'minMultiFrameDecisionRate': _coerce_optional_float(getattr(args, 'min_multi_frame_decision_rate', None)),
        'maxP95LatencyMs': _coerce_optional_float(getattr(args, 'max_p95_latency_ms', None)),
        'maxP95TrackingMs': _coerce_optional_float(getattr(args, 'max_p95_tracking_ms', None)),
        'maxP95SampleAnalysisMs': _coerce_optional_float(getattr(args, 'max_p95_sample_analysis_ms', None)),
        'maxP95TemporalSupportMs': _coerce_optional_float(getattr(args, 'max_p95_temporal_support_ms', None)),
        'maxP95FusionMs': _coerce_optional_float(getattr(args, 'max_p95_fusion_ms', None)),
        'maxP95RuntimeTotalMs': _coerce_optional_float(getattr(args, 'max_p95_runtime_total_ms', None)),
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
    tracking_case_count = _coerce_optional_int(metrics.get('intervalTrackingCaseCount'))
    _append_min_check(
        checks,
        'meanTrackingCoverageRatio',
        metrics.get('meanTrackingCoverageRatio'),
        thresholds.get('minMeanTrackingCoverageRatio'),
        sample_size=tracking_case_count,
    )
    _append_max_check(
        checks,
        'degradedTrackingRate',
        metrics.get('degradedTrackingRate'),
        thresholds.get('maxDegradedTrackingRate'),
        sample_size=tracking_case_count,
    )
    degraded_tracking_case_count = _degraded_tracking_case_count(cases)
    detection_fallback_case_count = _tracking_tier_case_count(cases, 'detection-fallback')
    _append_min_check(
        checks,
        'acceptedUnderDegradedTrackingRate',
        metrics.get('acceptedUnderDegradedTrackingRate'),
        thresholds.get('minAcceptedUnderDegradedTrackingRate'),
        sample_size=degraded_tracking_case_count,
    )
    _append_max_check(
        checks,
        'detectionFallbackReviewRequiredRate',
        metrics.get('detectionFallbackReviewRequiredRate'),
        thresholds.get('maxDetectionFallbackReviewRequiredRate'),
        sample_size=detection_fallback_case_count,
    )
    decision_case_count = _coerce_optional_int(metrics.get('decisionCaseCount'))
    _append_min_check(
        checks,
        'meanDecisionAgreementRatio',
        metrics.get('meanDecisionAgreementRatio'),
        thresholds.get('minMeanDecisionAgreementRatio'),
        sample_size=decision_case_count,
    )
    _append_min_check(
        checks,
        'meanDecisionSupportFrameCount',
        metrics.get('meanDecisionSupportFrameCount'),
        thresholds.get('minMeanDecisionSupportFrameCount'),
        sample_size=decision_case_count,
    )
    _append_min_check(
        checks,
        'temporalDecisionRate',
        metrics.get('temporalDecisionRate'),
        thresholds.get('minTemporalDecisionRate'),
        sample_size=decision_case_count,
    )
    _append_min_check(
        checks,
        'multiFrameDecisionRate',
        metrics.get('multiFrameDecisionRate'),
        thresholds.get('minMultiFrameDecisionRate'),
        sample_size=decision_case_count,
    )
    latency_payload = metrics.get('latencyMs') if isinstance(metrics.get('latencyMs'), dict) else {}
    _append_max_check(checks, 'p95LatencyMs', latency_payload.get('p95'), thresholds.get('maxP95LatencyMs'), sample_size=total_cases)
    stage_timing_payload = metrics.get('stageTimingMs') if isinstance(metrics.get('stageTimingMs'), dict) else {}
    _append_stage_p95_check(checks, stage_timing_payload, 'trackingMs', thresholds.get('maxP95TrackingMs'), total_cases)
    _append_stage_p95_check(checks, stage_timing_payload, 'sampleAnalysisMs', thresholds.get('maxP95SampleAnalysisMs'), total_cases)
    _append_stage_p95_check(checks, stage_timing_payload, 'temporalSupportMs', thresholds.get('maxP95TemporalSupportMs'), total_cases)
    _append_stage_p95_check(checks, stage_timing_payload, 'fusionMs', thresholds.get('maxP95FusionMs'), total_cases)
    _append_stage_p95_check(checks, stage_timing_payload, 'totalMs', thresholds.get('maxP95RuntimeTotalMs'), total_cases)

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


def _append_stage_p95_check(
    checks: list[dict[str, Any]],
    stage_timing_payload: dict[str, Any],
    timing_key: str,
    maximum: float | None,
    sample_size: int | None,
) -> None:
    if maximum is None:
        return
    timing_summary = stage_timing_payload.get(timing_key)
    actual = timing_summary.get('p95') if isinstance(timing_summary, dict) else None
    metric_name = f'p95{timing_key[0].upper()}{timing_key[1:]}'
    _append_max_check(checks, metric_name, actual, maximum, sample_size=sample_size)


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


def _degraded_tracking_case_count(cases: list[Any]) -> int | None:
    if not cases:
        return None
    count = 0
    for case in cases:
        if not isinstance(case, dict):
            continue
        tracking_payload = case.get('tracking')
        if not isinstance(tracking_payload, dict):
            continue
        tracking_tier = str(tracking_payload.get('trackingTier') or 'unknown')
        if tracking_tier != 'full':
            count += 1
    return count


def _tracking_tier_case_count(cases: list[Any], tracking_tier: str) -> int | None:
    if not cases:
        return None
    count = 0
    for case in cases:
        if not isinstance(case, dict):
            continue
        tracking_payload = case.get('tracking')
        if not isinstance(tracking_payload, dict):
            continue
        if str(tracking_payload.get('trackingTier') or 'unknown') == tracking_tier:
            count += 1
    return count


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