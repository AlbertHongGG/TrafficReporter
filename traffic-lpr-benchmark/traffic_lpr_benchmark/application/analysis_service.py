from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .evaluation_engine import build_run_evaluation, classify_failure_attribution


def classify_failure_source(failure_reason: Any) -> str:
    return classify_failure_attribution({'failureReason': failure_reason})['family']


def build_run_analysis(bundle: dict[str, Any]) -> dict[str, Any]:
    suite = bundle.get('suite') if isinstance(bundle.get('suite'), dict) else {}
    result = bundle.get('result') if isinstance(bundle.get('result'), dict) else {}
    result_metrics = result.get('metrics') if isinstance(result.get('metrics'), dict) else {}
    cases = result.get('cases') if isinstance(result.get('cases'), list) else []

    dataset_case_counts: Counter[str] = Counter()
    dataset_exact_counts: Counter[str] = Counter()
    dataset_failure_sources: dict[str, Counter[str]] = defaultdict(Counter)

    split_case_counts: Counter[str] = Counter()
    split_exact_counts: Counter[str] = Counter()
    split_failure_sources: dict[str, Counter[str]] = defaultdict(Counter)

    category_case_counts: Counter[str] = Counter()
    category_exact_counts: Counter[str] = Counter()
    category_failure_sources: dict[str, Counter[str]] = defaultdict(Counter)
    tracking_tier_case_counts: Counter[str] = Counter()
    tracking_tier_exact_counts: Counter[str] = Counter()
    tracking_tier_failure_sources: dict[str, Counter[str]] = defaultdict(Counter)
    sequence_tier_case_counts: Counter[str] = Counter()
    sequence_tier_exact_counts: Counter[str] = Counter()
    sequence_tier_failure_sources: dict[str, Counter[str]] = defaultdict(Counter)
    review_status_case_counts: Counter[str] = Counter()
    review_status_exact_counts: Counter[str] = Counter()
    review_status_failure_sources: dict[str, Counter[str]] = defaultdict(Counter)

    failure_reason_counts: Counter[str] = Counter()
    failure_source_counts: Counter[str] = Counter()

    for case in cases:
        if not isinstance(case, dict):
            continue
        metadata = case.get('metadata') if isinstance(case.get('metadata'), dict) else {}
        dataset = str(metadata.get('dataset') or 'unknown')
        split = str(metadata.get('split') or 'unknown')
        category = str(metadata.get('category') or metadata.get('dominantCategory') or 'uncategorized')
        failure_reason = str(case.get('failureReason') or 'unknown')
        failure_source = classify_failure_source(failure_reason)
        exact_match = bool(case.get('exactMatch'))

        dataset_case_counts[dataset] += 1
        split_case_counts[split] += 1
        category_case_counts[category] += 1
        dataset_failure_sources[dataset][failure_source] += 1
        split_failure_sources[split][failure_source] += 1
        category_failure_sources[category][failure_source] += 1
        failure_reason_counts[failure_reason] += 1
        failure_source_counts[failure_source] += 1
        review_status = _review_status(case)
        review_status_case_counts[review_status] += 1
        review_status_failure_sources[review_status][failure_source] += 1

        tracking_payload = case.get('tracking') if isinstance(case.get('tracking'), dict) else None
        if tracking_payload is not None:
            tracking_tier = str(tracking_payload.get('trackingTier') or 'unknown')
            tracking_tier_case_counts[tracking_tier] += 1
            tracking_tier_failure_sources[tracking_tier][failure_source] += 1

        sequence_payload = case.get('sequence') if isinstance(case.get('sequence'), dict) else None
        if sequence_payload is not None:
            sequence_tier = str(sequence_payload.get('sequenceTier') or 'unknown')
            sequence_tier_case_counts[sequence_tier] += 1
            sequence_tier_failure_sources[sequence_tier][failure_source] += 1

        if exact_match:
            dataset_exact_counts[dataset] += 1
            split_exact_counts[split] += 1
            category_exact_counts[category] += 1
            review_status_exact_counts[review_status] += 1
            if tracking_payload is not None:
                tracking_tier_exact_counts[tracking_tier] += 1
            if sequence_payload is not None:
                sequence_tier_exact_counts[sequence_tier] += 1

    analysis = {
        'runId': bundle.get('runId'),
        'suiteId': suite.get('suiteId'),
        'suiteTitle': suite.get('title'),
        'totalCases': len(cases),
        'failureSourceBreakdown': dict(sorted(failure_source_counts.items())),
        'failureReasonBreakdown': dict(sorted(failure_reason_counts.items())),
        'datasetBreakdown': _serialize_axis_breakdown(dataset_case_counts, dataset_exact_counts, dataset_failure_sources),
        'splitBreakdown': _serialize_axis_breakdown(split_case_counts, split_exact_counts, split_failure_sources),
        'categoryBreakdown': _serialize_axis_breakdown(category_case_counts, category_exact_counts, category_failure_sources),
        'difficultyBreakdown': {
            'trackingTier': _serialize_axis_breakdown(tracking_tier_case_counts, tracking_tier_exact_counts, tracking_tier_failure_sources),
            'sequenceTier': _serialize_axis_breakdown(sequence_tier_case_counts, sequence_tier_exact_counts, sequence_tier_failure_sources),
            'reviewStatus': _serialize_axis_breakdown(review_status_case_counts, review_status_exact_counts, review_status_failure_sources),
        },
    }

    taiwan_primary = analysis['datasetBreakdown'].get('AOLP')
    moving_camera_gate = analysis['datasetBreakdown'].get('UFPR-ALPR')
    if taiwan_primary is not None or moving_camera_gate is not None:
        analysis['focusBreakdown'] = {
            'taiwanPrimary': taiwan_primary,
            'movingCameraReliability': moving_camera_gate,
        }
    fragmented_sequence = analysis['difficultyBreakdown']['sequenceTier'].get('fragmented')
    degraded_tracking = analysis['difficultyBreakdown']['trackingTier'].get('detection-fallback')
    if fragmented_sequence is not None or degraded_tracking is not None:
        analysis.setdefault('focusBreakdown', {})
        if fragmented_sequence is not None:
            analysis['focusBreakdown']['fragmentedSequence'] = fragmented_sequence
        if degraded_tracking is not None:
            analysis['focusBreakdown']['degradedTracking'] = degraded_tracking
    if any(result_metrics.get(key) is not None for key in ['acceptedUnderDegradedTrackingRate', 'detectionFallbackReviewRequiredRate', 'meanDetectionFallbackReacquireFrames']):
        analysis.setdefault('focusBreakdown', {})
        analysis['focusBreakdown']['trackingAcceptance'] = {
            'acceptedUnderDegradedTrackingRate': result_metrics.get('acceptedUnderDegradedTrackingRate'),
            'detectionFallbackReviewRequiredRate': result_metrics.get('detectionFallbackReviewRequiredRate'),
            'meanDetectionFallbackReacquireFrames': result_metrics.get('meanDetectionFallbackReacquireFrames'),
        }
    if any(result_metrics.get(key) is not None for key in ['meanAcceptedMargin', 'meanPredictionSwitchCount', 'meanSampleExactMatchRate', 'meanSequencePersistence', 'meanCharacterConsistencyMean']):
        analysis.setdefault('focusBreakdown', {})
        analysis['focusBreakdown']['hardCaseStability'] = {
            'meanAcceptedMargin': result_metrics.get('meanAcceptedMargin'),
            'meanPredictionSwitchCount': result_metrics.get('meanPredictionSwitchCount'),
            'meanSampleExactMatchRate': result_metrics.get('meanSampleExactMatchRate'),
            'meanSequencePersistence': result_metrics.get('meanSequencePersistence'),
            'meanCharacterConsistencyMean': result_metrics.get('meanCharacterConsistencyMean'),
        }

    evaluation = build_run_evaluation(bundle)
    analysis['stageBreakdown'] = dict(evaluation.get('stageBreakdown') or {})
    analysis['componentBreakdown'] = dict(evaluation.get('componentBreakdown') or {})
    analysis['datasetComponentBreakdown'] = dict(evaluation.get('datasetComponentBreakdown') or {})
    analysis['topRegressions'] = list(evaluation.get('topRegressions') or [])

    return analysis


def build_analysis_markdown(bundle: dict[str, Any], analysis: dict[str, Any]) -> str:
    lines = [
        f"# {(analysis.get('suiteTitle') or analysis.get('suiteId') or 'Benchmark Analysis')}",
        '',
        f"- Run ID: {analysis.get('runId')}",
        f"- Total cases: {analysis.get('totalCases')}",
        f"- Summary: {(bundle.get('result') or {}).get('summary') or '--'}",
        '',
        '## Dataset Focus',
        '',
    ]

    for dataset, payload in analysis.get('datasetBreakdown', {}).items():
        failure_sources = ', '.join(
            f'{name}={count}'
            for name, count in (payload.get('failureSources') or {}).items()
        ) or 'none'
        lines.append(
            f"- {dataset}: cases={payload.get('cases')}, exact={_format_rate(payload.get('exactMatchRate'))}, failureSources={failure_sources}"
        )

    lines.extend([
        '',
        '## Failure Sources',
        '',
    ])
    for name, count in analysis.get('failureSourceBreakdown', {}).items():
        lines.append(f'- {name}: {count}')

    focus_breakdown = analysis.get('focusBreakdown') if isinstance(analysis.get('focusBreakdown'), dict) else {}
    tracking_acceptance = focus_breakdown.get('trackingAcceptance') if isinstance(focus_breakdown.get('trackingAcceptance'), dict) else None
    if tracking_acceptance is not None:
        lines.extend([
            '',
            '## Tracking Acceptance Focus',
            '',
            f"- Accepted under degraded tracking: {_format_rate(tracking_acceptance.get('acceptedUnderDegradedTrackingRate'))}",
            f"- Detection-fallback review required: {_format_rate(tracking_acceptance.get('detectionFallbackReviewRequiredRate'))}",
            f"- Detection-fallback mean reacquire frames: {tracking_acceptance.get('meanDetectionFallbackReacquireFrames') if isinstance(tracking_acceptance.get('meanDetectionFallbackReacquireFrames'), (int, float)) else '--'}",
        ])
    hard_case_stability = focus_breakdown.get('hardCaseStability') if isinstance(focus_breakdown.get('hardCaseStability'), dict) else None
    if hard_case_stability is not None:
        lines.extend([
            '',
            '## Hard-Case Stability Focus',
            '',
            f"- Mean accepted margin: {_format_number(hard_case_stability.get('meanAcceptedMargin'))}",
            f"- Mean prediction switches: {_format_number(hard_case_stability.get('meanPredictionSwitchCount'))}",
            f"- Mean sample exact match rate: {_format_rate(hard_case_stability.get('meanSampleExactMatchRate'))}",
            f"- Mean sequence persistence: {_format_rate(hard_case_stability.get('meanSequencePersistence'))}",
            f"- Mean character consistency: {_format_number(hard_case_stability.get('meanCharacterConsistencyMean'))}",
        ])

    lines.extend([
        '',
        '## Difficulty Focus',
        '',
    ])
    difficulty_breakdown = analysis.get('difficultyBreakdown') if isinstance(analysis.get('difficultyBreakdown'), dict) else {}
    for axis_name, axis_breakdown in difficulty_breakdown.items():
        lines.append(f'### {axis_name}')
        lines.append('')
        if not axis_breakdown:
            lines.append('- none')
            lines.append('')
            continue
        for axis_value, payload in axis_breakdown.items():
            failure_sources = ', '.join(
                f'{name}={count}'
                for name, count in (payload.get('failureSources') or {}).items()
            ) or 'none'
            lines.append(
                f"- {axis_value}: cases={payload.get('cases')}, exact={_format_rate(payload.get('exactMatchRate'))}, failureSources={failure_sources}"
            )
        lines.append('')

    lines.extend([
        '',
        '## Failure Components',
        '',
    ])
    for name, count in analysis.get('componentBreakdown', {}).items():
        lines.append(f'- {name}: {count}')

    lines.extend([
        '',
        '## Category Coverage',
        '',
    ])
    for category, payload in analysis.get('categoryBreakdown', {}).items():
        failure_sources = ', '.join(
            f'{name}={count}'
            for name, count in (payload.get('failureSources') or {}).items()
        ) or 'none'
        lines.append(
            f"- {category}: cases={payload.get('cases')}, exact={_format_rate(payload.get('exactMatchRate'))}, failureSources={failure_sources}"
        )

    regressions = analysis.get('topRegressions') or []
    lines.extend([
        '',
        '## Top Regressions',
        '',
    ])
    if not regressions:
        lines.append('- none')
    else:
        for row in regressions:
            lines.append(
                '- {id}: dataset={dataset}, category={category}, failure={failure}, component={component}, best={best}'.format(
                    id=row.get('id') or '--',
                    dataset=row.get('dataset') or 'unknown',
                    category=row.get('category') or 'uncategorized',
                    failure=row.get('failureReason') or 'unknown',
                    component=row.get('component') or 'unknown',
                    best=row.get('bestText') or '--',
                )
            )

    return '\n'.join(lines) + '\n'


def _serialize_axis_breakdown(
    case_counts: Counter[str],
    exact_counts: Counter[str],
    failure_sources: dict[str, Counter[str]],
) -> dict[str, dict[str, Any]]:
    serialized: dict[str, dict[str, Any]] = {}
    for axis_value in sorted(case_counts):
        total_cases = case_counts[axis_value]
        serialized[axis_value] = {
            'cases': total_cases,
            'exactMatchRate': exact_counts[axis_value] / total_cases if total_cases else 0.0,
            'failureSources': dict(sorted(failure_sources[axis_value].items())),
        }
    return serialized


def _format_rate(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return '--'
    return f'{value * 100:.1f}%'


def _format_number(value: Any, digits: int = 3) -> str:
    if not isinstance(value, (int, float)):
        return '--'
    return f'{float(value):.{digits}f}'


def _review_status(case_payload: dict[str, Any]) -> str:
    review_payload = case_payload.get('review') if isinstance(case_payload.get('review'), dict) else {}
    status = str(review_payload.get('status') or 'unknown').strip()
    return status or 'unknown'