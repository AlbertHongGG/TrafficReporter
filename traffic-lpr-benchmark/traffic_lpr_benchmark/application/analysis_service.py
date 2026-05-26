from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .evaluation_engine import build_run_evaluation, classify_failure_attribution


def classify_failure_source(failure_reason: Any) -> str:
    return classify_failure_attribution({'failureReason': failure_reason})['family']


def build_run_analysis(bundle: dict[str, Any]) -> dict[str, Any]:
    suite = bundle.get('suite') if isinstance(bundle.get('suite'), dict) else {}
    result = bundle.get('result') if isinstance(bundle.get('result'), dict) else {}
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

        if exact_match:
            dataset_exact_counts[dataset] += 1
            split_exact_counts[split] += 1
            category_exact_counts[category] += 1

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
    }

    taiwan_primary = analysis['datasetBreakdown'].get('AOLP')
    moving_camera_gate = analysis['datasetBreakdown'].get('UFPR-ALPR')
    if taiwan_primary is not None or moving_camera_gate is not None:
        analysis['focusBreakdown'] = {
            'taiwanPrimary': taiwan_primary,
            'movingCameraReliability': moving_camera_gate,
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