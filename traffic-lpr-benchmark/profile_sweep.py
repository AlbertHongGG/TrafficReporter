from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


def apply_analysis_profile_to_suite(suite_payload: dict[str, Any], profile_id: str) -> dict[str, Any]:
    cloned_payload = copy.deepcopy(suite_payload)
    cloned_payload['analysisProfileId'] = profile_id
    for case in cloned_payload.get('cases') or []:
        if isinstance(case, dict):
            case['analysisProfileId'] = profile_id
    return cloned_payload


def build_profile_sweep_payload(
    comparison_id: str,
    suite_payload: dict[str, Any],
    profile_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        'comparisonId': comparison_id,
        'suiteId': suite_payload.get('suiteId'),
        'suiteTitle': suite_payload.get('title'),
        'profiles': profile_runs,
    }


def build_profile_sweep_markdown(payload: dict[str, Any]) -> str:
    profile_ids = [
        str(entry.get('profileId'))
        for entry in payload.get('profiles') or []
        if isinstance(entry, dict)
    ]
    lines = [
        f"# {(payload.get('suiteTitle') or payload.get('suiteId') or 'Profile Sweep')}",
        '',
        f"- Comparison ID: {payload.get('comparisonId')}",
        f"- Profiles: {', '.join(profile_ids)}",
        '',
        '## Profile Comparison',
        '',
    ]

    for entry in payload.get('profiles') or []:
        if not isinstance(entry, dict):
            continue
        failure_sources = ', '.join(
            f'{name}={count}'
            for name, count in (entry.get('failureSources') or {}).items()
        ) or 'none'
        gate_status = '--'
        if entry.get('gatePassed') is True:
            gate_status = 'pass'
        elif entry.get('gatePassed') is False:
            gate_status = 'fail'
        lines.append(
            '- '
            f"{entry.get('profileId')}: exact={_format_rate(entry.get('exactMatchRate'))}, "
            f"top3={_format_rate(entry.get('top3MatchRate'))}, "
            f"cer={_format_number(entry.get('meanCharacterErrorRate'))}, "
            f"plateIoU={_format_number(entry.get('meanPlateIoU'))}, "
            f"p95={_format_number(entry.get('p95LatencyMs'), 1)}ms, "
            f"margin={_format_number(entry.get('meanAcceptedMargin'))}, "
            f"gate={gate_status}, "
            f"failureSources={failure_sources}"
        )

    return '\n'.join(lines) + '\n'


def write_profile_sweep_artifacts(report_root: Path, comparison_payload: dict[str, Any]) -> dict[str, str]:
    report_root.mkdir(parents=True, exist_ok=True)
    comparison_id = str(comparison_payload.get('comparisonId') or 'profile-sweep')
    json_path = report_root / f'{comparison_id}.profile-sweep.json'
    markdown_path = report_root / f'{comparison_id}.profile-sweep.md'
    json_path.write_text(json.dumps(comparison_payload, indent=2), encoding='utf-8')
    markdown_path.write_text(build_profile_sweep_markdown(comparison_payload), encoding='utf-8')
    return {
        'comparisonJson': str(json_path.resolve()),
        'comparisonMarkdown': str(markdown_path.resolve()),
    }


def summarize_profile_run(
    profile_id: str,
    run_id: str,
    runtime_result: dict[str, Any],
    analysis_payload: dict[str, Any],
    artifact_paths: dict[str, str],
    gate_result: dict[str, Any] | None,
) -> dict[str, Any]:
    metrics = runtime_result.get('metrics') if isinstance(runtime_result.get('metrics'), dict) else {}
    latency_payload = metrics.get('latencyMs') if isinstance(metrics.get('latencyMs'), dict) else {}
    return {
        'profileId': profile_id,
        'runId': run_id,
        'summary': runtime_result.get('summary'),
        'exactMatchRate': metrics.get('exactMatchRate'),
        'top3MatchRate': metrics.get('top3MatchRate'),
        'meanCharacterErrorRate': metrics.get('meanCharacterErrorRate'),
        'meanAcceptedMargin': metrics.get('meanAcceptedMargin'),
        'meanPlateIoU': _mean_case_metric(runtime_result.get('cases') or [], 'localization', 'plateMeanIoU'),
        'p95LatencyMs': latency_payload.get('p95'),
        'failureSources': analysis_payload.get('failureSourceBreakdown') or {},
        'datasetBreakdown': analysis_payload.get('datasetBreakdown') or {},
        'gatePassed': gate_result.get('passed') if isinstance(gate_result, dict) else None,
        'artifacts': artifact_paths,
    }


def _mean_case_metric(cases: list[Any], parent_key: str, value_key: str) -> float | None:
    values: list[float] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        parent = case.get(parent_key)
        if not isinstance(parent, dict):
            continue
        value = parent.get(value_key)
        if isinstance(value, (int, float)):
            values.append(float(value))
    if not values:
        return None
    return sum(values) / len(values)


def _format_rate(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return '--'
    return f'{value * 100:.1f}%'


def _format_number(value: Any, digits: int = 3) -> str:
    if not isinstance(value, (int, float)):
        return '--'
    return f'{value:.{digits}f}'