from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from ..domain.models import format_case_expectation
from .case_registry_service import BenchmarkSuiteRegistry
from .run_ledger_service import build_run_ledger


def classify_failure_attribution(case_payload: dict[str, Any]) -> dict[str, str]:
    failure_reason = str(case_payload.get('failureReason') or 'unknown')
    if failure_reason == 'correct':
        return {
            'stage': 'correct',
            'component': 'correct',
            'family': 'correct',
        }
    if failure_reason == 'target-missed':
        return {
            'stage': 'detection',
            'component': 'target-detector',
            'family': 'localization',
        }
    if failure_reason == 'plate-localization-missed':
        return {
            'stage': 'localization',
            'component': 'plate-localizer',
            'family': 'localization',
        }
    if failure_reason == 'fusion-unstable':
        return {
            'stage': 'temporal',
            'component': 'fusion',
            'family': 'tracking',
        }
    return {
        'stage': 'recognition',
        'component': 'ocr',
        'family': 'ocr',
    }


def build_run_evaluation(
    bundle: dict[str, Any],
    suite_registry: BenchmarkSuiteRegistry | None = None,
) -> dict[str, Any]:
    suite = bundle.get('suite') if isinstance(bundle.get('suite'), dict) else {}
    result = bundle.get('result') if isinstance(bundle.get('result'), dict) else {}
    cases = result.get('cases') if isinstance(result.get('cases'), list) else []
    stage_counts: Counter[str] = Counter()
    component_counts: Counter[str] = Counter()
    family_counts: Counter[str] = Counter()
    review_counts: Counter[str] = Counter()
    review_reason_counts: Counter[str] = Counter()
    dataset_component_breakdown: dict[str, Counter[str]] = defaultdict(Counter)
    dataset_review_breakdown: dict[str, Counter[str]] = defaultdict(Counter)
    top_regressions: list[dict[str, Any]] = []

    for case in cases:
        if not isinstance(case, dict):
            continue
        attribution = classify_failure_attribution(case)
        metadata = case.get('metadata') if isinstance(case.get('metadata'), dict) else {}
        dataset = str(metadata.get('dataset') or 'unknown')
        review_status = _case_review_status(case)
        review_reasons = _case_review_reasons(case, review_status)
        stage_counts[attribution['stage']] += 1
        component_counts[attribution['component']] += 1
        family_counts[attribution['family']] += 1
        review_counts[review_status] += 1
        for reason in review_reasons:
            review_reason_counts[reason] += 1
        dataset_component_breakdown[dataset][attribution['component']] += 1
        dataset_review_breakdown[dataset][review_status] += 1

        if not bool(case.get('exactMatch')):
            top_regressions.append({
                'id': case.get('id'),
                'dataset': dataset,
                'category': metadata.get('category') or metadata.get('dominantCategory') or 'uncategorized',
                'expectationKind': case.get('expectationKind') or 'readable',
                'expectedText': case.get('expectedText'),
                'expectedDisplay': format_case_expectation(str(case.get('expectationKind') or 'readable'), case.get('expectedText')),
                'bestText': case.get('bestText'),
                'failureReason': case.get('failureReason'),
                'stage': attribution['stage'],
                'component': attribution['component'],
                'reviewStatus': review_status,
                'reviewReasons': review_reasons,
                'latencyMs': _coerce_optional_float(case.get('latencyMs')),
                'characterErrorRate': _coerce_optional_float(case.get('characterErrorRate')),
            })

    top_regressions.sort(
        key=lambda row: (
            -(row.get('characterErrorRate') or 0.0),
            -(row.get('latencyMs') or 0.0),
            str(row.get('id') or ''),
        )
    )
    evaluation = {
        'runId': bundle.get('runId'),
        'suiteId': suite.get('suiteId'),
        'suiteTitle': suite.get('title'),
        'totalCases': len(cases),
        'stageBreakdown': dict(sorted(stage_counts.items())),
        'componentBreakdown': dict(sorted(component_counts.items())),
        'familyBreakdown': dict(sorted(family_counts.items())),
        'reviewBreakdown': dict(sorted(review_counts.items())),
        'reviewReasonBreakdown': dict(sorted(review_reason_counts.items())),
        'datasetComponentBreakdown': {
            dataset: dict(sorted(counts.items()))
            for dataset, counts in sorted(dataset_component_breakdown.items())
        },
        'datasetReviewBreakdown': {
            dataset: dict(sorted(counts.items()))
            for dataset, counts in sorted(dataset_review_breakdown.items())
        },
        'topRegressions': top_regressions[:10],
    }
    if suite_registry is not None:
        evaluation['registry'] = {
            'suiteHash': suite_registry.suite_hash,
            'caseCount': len(suite_registry.cases),
            'warnings': list(suite_registry.warnings),
            'sourceIntegrity': build_run_ledger(
                run_id=str(bundle.get('runId') or ''),
                generated_at=str(bundle.get('generatedAt') or ''),
                suite_registry=suite_registry,
                runtime_result=result,
            )['sourceIntegrity'],
        }
    return evaluation


def build_evaluation_markdown(evaluation: dict[str, Any]) -> str:
    lines = [
        f"# {(evaluation.get('suiteTitle') or evaluation.get('suiteId') or 'Benchmark Evaluation')}",
        '',
        f"- Run ID: {evaluation.get('runId')}",
        f"- Total cases: {evaluation.get('totalCases')}",
        '',
        '## Failure Stages',
        '',
    ]
    for stage, count in (evaluation.get('stageBreakdown') or {}).items():
        lines.append(f'- {stage}: {count}')

    lines.extend([
        '',
        '## Components',
        '',
    ])
    for component, count in (evaluation.get('componentBreakdown') or {}).items():
        lines.append(f'- {component}: {count}')

    lines.extend([
        '',
        '## Review States',
        '',
    ])
    for status, count in (evaluation.get('reviewBreakdown') or {}).items():
        lines.append(f'- {status}: {count}')

    review_reason_breakdown = evaluation.get('reviewReasonBreakdown') or {}
    if review_reason_breakdown:
        lines.extend([
            '',
            '## Review Reasons',
            '',
        ])
        for reason, count in review_reason_breakdown.items():
            lines.append(f'- {reason}: {count}')

    lines.extend([
        '',
        '## Top Regressions',
        '',
    ])
    regressions = evaluation.get('topRegressions') or []
    if not regressions:
        lines.append('- none')
    else:
        for row in regressions:
            lines.append(
                '- {id}: dataset={dataset}, category={category}, expected={expected}, failure={failure}, stage={stage}, component={component}, best={best}'.format(
                    id=row.get('id') or '--',
                    dataset=row.get('dataset') or 'unknown',
                    category=row.get('category') or 'uncategorized',
                    expected=row.get('expectedDisplay') or '--',
                    failure=row.get('failureReason') or 'unknown',
                    stage=row.get('stage') or 'unknown',
                    component=row.get('component') or 'unknown',
                    best=f"{row.get('bestText') or '--'}, review={row.get('reviewStatus') or 'unknown'}",
                )
            )

    registry_payload = evaluation.get('registry') if isinstance(evaluation.get('registry'), dict) else None
    if registry_payload is not None:
        lines.extend([
            '',
            '## Registry',
            '',
            f"- Suite hash: {registry_payload.get('suiteHash') or '--'}",
            f"- Warnings: {', '.join(registry_payload.get('warnings') or []) or 'none'}",
        ])

    return '\n'.join(lines) + '\n'


def _coerce_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _case_review_status(case_payload: dict[str, Any]) -> str:
    review_payload = case_payload.get('review')
    if not isinstance(review_payload, dict):
        raise ValueError('Benchmark case is missing review payload.')

    status = str(review_payload.get('status') or '').strip()
    if status not in {'accepted', 'review-required', 'no-candidate'}:
        raise ValueError(f'Unsupported review status: {status!r}')
    return status


def _case_review_reasons(case_payload: dict[str, Any], review_status: str) -> list[str]:
    review_payload = case_payload.get('review')
    if not isinstance(review_payload, dict):
        raise ValueError('Benchmark case is missing review payload.')

    reasons = [
        str(reason)
        for reason in review_payload.get('reasons') or []
        if isinstance(reason, str) and reason
    ]
    if reasons:
        return reasons
    return ['no-candidate'] if review_status == 'no-candidate' else []