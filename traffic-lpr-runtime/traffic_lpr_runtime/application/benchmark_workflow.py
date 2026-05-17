from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from traffic_lpr_runtime.domain.text import character_error_rate, normalize_plate_text
from traffic_lpr_runtime.domain.value_objects import NormalizedRect


class BenchmarkRunWorkflow:
    def __init__(
        self,
        ensure_ready: Callable[[], None],
        status: Callable[[], dict[str, Any]],
        analyze_frame: Callable[[dict[str, Any]], dict[str, Any]],
        analyze_interval: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        self._ensure_ready = ensure_ready
        self._status = status
        self._analyze_frame = analyze_frame
        self._analyze_interval = analyze_interval

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        cases = list(payload.get('cases') or [])
        manifest_path = payload.get('manifestPath')
        progress_path = _resolve_optional_path(payload.get('progressPath'))
        checkpoint_path = _resolve_optional_path(payload.get('checkpointPath'))
        resume_from_checkpoint = bool(payload.get('resumeFromCheckpoint'))
        if manifest_path:
            manifest_payload = json.loads(Path(str(manifest_path)).read_text(encoding='utf-8'))
            cases.extend(manifest_payload.get('cases') or [])

        runtime_status = self._status()
        if not cases:
            result = summarize_benchmark_results([], runtime_status)
            _write_execution_state(
                suite_cases=[],
                benchmark_results=[],
                started_at=datetime.now(UTC).isoformat(),
                runtime_status=runtime_status,
                progress_path=progress_path,
                checkpoint_path=checkpoint_path,
                completed=True,
            )
            return result

        valid_case_ids = {
            str(case_payload.get('id') or f'case-{index + 1}')
            for index, case_payload in enumerate(cases)
        }
        benchmark_results, started_at = _load_checkpoint_results(checkpoint_path, valid_case_ids) if resume_from_checkpoint else ([], None)
        started_at = started_at or datetime.now(UTC).isoformat()
        completed_case_ids = {
            str(result.get('id') or '')
            for result in benchmark_results
            if isinstance(result, dict) and result.get('id')
        }

        _write_execution_state(
            suite_cases=cases,
            benchmark_results=benchmark_results,
            started_at=started_at,
            runtime_status=runtime_status,
            progress_path=progress_path,
            checkpoint_path=checkpoint_path,
            completed=False,
        )

        for index, case_payload in enumerate(cases):
            mode = str(case_payload.get('mode') or 'interval')
            case_id = str(case_payload.get('id') or f'case-{index + 1}')
            if case_id in completed_case_ids:
                continue
            expected_text = normalize_plate_text(case_payload.get('expectedText'))
            case_metadata = dict(case_payload.get('metadata') or {})
            timer_started = time.perf_counter()

            if mode == 'frame':
                response = self._analyze_frame(case_payload)
                candidates = response.get('candidates') or []
            else:
                response = self._analyze_interval(case_payload)
                candidates = response.get('candidates') or []

            latency_ms = max(0.0, (time.perf_counter() - timer_started) * 1000.0)

            ranked_texts = [normalize_plate_text(candidate.get('text')) for candidate in candidates if candidate.get('text')]
            ranked_sources = [str(candidate.get('source') or '') for candidate in candidates if candidate.get('text')]
            best_text = ranked_texts[0] if ranked_texts else ''
            best_source = ranked_sources[0] if ranked_sources else ''
            best_confidence = _candidate_confidence(candidates[0]) if candidates else 0.0
            second_confidence = _candidate_confidence(candidates[1]) if len(candidates) > 1 else 0.0
            accepted_margin = max(0.0, best_confidence - second_confidence)
            exact_match = bool(expected_text and best_text == expected_text)
            top3_match = bool(expected_text and expected_text in ranked_texts[:3])
            case_character_error_rate = character_error_rate(best_text, expected_text)
            localization = _evaluate_localization(case_payload, response)
            track_metrics_case = _evaluate_track_consistency(response, expected_text) if mode != 'frame' else None
            failure_reason = _classify_failure_reason(
                exact_match,
                accepted_margin,
                localization,
                track_metrics_case,
                response,
            )

            review_payload = response.get('review')
            if not isinstance(review_payload, dict):
                raise ValueError(f'Benchmark case {case_id} is missing review payload from runtime response.')
            provenance_payload = response.get('provenance')
            if not isinstance(provenance_payload, dict):
                raise ValueError(f'Benchmark case {case_id} is missing provenance payload from runtime response.')

            benchmark_results.append(
                {
                    'id': case_id,
                    'mode': mode,
                    'expectedText': expected_text,
                    'bestText': best_text,
                    'bestSource': best_source,
                    'allSources': ranked_sources,
                    'top3Texts': ranked_texts[:3],
                    'exactMatch': exact_match,
                    'top3Match': top3_match,
                    'characterErrorRate': case_character_error_rate,
                    'acceptedCandidateId': response.get('acceptedCandidateId'),
                    'acceptedConfidence': best_confidence,
                    'acceptedMargin': accepted_margin,
                    'latencyMs': latency_ms,
                    'localization': localization,
                    'trackMetrics': track_metrics_case,
                    'failureReason': failure_reason,
                    'review': dict(review_payload),
                    'provenance': dict(provenance_payload),
                    'summary': response.get('summary') or '',
                    'tags': list(case_payload.get('tags') or []),
                    'metadata': case_metadata,
                }
            )
            completed_case_ids.add(case_id)

            _write_execution_state(
                suite_cases=cases,
                benchmark_results=benchmark_results,
                started_at=started_at,
                runtime_status=runtime_status,
                progress_path=progress_path,
                checkpoint_path=checkpoint_path,
                current_case_id=case_id,
                completed=False,
            )

        runtime_status = self._status()
        result = summarize_benchmark_results(benchmark_results, runtime_status)
        _write_execution_state(
            suite_cases=cases,
            benchmark_results=benchmark_results,
            started_at=started_at,
            runtime_status=runtime_status,
            progress_path=progress_path,
            checkpoint_path=checkpoint_path,
            completed=True,
        )
        return result


def summarize_benchmark_results(benchmark_results: list[dict[str, Any]], runtime_status: dict[str, Any]) -> dict[str, Any]:
    if not benchmark_results:
        return {
            'summary': 'No benchmark cases were provided.',
            'cases': [],
            'metrics': {
                'totalCases': 0,
                'exactMatchRate': 0.0,
                'top3MatchRate': 0.0,
                'meanCharacterErrorRate': 0.0,
                'acceptedRate': 0.0,
                'reviewRequiredRate': 0.0,
                'noCandidateRate': 0.0,
                'reviewBreakdown': {},
                'reviewReasonBreakdown': {},
                'sourceWinCounts': {},
                'meanAcceptedMargin': 0.0,
                'latencyMs': {
                    'mean': 0.0,
                    'p50': 0.0,
                    'p95': 0.0,
                },
                'confidenceCalibration': {'expectedCalibrationError': 0.0, 'bins': []},
                'failureBreakdown': {},
                'tagBreakdown': {},
                'datasetBreakdown': {},
                'splitBreakdown': {},
            },
            'runtime': runtime_status,
        }

    exact_matches = 0
    top3_matches = 0
    total_character_error_rate = 0.0
    source_wins: dict[str, int] = {}
    tag_metrics: dict[str, dict[str, float]] = {}
    dataset_metrics: dict[str, dict[str, float]] = {}
    split_metrics: dict[str, dict[str, float]] = {}
    latency_values_ms: list[float] = []
    calibration_points: list[tuple[float, bool]] = []
    failure_counts: dict[str, int] = {}
    review_status_counts: dict[str, int] = {}
    review_reason_counts: dict[str, int] = {}

    for result in benchmark_results:
        exact_match = bool(result.get('exactMatch'))
        top3_match = bool(result.get('top3Match'))
        character_error_rate_value = float(result.get('characterErrorRate') or 0.0)
        accepted_confidence = float(result.get('acceptedConfidence') or 0.0)
        accepted_margin = float(result.get('acceptedMargin') or 0.0)
        latency_ms = float(result.get('latencyMs') or 0.0)
        failure_reason = str(result.get('failureReason') or 'unknown')
        best_source = str(result.get('bestSource') or '')
        localization = dict(result.get('localization') or {})
        track_metrics_case = dict(result.get('trackMetrics') or {}) if isinstance(result.get('trackMetrics'), dict) else None
        metadata = dict(result.get('metadata') or {})
        review_payload = _normalized_review_payload(result)
        review_status = review_payload['status']

        exact_matches += 1 if exact_match else 0
        top3_matches += 1 if top3_match else 0
        total_character_error_rate += character_error_rate_value
        latency_values_ms.append(latency_ms)
        calibration_points.append((accepted_confidence, exact_match))
        failure_counts[failure_reason] = failure_counts.get(failure_reason, 0) + 1
        review_status_counts[review_status] = review_status_counts.get(review_status, 0) + 1
        for reason in review_payload['reasons']:
            review_reason_counts[reason] = review_reason_counts.get(reason, 0) + 1
        if best_source:
            source_wins[best_source] = source_wins.get(best_source, 0) + 1

        case_metrics = {
            'exactMatch': exact_match,
            'top3Match': top3_match,
            'characterErrorRate': character_error_rate_value,
            'acceptedCase': review_status == 'accepted',
            'reviewRequiredCase': review_status == 'review-required',
            'noCandidateCase': review_status == 'no-candidate',
            'latencyMs': latency_ms,
            'acceptedMargin': accepted_margin,
            'plateIoU': localization.get('plateMeanIoU'),
            'plateLocalizationRecall': localization.get('plateRecall'),
            'targetIoU': localization.get('targetMeanIoU'),
            'targetLocalizationRecall': localization.get('targetRecall'),
            'trackMajorityExactMatch': (track_metrics_case or {}).get('majorityExactMatch'),
            'predictionSwitchCount': (track_metrics_case or {}).get('predictionSwitchCount'),
            'sampleExactMatchRate': (track_metrics_case or {}).get('sampleExactMatchRate'),
            'timeToFirstCorrectMs': (track_metrics_case or {}).get('timeToFirstCorrectMs'),
        }

        for tag in list(result.get('tags') or []):
            _update_metric_bucket(tag_metrics.setdefault(str(tag), _new_metric_bucket()), case_metrics)

        dataset_name = str(metadata.get('dataset') or 'unknown')
        split_name = str(metadata.get('split') or 'unknown')
        _update_metric_bucket(dataset_metrics.setdefault(dataset_name, _new_metric_bucket()), case_metrics)
        _update_metric_bucket(split_metrics.setdefault(split_name, _new_metric_bucket()), case_metrics)

    total_cases = len(benchmark_results)
    metrics = {
        'totalCases': total_cases,
        'exactMatchRate': exact_matches / total_cases,
        'top3MatchRate': top3_matches / total_cases,
        'meanCharacterErrorRate': total_character_error_rate / total_cases,
        'acceptedRate': review_status_counts.get('accepted', 0) / total_cases,
        'reviewRequiredRate': review_status_counts.get('review-required', 0) / total_cases,
        'noCandidateRate': review_status_counts.get('no-candidate', 0) / total_cases,
        'reviewBreakdown': dict(sorted(review_status_counts.items())),
        'reviewReasonBreakdown': dict(sorted(review_reason_counts.items())),
        'sourceWinCounts': source_wins,
        'meanAcceptedMargin': sum(float(result.get('acceptedMargin') or 0.0) for result in benchmark_results) / total_cases,
        'latencyMs': {
            'mean': sum(latency_values_ms) / total_cases if latency_values_ms else 0.0,
            'p50': _percentile(latency_values_ms, 0.50),
            'p95': _percentile(latency_values_ms, 0.95),
        },
        'confidenceCalibration': _build_confidence_calibration(calibration_points),
        'failureBreakdown': failure_counts,
        'tagBreakdown': {
            tag: _finalize_metric_bucket(values)
            for tag, values in sorted(tag_metrics.items())
        },
        'datasetBreakdown': {
            dataset: _finalize_metric_bucket(values)
            for dataset, values in sorted(dataset_metrics.items())
        },
        'splitBreakdown': {
            split: _finalize_metric_bucket(values)
            for split, values in sorted(split_metrics.items())
        },
    }
    summary = (
        f"{total_cases} cases, exact={metrics['exactMatchRate']:.1%}, "
        f"top3={metrics['top3MatchRate']:.1%}, cer={metrics['meanCharacterErrorRate']:.3f}, "
        f"review={metrics['reviewRequiredRate']:.1%}, noCandidate={metrics['noCandidateRate']:.1%}, "
        f"plateIoU={_safe_metric_average(benchmark_results, 'localization', 'plateMeanIoU'):.3f}, "
        f"p95={metrics['latencyMs']['p95']:.1f}ms"
    )
    return {
        'summary': summary,
        'cases': benchmark_results,
        'metrics': metrics,
        'runtime': runtime_status,
    }


def _resolve_optional_path(value: Any) -> Path | None:
    if value in (None, ''):
        return None
    return Path(str(value)).resolve()


def _load_checkpoint_results(checkpoint_path: Path | None, valid_case_ids: set[str]) -> tuple[list[dict[str, Any]], str | None]:
    if checkpoint_path is None or not checkpoint_path.exists():
        return [], None

    payload = json.loads(checkpoint_path.read_text(encoding='utf-8'))
    started_at = str(payload.get('startedAt')) if isinstance(payload.get('startedAt'), str) else None
    stored_cases = payload.get('cases')
    if not isinstance(stored_cases, list):
        return [], started_at

    restored: list[dict[str, Any]] = []
    seen_case_ids: set[str] = set()
    for entry in stored_cases:
        if not isinstance(entry, dict):
            continue
        case_id = str(entry.get('id') or '')
        if not case_id or case_id in seen_case_ids or case_id not in valid_case_ids:
            continue
        restored.append(entry)
        seen_case_ids.add(case_id)
    return restored, started_at


def _write_execution_state(
    suite_cases: list[dict[str, Any]],
    benchmark_results: list[dict[str, Any]],
    started_at: str,
    runtime_status: dict[str, Any],
    progress_path: Path | None = None,
    checkpoint_path: Path | None = None,
    current_case_id: str | None = None,
    completed: bool = False,
) -> None:
    if progress_path is None and checkpoint_path is None:
        return

    partial_result = summarize_benchmark_results(benchmark_results, runtime_status)
    total_cases = len(suite_cases)
    completed_count = len(benchmark_results)
    updated_at = datetime.now(UTC).isoformat()
    latest_case = benchmark_results[-1] if benchmark_results else None

    progress_payload: dict[str, Any] = {
        'schemaVersion': 1,
        'startedAt': started_at,
        'updatedAt': updated_at,
        'totalCases': total_cases,
        'completedCaseCount': completed_count,
        'remainingCaseCount': max(total_cases - completed_count, 0),
        'completed': completed,
        'currentCaseId': None if completed else current_case_id,
        'latestCase': {
            'id': latest_case.get('id'),
            'failureReason': latest_case.get('failureReason'),
            'latencyMs': latest_case.get('latencyMs'),
        } if isinstance(latest_case, dict) else None,
        'summary': partial_result.get('summary'),
        'metrics': partial_result.get('metrics'),
    }

    if progress_path is not None:
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text(json.dumps(progress_payload, indent=2), encoding='utf-8')

    if checkpoint_path is not None:
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_payload = {
            **progress_payload,
            'suiteCaseIds': [
                str(case_payload.get('id') or f'case-{index + 1}')
                for index, case_payload in enumerate(suite_cases)
            ],
            'cases': benchmark_results,
        }
        checkpoint_path.write_text(json.dumps(checkpoint_payload, indent=2), encoding='utf-8')


def _candidate_confidence(candidate: dict[str, Any] | None) -> float:
    if not isinstance(candidate, dict):
        return 0.0
    try:
        return float(candidate.get('confidence') or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _new_metric_bucket() -> dict[str, float]:
    return {
        'totalCases': 0.0,
        'exact': 0.0,
        'top3': 0.0,
        'cer': 0.0,
        'accepted': 0.0,
        'reviewRequired': 0.0,
        'noCandidate': 0.0,
        'latencyMs': 0.0,
        'acceptedMargin': 0.0,
        'plateIoUSum': 0.0,
        'plateIoUCount': 0.0,
        'plateRecallSum': 0.0,
        'plateRecallCount': 0.0,
        'targetIoUSum': 0.0,
        'targetIoUCount': 0.0,
        'targetRecallSum': 0.0,
        'targetRecallCount': 0.0,
        'trackCases': 0.0,
        'majorityExact': 0.0,
        'predictionSwitchCount': 0.0,
        'sampleExactMatchRate': 0.0,
        'sampleExactMatchRateCount': 0.0,
        'timeToFirstCorrectMs': 0.0,
        'timeToFirstCorrectCount': 0.0,
    }


def _update_metric_bucket(bucket: dict[str, float], case_metrics: dict[str, Any]) -> None:
    bucket['totalCases'] += 1.0
    bucket['exact'] += 1.0 if case_metrics.get('exactMatch') else 0.0
    bucket['top3'] += 1.0 if case_metrics.get('top3Match') else 0.0
    bucket['cer'] += float(case_metrics.get('characterErrorRate') or 0.0)
    bucket['accepted'] += 1.0 if case_metrics.get('acceptedCase') else 0.0
    bucket['reviewRequired'] += 1.0 if case_metrics.get('reviewRequiredCase') else 0.0
    bucket['noCandidate'] += 1.0 if case_metrics.get('noCandidateCase') else 0.0
    bucket['latencyMs'] += float(case_metrics.get('latencyMs') or 0.0)
    bucket['acceptedMargin'] += float(case_metrics.get('acceptedMargin') or 0.0)

    plate_iou = case_metrics.get('plateIoU')
    if isinstance(plate_iou, (int, float)):
        bucket['plateIoUSum'] += float(plate_iou)
        bucket['plateIoUCount'] += 1.0
    plate_recall = case_metrics.get('plateLocalizationRecall')
    if isinstance(plate_recall, (int, float)):
        bucket['plateRecallSum'] += float(plate_recall)
        bucket['plateRecallCount'] += 1.0

    target_iou = case_metrics.get('targetIoU')
    if isinstance(target_iou, (int, float)):
        bucket['targetIoUSum'] += float(target_iou)
        bucket['targetIoUCount'] += 1.0
    target_recall = case_metrics.get('targetLocalizationRecall')
    if isinstance(target_recall, (int, float)):
        bucket['targetRecallSum'] += float(target_recall)
        bucket['targetRecallCount'] += 1.0

    if case_metrics.get('trackMajorityExactMatch') is not None:
        bucket['trackCases'] += 1.0
        bucket['majorityExact'] += 1.0 if case_metrics.get('trackMajorityExactMatch') else 0.0
    if isinstance(case_metrics.get('predictionSwitchCount'), (int, float)):
        bucket['predictionSwitchCount'] += float(case_metrics['predictionSwitchCount'])
    if isinstance(case_metrics.get('sampleExactMatchRate'), (int, float)):
        bucket['sampleExactMatchRate'] += float(case_metrics['sampleExactMatchRate'])
        bucket['sampleExactMatchRateCount'] += 1.0
    if isinstance(case_metrics.get('timeToFirstCorrectMs'), (int, float)):
        bucket['timeToFirstCorrectMs'] += float(case_metrics['timeToFirstCorrectMs'])
        bucket['timeToFirstCorrectCount'] += 1.0


def _finalize_metric_bucket(bucket: dict[str, float]) -> dict[str, float | None]:
    total_cases = max(bucket['totalCases'], 1.0)
    return {
        'totalCases': int(bucket['totalCases']),
        'exactMatchRate': bucket['exact'] / total_cases,
        'top3MatchRate': bucket['top3'] / total_cases,
        'meanCharacterErrorRate': bucket['cer'] / total_cases,
        'acceptedRate': bucket['accepted'] / total_cases,
        'reviewRequiredRate': bucket['reviewRequired'] / total_cases,
        'noCandidateRate': bucket['noCandidate'] / total_cases,
        'meanLatencyMs': bucket['latencyMs'] / total_cases,
        'meanAcceptedMargin': bucket['acceptedMargin'] / total_cases,
        'meanPlateIoU': bucket['plateIoUSum'] / bucket['plateIoUCount'] if bucket['plateIoUCount'] else None,
        'plateLocalizationRecall': bucket['plateRecallSum'] / bucket['plateRecallCount'] if bucket['plateRecallCount'] else None,
        'meanTargetIoU': bucket['targetIoUSum'] / bucket['targetIoUCount'] if bucket['targetIoUCount'] else None,
        'targetLocalizationRecall': bucket['targetRecallSum'] / bucket['targetRecallCount'] if bucket['targetRecallCount'] else None,
        'trackMajorityExactMatchRate': bucket['majorityExact'] / bucket['trackCases'] if bucket['trackCases'] else None,
        'meanPredictionSwitchCount': bucket['predictionSwitchCount'] / bucket['trackCases'] if bucket['trackCases'] else None,
        'meanSampleExactMatchRate': bucket['sampleExactMatchRate'] / bucket['sampleExactMatchRateCount'] if bucket['sampleExactMatchRateCount'] else None,
        'meanTimeToFirstCorrectMs': bucket['timeToFirstCorrectMs'] / bucket['timeToFirstCorrectCount'] if bucket['timeToFirstCorrectCount'] else None,
    }


def _evaluate_localization(case_payload: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    ground_truth_frames = case_payload.get('groundTruthFrames')
    if isinstance(ground_truth_frames, list) and ground_truth_frames:
        return _evaluate_interval_localization(
            response.get('samples') or [],
            ground_truth_frames,
            int(case_payload.get('sampleEveryMs') or 120),
        )

    sample_payload = response.get('sample') if isinstance(response.get('sample'), dict) else None
    predicted_plate_box = _rect_from_payload(sample_payload.get('plateBox') if sample_payload else None)
    predicted_target_box = _rect_from_payload(sample_payload.get('targetBox') if sample_payload else None)
    ground_truth_plate_box = _rect_from_payload(case_payload.get('groundTruthPlateBox') or case_payload.get('markerRect'))
    ground_truth_target_box = _rect_from_payload(case_payload.get('groundTruthTargetBox') or case_payload.get('selectedTargetBox'))

    plate_iou = predicted_plate_box.intersection_over_union(ground_truth_plate_box) if predicted_plate_box and ground_truth_plate_box else None
    target_iou = predicted_target_box.intersection_over_union(ground_truth_target_box) if predicted_target_box and ground_truth_target_box else None
    return {
        'groundTruthFrameCount': 1 if ground_truth_plate_box or ground_truth_target_box else 0,
        'matchedFrameCount': 1 if sample_payload is not None else 0,
        'plateMeanIoU': plate_iou,
        'plateRecall': 1.0 if plate_iou is not None and plate_iou >= 0.5 else 0.0 if ground_truth_plate_box else None,
        'targetMeanIoU': target_iou,
        'targetRecall': 1.0 if target_iou is not None and target_iou >= 0.5 else 0.0 if ground_truth_target_box else None,
    }


def _evaluate_interval_localization(sample_payloads: list[Any], ground_truth_frames: list[Any], tolerance_ms: int) -> dict[str, Any]:
    matched_frames = 0
    plate_ious: list[float] = []
    target_ious: list[float] = []
    plate_hits = 0
    target_hits = 0

    for sample_payload in sample_payloads:
        if not isinstance(sample_payload, dict):
            continue
        matched_ground_truth = _match_ground_truth_frame(int(sample_payload.get('timeMs') or 0), ground_truth_frames, tolerance_ms)
        if matched_ground_truth is None:
            continue
        matched_frames += 1
        predicted_plate_box = _rect_from_payload(sample_payload.get('plateBox'))
        predicted_target_box = _rect_from_payload(sample_payload.get('targetBox'))
        ground_truth_plate_box = _rect_from_payload(matched_ground_truth.get('plateBox'))
        ground_truth_target_box = _rect_from_payload(matched_ground_truth.get('targetBox'))

        if predicted_plate_box and ground_truth_plate_box:
            plate_iou = predicted_plate_box.intersection_over_union(ground_truth_plate_box)
            plate_ious.append(plate_iou)
            if plate_iou >= 0.5:
                plate_hits += 1
        if predicted_target_box and ground_truth_target_box:
            target_iou = predicted_target_box.intersection_over_union(ground_truth_target_box)
            target_ious.append(target_iou)
            if target_iou >= 0.5:
                target_hits += 1

    ground_truth_count = len(ground_truth_frames)
    return {
        'groundTruthFrameCount': ground_truth_count,
        'matchedFrameCount': matched_frames,
        'plateMeanIoU': (sum(plate_ious) / len(plate_ious)) if plate_ious else None,
        'plateRecall': (plate_hits / ground_truth_count) if ground_truth_count else None,
        'targetMeanIoU': (sum(target_ious) / len(target_ious)) if target_ious else None,
        'targetRecall': (target_hits / ground_truth_count) if ground_truth_count else None,
    }


def _match_ground_truth_frame(time_ms: int, ground_truth_frames: list[Any], tolerance_ms: int) -> dict[str, Any] | None:
    best_entry: dict[str, Any] | None = None
    best_distance: int | None = None
    for entry in ground_truth_frames:
        if not isinstance(entry, dict):
            continue
        distance = abs(int(entry.get('timeMs') or 0) - time_ms)
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_entry = entry
    if best_distance is None or best_distance > max(tolerance_ms, 1):
        return None
    return best_entry


def _evaluate_track_consistency(response: dict[str, Any], expected_text: str) -> dict[str, Any] | None:
    sample_payloads = [sample for sample in (response.get('samples') or []) if isinstance(sample, dict)]
    if not sample_payloads:
        return None

    ranked_texts: list[tuple[int, str]] = []
    text_counts: dict[str, int] = {}
    exact_matches = 0
    for sample in sample_payloads:
        top_candidate = (sample.get('candidates') or [None])[0]
        if not isinstance(top_candidate, dict):
            continue
        normalized_text = normalize_plate_text(top_candidate.get('text'))
        if not normalized_text:
            continue
        sample_time_ms = int(sample.get('timeMs') or 0)
        ranked_texts.append((sample_time_ms, normalized_text))
        text_counts[normalized_text] = text_counts.get(normalized_text, 0) + 1
        if expected_text and normalized_text == expected_text:
            exact_matches += 1

    if not ranked_texts:
        return {
            'sampleCount': len(sample_payloads),
            'predictionSwitchCount': 0,
            'majorityText': '',
            'majorityExactMatch': False,
            'sampleExactMatchRate': 0.0,
            'timeToFirstCorrectMs': None,
        }

    ranked_texts.sort(key=lambda entry: entry[0])
    prediction_switch_count = 0
    for previous, current in zip(ranked_texts, ranked_texts[1:]):
        if previous[1] != current[1]:
            prediction_switch_count += 1

    majority_text = max(text_counts.items(), key=lambda entry: (entry[1], len(entry[0])))[0]
    time_to_first_correct_ms = next((time_ms for time_ms, text in ranked_texts if expected_text and text == expected_text), None)
    return {
        'sampleCount': len(sample_payloads),
        'predictionSwitchCount': prediction_switch_count,
        'majorityText': majority_text,
        'majorityExactMatch': bool(expected_text and majority_text == expected_text),
        'sampleExactMatchRate': exact_matches / max(len(ranked_texts), 1),
        'timeToFirstCorrectMs': time_to_first_correct_ms,
    }


def _classify_failure_reason(
    exact_match: bool,
    accepted_margin: float,
    localization: dict[str, Any],
    track_metrics_case: dict[str, Any] | None,
    response: dict[str, Any],
) -> str:
    if exact_match:
        return 'correct'
    if isinstance(localization.get('targetRecall'), (int, float)) and float(localization['targetRecall']) <= 0.25:
        return 'target-missed'
    if isinstance(localization.get('plateRecall'), (int, float)) and float(localization['plateRecall']) <= 0.25:
        return 'plate-localization-missed'

    quality_scores = _sample_quality_scores(response)
    if quality_scores and max(quality_scores) < 0.45:
        return 'plate-quality-poor'
    if track_metrics_case and int(track_metrics_case.get('predictionSwitchCount') or 0) >= 2:
        return 'fusion-unstable'
    if _has_candidate_disagreement(response, accepted_margin):
        return 'ocr-disagreement'
    return 'wrong-text'


def _sample_quality_scores(response: dict[str, Any]) -> list[float]:
    values: list[float] = []
    sample_payload = response.get('sample')
    if isinstance(sample_payload, dict):
        quality_payload = sample_payload.get('quality')
        if isinstance(quality_payload, dict) and isinstance(quality_payload.get('overallScore'), (int, float)):
            values.append(float(quality_payload['overallScore']))

    for sample in response.get('samples') or []:
        if not isinstance(sample, dict):
            continue
        quality_payload = sample.get('quality')
        if isinstance(quality_payload, dict) and isinstance(quality_payload.get('overallScore'), (int, float)):
            values.append(float(quality_payload['overallScore']))
    return values


def _has_candidate_disagreement(response: dict[str, Any], accepted_margin: float) -> bool:
    if accepted_margin < 0.08:
        return True

    observed_texts: set[str] = set()
    for sample in response.get('samples') or []:
        if not isinstance(sample, dict):
            continue
        top_candidate = (sample.get('candidates') or [None])[0]
        if not isinstance(top_candidate, dict):
            continue
        normalized_text = normalize_plate_text(top_candidate.get('text'))
        if normalized_text:
            observed_texts.add(normalized_text)
    return len(observed_texts) >= 3


def _rect_from_payload(payload: Any) -> NormalizedRect | None:
    if not isinstance(payload, dict):
        return None
    return NormalizedRect.from_payload(payload)


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * probability))))
    return float(ordered[index])


def _build_confidence_calibration(points: list[tuple[float, bool]], bins: int = 5) -> dict[str, Any]:
    if not points:
        return {'expectedCalibrationError': 0.0, 'bins': []}

    buckets = [
        {
            'count': 0,
            'confidenceSum': 0.0,
            'accuracySum': 0.0,
            'lowerBound': index / bins,
            'upperBound': (index + 1) / bins,
        }
        for index in range(bins)
    ]

    for confidence, exact_match in points:
        bucket_index = min(bins - 1, max(0, int(confidence * bins)))
        bucket = buckets[bucket_index]
        bucket['count'] += 1
        bucket['confidenceSum'] += confidence
        bucket['accuracySum'] += 1.0 if exact_match else 0.0

    expected_calibration_error = 0.0
    serialized_bins: list[dict[str, Any]] = []
    total = len(points)
    for bucket in buckets:
        if bucket['count'] == 0:
            serialized_bins.append({
                'lowerBound': bucket['lowerBound'],
                'upperBound': bucket['upperBound'],
                'count': 0,
                'meanConfidence': 0.0,
                'accuracy': 0.0,
            })
            continue

        mean_confidence = bucket['confidenceSum'] / bucket['count']
        accuracy = bucket['accuracySum'] / bucket['count']
        expected_calibration_error += abs(accuracy - mean_confidence) * (bucket['count'] / total)
        serialized_bins.append({
            'lowerBound': bucket['lowerBound'],
            'upperBound': bucket['upperBound'],
            'count': bucket['count'],
            'meanConfidence': mean_confidence,
            'accuracy': accuracy,
        })

    return {
        'expectedCalibrationError': expected_calibration_error,
        'bins': serialized_bins,
    }


def _safe_metric_average(results: list[dict[str, Any]], parent_key: str, value_key: str) -> float:
    values: list[float] = []
    for result in results:
        parent = result.get(parent_key)
        if not isinstance(parent, dict):
            continue
        value = parent.get(value_key)
        if isinstance(value, (int, float)):
            values.append(float(value))
    return sum(values) / len(values) if values else 0.0


def _normalized_review_payload(result: dict[str, Any]) -> dict[str, Any]:
    review_payload = result.get('review')
    if not isinstance(review_payload, dict):
        raise ValueError('Benchmark result is missing review payload.')

    status = str(review_payload.get('status') or '').strip()
    if status not in {'accepted', 'review-required', 'no-candidate'}:
        raise ValueError(f'Unsupported review status: {status!r}')

    reasons = [
        str(reason)
        for reason in review_payload.get('reasons') or []
        if isinstance(reason, str) and reason
    ]
    if status == 'no-candidate' and not reasons:
        reasons = ['no-candidate']

    return {'status': status, 'reasons': reasons}
