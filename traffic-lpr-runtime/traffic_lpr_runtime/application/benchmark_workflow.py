from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from traffic_lpr_runtime.domain.text import character_error_rate, normalize_plate_text
from traffic_lpr_runtime.domain.value_objects import NormalizedRect


READABLE_EXPECTATION_KIND = 'readable'
UNREADABLE_EXPECTATION_KIND = 'unreadable'


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
        run_id = _resolve_optional_str(payload.get('runId'))
        artifact_root = _resolve_optional_path(payload.get('artifactRoot'))
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
                started_at=_local_now_iso(),
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
        started_at = started_at or _local_now_iso()
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
            expectation_kind, expected_text = _resolve_case_expectation(case_payload)
            case_metadata = dict(case_payload.get('metadata') or {})
            timer_started = time.perf_counter()
            request_payload = _build_case_request(case_payload, run_id=run_id, artifact_root=artifact_root, case_id=case_id)

            if mode == 'frame':
                response = self._analyze_frame(request_payload)
                candidates = response.get('candidates') or []
            else:
                response = self._analyze_interval(request_payload)
                candidates = response.get('candidates') or []

            latency_ms = max(0.0, (time.perf_counter() - timer_started) * 1000.0)

            ranked_texts = [normalize_plate_text(candidate.get('text')) for candidate in candidates if candidate.get('text')]
            ranked_sources = [str(candidate.get('source') or '') for candidate in candidates if candidate.get('text')]
            best_text = ranked_texts[0] if ranked_texts else ''
            best_source = ranked_sources[0] if ranked_sources else ''
            best_confidence = _candidate_confidence(candidates[0]) if candidates else 0.0
            second_confidence = _candidate_confidence(candidates[1]) if len(candidates) > 1 else 0.0
            accepted_margin = max(0.0, best_confidence - second_confidence)
            exact_match = _matches_expectation(expectation_kind, expected_text, best_text)
            top3_match = _top3_matches_expectation(expectation_kind, expected_text, ranked_texts[:3])
            case_character_error_rate = _expectation_character_error_rate(expectation_kind, expected_text, best_text)
            localization = _evaluate_localization(case_payload, response)
            track_metrics_case = _evaluate_track_consistency(response, expectation_kind, expected_text) if mode != 'frame' else None
            sequence_payload = _normalized_sequence_payload(response)
            failure_reason = _classify_failure_reason(
                expectation_kind,
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
            tracker_diagnostics_payload = {}
            diagnostics_payload = response.get('diagnostics')
            if isinstance(diagnostics_payload, dict) and isinstance(diagnostics_payload.get('tracker'), dict):
                tracker_diagnostics_payload = dict(diagnostics_payload['tracker'])
            tracking_payload = dict(response.get('tracking') or {}) if isinstance(response.get('tracking'), dict) else None
            if tracking_payload is not None:
                for key in [
                    'identityBreaks',
                    'reassociatedFrames',
                    'reacquireFrames',
                    'detectionFallbackFrames',
                    'uncertainFrames',
                    'backwardTrackedFrameCount',
                    'forwardTrackedFrameCount',
                ]:
                    value = tracker_diagnostics_payload.get(key)
                    if isinstance(value, (int, float)):
                        tracking_payload[key] = value

            benchmark_results.append(
                {
                    'id': case_id,
                    'mode': mode,
                    'expectationKind': expectation_kind,
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
                    'tracking': tracking_payload,
                    'sequence': sequence_payload,
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
                'intervalTrackingCaseCount': 0,
                'trackingTierBreakdown': {},
                'meanTrackingCoverageRatio': None,
                'degradedTrackingRate': None,
                'acceptedUnderDegradedTrackingRate': None,
                'detectionFallbackCaseCount': 0,
                'detectionFallbackReviewRequiredRate': None,
                'meanDetectionFallbackReacquireFrames': None,
                'meanTrackedFrameCount': None,
                'intervalSequenceCaseCount': 0,
                'sequenceTierBreakdown': {},
                'meanSequencePersistence': None,
                'meanSequenceGapCount': None,
                'meanPredictionSwitchCount': None,
                'meanSampleExactMatchRate': None,
                'meanCharacterConsistencyMean': None,
                'tagBreakdown': {},
                'datasetBreakdown': {},
                'splitBreakdown': {},
                'difficultyBreakdown': {
                    'category': {},
                    'trackingTier': {},
                    'sequenceTier': {},
                    'reviewStatus': {},
                },
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
    tracking_tier_counts: dict[str, int] = {}
    tracking_coverage_values: list[float] = []
    tracked_frame_counts: list[int] = []
    degraded_tracking_cases = 0
    accepted_under_degraded_tracking_cases = 0
    interval_tracking_cases = 0
    detection_fallback_cases = 0
    detection_fallback_review_required_cases = 0
    detection_fallback_reacquire_values: list[float] = []
    sequence_tier_counts: dict[str, int] = {}
    sequence_persistence_values: list[float] = []
    sequence_gap_values: list[float] = []
    prediction_switch_values: list[float] = []
    sample_exact_match_rate_values: list[float] = []
    character_consistency_mean_values: list[float] = []
    interval_sequence_cases = 0
    difficulty_category_metrics: dict[str, dict[str, float]] = {}
    difficulty_tracking_tier_metrics: dict[str, dict[str, float]] = {}
    difficulty_sequence_tier_metrics: dict[str, dict[str, float]] = {}
    difficulty_review_status_metrics: dict[str, dict[str, float]] = {}

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
        tracking_payload = dict(result.get('tracking') or {}) if isinstance(result.get('tracking'), dict) else None
        sequence_payload = dict(result.get('sequence') or {}) if isinstance(result.get('sequence'), dict) else None
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
        if tracking_payload:
            interval_tracking_cases += 1
            tracking_tier = str(tracking_payload.get('trackingTier') or 'unknown')
            tracking_tier_counts[tracking_tier] = tracking_tier_counts.get(tracking_tier, 0) + 1
            if tracking_tier != 'full':
                degraded_tracking_cases += 1
                if review_status == 'accepted':
                    accepted_under_degraded_tracking_cases += 1
            if tracking_tier == 'detection-fallback':
                detection_fallback_cases += 1
                if review_status == 'review-required':
                    detection_fallback_review_required_cases += 1
                reacquire_frames = _coerce_optional_float(tracking_payload.get('reacquireFrames'))
                if reacquire_frames is not None:
                    detection_fallback_reacquire_values.append(reacquire_frames)
            coverage_ratio = _coerce_optional_float(tracking_payload.get('coverageRatio'))
            if coverage_ratio is not None:
                tracking_coverage_values.append(coverage_ratio)
            tracked_frame_count = _coerce_optional_int(tracking_payload.get('trackedFrameCount'))
            if tracked_frame_count is not None:
                tracked_frame_counts.append(tracked_frame_count)
        if sequence_payload:
            interval_sequence_cases += 1
            sequence_tier = str(sequence_payload.get('sequenceTier') or 'unknown')
            sequence_tier_counts[sequence_tier] = sequence_tier_counts.get(sequence_tier, 0) + 1
            persistence_ratio = _coerce_optional_float(sequence_payload.get('persistenceRatio'))
            if persistence_ratio is not None:
                sequence_persistence_values.append(persistence_ratio)
            support_gap_count = _coerce_optional_int(sequence_payload.get('supportFrameGapCount'))
            if support_gap_count is not None:
                sequence_gap_values.append(float(support_gap_count))
            character_consistency_mean = _coerce_optional_float(sequence_payload.get('characterConsistencyMean'))
            if character_consistency_mean is not None:
                character_consistency_mean_values.append(character_consistency_mean)
        prediction_switch_count = _coerce_optional_float((track_metrics_case or {}).get('predictionSwitchCount'))
        if prediction_switch_count is not None:
            prediction_switch_values.append(prediction_switch_count)
        sample_exact_match_rate = _coerce_optional_float((track_metrics_case or {}).get('sampleExactMatchRate'))
        if sample_exact_match_rate is not None:
            sample_exact_match_rate_values.append(sample_exact_match_rate)

        case_metrics = {
            'exactMatch': exact_match,
            'top3Match': top3_match,
            'characterErrorRate': character_error_rate_value,
            'acceptedCase': review_status == 'accepted',
            'reviewRequiredCase': review_status == 'review-required',
            'noCandidateCase': review_status == 'no-candidate',
            'acceptedUnderDegradedTrackingCase': bool(tracking_payload) and str((tracking_payload or {}).get('trackingTier') or 'unknown') != 'full' and review_status == 'accepted',
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
            'trackingCoverageRatio': (tracking_payload or {}).get('coverageRatio'),
            'trackedFrameCount': (tracking_payload or {}).get('trackedFrameCount'),
            'reacquireFrames': (tracking_payload or {}).get('reacquireFrames'),
            'sequencePersistence': (sequence_payload or {}).get('persistenceRatio'),
            'sequenceGapCount': (sequence_payload or {}).get('supportFrameGapCount'),
            'characterConsistencyMean': (sequence_payload or {}).get('characterConsistencyMean'),
        }

        for tag in list(result.get('tags') or []):
            _update_metric_bucket(tag_metrics.setdefault(str(tag), _new_metric_bucket()), case_metrics)

        dataset_name = str(metadata.get('dataset') or 'unknown')
        split_name = str(metadata.get('split') or 'unknown')
        category_name = str(metadata.get('category') or metadata.get('dominantCategory') or 'uncategorized')
        _update_metric_bucket(dataset_metrics.setdefault(dataset_name, _new_metric_bucket()), case_metrics)
        _update_metric_bucket(split_metrics.setdefault(split_name, _new_metric_bucket()), case_metrics)
        _update_metric_bucket(difficulty_category_metrics.setdefault(category_name, _new_metric_bucket()), case_metrics)
        _update_metric_bucket(difficulty_review_status_metrics.setdefault(review_status, _new_metric_bucket()), case_metrics)
        if tracking_payload:
            tracking_tier = str(tracking_payload.get('trackingTier') or 'unknown')
            _update_metric_bucket(difficulty_tracking_tier_metrics.setdefault(tracking_tier, _new_metric_bucket()), case_metrics)
        if sequence_payload:
            sequence_tier = str(sequence_payload.get('sequenceTier') or 'unknown')
            _update_metric_bucket(difficulty_sequence_tier_metrics.setdefault(sequence_tier, _new_metric_bucket()), case_metrics)

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
        'intervalTrackingCaseCount': interval_tracking_cases,
        'trackingTierBreakdown': dict(sorted(tracking_tier_counts.items())),
        'meanTrackingCoverageRatio': _mean_values(tracking_coverage_values),
        'degradedTrackingRate': (degraded_tracking_cases / interval_tracking_cases) if interval_tracking_cases else None,
        'acceptedUnderDegradedTrackingRate': (accepted_under_degraded_tracking_cases / degraded_tracking_cases) if degraded_tracking_cases else None,
        'detectionFallbackCaseCount': detection_fallback_cases,
        'detectionFallbackReviewRequiredRate': (detection_fallback_review_required_cases / detection_fallback_cases) if detection_fallback_cases else None,
        'meanDetectionFallbackReacquireFrames': _mean_values(detection_fallback_reacquire_values),
        'meanTrackedFrameCount': (sum(tracked_frame_counts) / len(tracked_frame_counts)) if tracked_frame_counts else None,
        'intervalSequenceCaseCount': interval_sequence_cases,
        'sequenceTierBreakdown': dict(sorted(sequence_tier_counts.items())),
        'meanSequencePersistence': _mean_values(sequence_persistence_values),
        'meanSequenceGapCount': _mean_values(sequence_gap_values),
        'meanPredictionSwitchCount': _mean_values(prediction_switch_values),
        'meanSampleExactMatchRate': _mean_values(sample_exact_match_rate_values),
        'meanCharacterConsistencyMean': _mean_values(character_consistency_mean_values),
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
        'difficultyBreakdown': {
            'category': {
                label: _finalize_metric_bucket(values)
                for label, values in sorted(difficulty_category_metrics.items())
            },
            'trackingTier': {
                label: _finalize_metric_bucket(values)
                for label, values in sorted(difficulty_tracking_tier_metrics.items())
            },
            'sequenceTier': {
                label: _finalize_metric_bucket(values)
                for label, values in sorted(difficulty_sequence_tier_metrics.items())
            },
            'reviewStatus': {
                label: _finalize_metric_bucket(values)
                for label, values in sorted(difficulty_review_status_metrics.items())
            },
        },
    }
    summary = (
        f"{total_cases} cases, exact={metrics['exactMatchRate']:.1%}, "
        f"top3={metrics['top3MatchRate']:.1%}, cer={metrics['meanCharacterErrorRate']:.3f}, "
        f"review={metrics['reviewRequiredRate']:.1%}, noCandidate={metrics['noCandidateRate']:.1%}, "
        f"coverage={_format_optional_ratio(metrics['meanTrackingCoverageRatio'])}, "
        f"sequence={_format_optional_ratio(metrics['meanSequencePersistence'])}, "
        f"plateIoU={_safe_metric_average(benchmark_results, 'localization', 'plateMeanIoU'):.3f}, "
        f"p95={metrics['latencyMs']['p95']:.1f}ms"
    )
    if metrics['acceptedUnderDegradedTrackingRate'] is not None:
        summary = f"{summary}, degradedAccepted={metrics['acceptedUnderDegradedTrackingRate']:.1%}"
    if metrics['detectionFallbackReviewRequiredRate'] is not None:
        summary = f"{summary}, fallbackReview={metrics['detectionFallbackReviewRequiredRate']:.1%}"
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


def _resolve_optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _local_now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def _build_case_request(
    case_payload: dict[str, Any],
    *,
    run_id: str | None,
    artifact_root: Path | None,
    case_id: str,
) -> dict[str, Any]:
    request_payload = dict(case_payload)
    analysis_options = dict(request_payload.get('analysisOptions') or {})

    if run_id and not _resolve_optional_str(request_payload.get('requestId')):
        request_payload['requestId'] = f'{run_id}-{case_id}'

    if artifact_root is not None and not analysis_options.get('artifactDir'):
        analysis_options['artifactDir'] = str((artifact_root / 'cases' / case_id).resolve())
        analysis_options['persistArtifacts'] = True

    if analysis_options:
        request_payload['analysisOptions'] = analysis_options

    return request_payload


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
    updated_at = _local_now_iso()
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


def _coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean_values(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _format_optional_ratio(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f'{float(value):.1%}'
    return '--'


def _new_metric_bucket() -> dict[str, float]:
    return {
        'totalCases': 0.0,
        'exact': 0.0,
        'top3': 0.0,
        'cer': 0.0,
        'accepted': 0.0,
        'reviewRequired': 0.0,
        'noCandidate': 0.0,
        'acceptedUnderDegradedTracking': 0.0,
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
        'trackingCoverageRatio': 0.0,
        'trackingCoverageRatioCount': 0.0,
        'trackedFrameCount': 0.0,
        'trackedFrameCountCount': 0.0,
        'reacquireFrames': 0.0,
        'reacquireFramesCount': 0.0,
        'majorityExact': 0.0,
        'predictionSwitchCount': 0.0,
        'sampleExactMatchRate': 0.0,
        'sampleExactMatchRateCount': 0.0,
        'timeToFirstCorrectMs': 0.0,
        'timeToFirstCorrectCount': 0.0,
        'sequencePersistence': 0.0,
        'sequencePersistenceCount': 0.0,
        'sequenceGapCount': 0.0,
        'sequenceGapCountCount': 0.0,
        'characterConsistencyMean': 0.0,
        'characterConsistencyMeanCount': 0.0,
    }


def _update_metric_bucket(bucket: dict[str, float], case_metrics: dict[str, Any]) -> None:
    bucket['totalCases'] += 1.0
    bucket['exact'] += 1.0 if case_metrics.get('exactMatch') else 0.0
    bucket['top3'] += 1.0 if case_metrics.get('top3Match') else 0.0
    bucket['cer'] += float(case_metrics.get('characterErrorRate') or 0.0)
    bucket['accepted'] += 1.0 if case_metrics.get('acceptedCase') else 0.0
    bucket['reviewRequired'] += 1.0 if case_metrics.get('reviewRequiredCase') else 0.0
    bucket['noCandidate'] += 1.0 if case_metrics.get('noCandidateCase') else 0.0
    bucket['acceptedUnderDegradedTracking'] += 1.0 if case_metrics.get('acceptedUnderDegradedTrackingCase') else 0.0
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
    if isinstance(case_metrics.get('trackingCoverageRatio'), (int, float)):
        bucket['trackingCoverageRatio'] += float(case_metrics['trackingCoverageRatio'])
        bucket['trackingCoverageRatioCount'] += 1.0
    if isinstance(case_metrics.get('trackedFrameCount'), (int, float)):
        bucket['trackedFrameCount'] += float(case_metrics['trackedFrameCount'])
        bucket['trackedFrameCountCount'] += 1.0
    if isinstance(case_metrics.get('reacquireFrames'), (int, float)):
        bucket['reacquireFrames'] += float(case_metrics['reacquireFrames'])
        bucket['reacquireFramesCount'] += 1.0
    if isinstance(case_metrics.get('predictionSwitchCount'), (int, float)):
        bucket['predictionSwitchCount'] += float(case_metrics['predictionSwitchCount'])
    if isinstance(case_metrics.get('sampleExactMatchRate'), (int, float)):
        bucket['sampleExactMatchRate'] += float(case_metrics['sampleExactMatchRate'])
        bucket['sampleExactMatchRateCount'] += 1.0
    if isinstance(case_metrics.get('timeToFirstCorrectMs'), (int, float)):
        bucket['timeToFirstCorrectMs'] += float(case_metrics['timeToFirstCorrectMs'])
        bucket['timeToFirstCorrectCount'] += 1.0
    if isinstance(case_metrics.get('sequencePersistence'), (int, float)):
        bucket['sequencePersistence'] += float(case_metrics['sequencePersistence'])
        bucket['sequencePersistenceCount'] += 1.0
    if isinstance(case_metrics.get('sequenceGapCount'), (int, float)):
        bucket['sequenceGapCount'] += float(case_metrics['sequenceGapCount'])
        bucket['sequenceGapCountCount'] += 1.0
    if isinstance(case_metrics.get('characterConsistencyMean'), (int, float)):
        bucket['characterConsistencyMean'] += float(case_metrics['characterConsistencyMean'])
        bucket['characterConsistencyMeanCount'] += 1.0


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
        'acceptedUnderDegradedTrackingRate': bucket['acceptedUnderDegradedTracking'] / total_cases,
        'meanLatencyMs': bucket['latencyMs'] / total_cases,
        'meanAcceptedMargin': bucket['acceptedMargin'] / total_cases,
        'meanPlateIoU': bucket['plateIoUSum'] / bucket['plateIoUCount'] if bucket['plateIoUCount'] else None,
        'plateLocalizationRecall': bucket['plateRecallSum'] / bucket['plateRecallCount'] if bucket['plateRecallCount'] else None,
        'meanTargetIoU': bucket['targetIoUSum'] / bucket['targetIoUCount'] if bucket['targetIoUCount'] else None,
        'targetLocalizationRecall': bucket['targetRecallSum'] / bucket['targetRecallCount'] if bucket['targetRecallCount'] else None,
        'meanTrackingCoverageRatio': bucket['trackingCoverageRatio'] / bucket['trackingCoverageRatioCount'] if bucket['trackingCoverageRatioCount'] else None,
        'meanTrackedFrameCount': bucket['trackedFrameCount'] / bucket['trackedFrameCountCount'] if bucket['trackedFrameCountCount'] else None,
        'meanReacquireFrames': bucket['reacquireFrames'] / bucket['reacquireFramesCount'] if bucket['reacquireFramesCount'] else None,
        'trackMajorityExactMatchRate': bucket['majorityExact'] / bucket['trackCases'] if bucket['trackCases'] else None,
        'meanPredictionSwitchCount': bucket['predictionSwitchCount'] / bucket['trackCases'] if bucket['trackCases'] else None,
        'meanSampleExactMatchRate': bucket['sampleExactMatchRate'] / bucket['sampleExactMatchRateCount'] if bucket['sampleExactMatchRateCount'] else None,
        'meanTimeToFirstCorrectMs': bucket['timeToFirstCorrectMs'] / bucket['timeToFirstCorrectCount'] if bucket['timeToFirstCorrectCount'] else None,
        'meanSequencePersistence': bucket['sequencePersistence'] / bucket['sequencePersistenceCount'] if bucket['sequencePersistenceCount'] else None,
        'meanSequenceGapCount': bucket['sequenceGapCount'] / bucket['sequenceGapCountCount'] if bucket['sequenceGapCountCount'] else None,
        'meanCharacterConsistencyMean': bucket['characterConsistencyMean'] / bucket['characterConsistencyMeanCount'] if bucket['characterConsistencyMeanCount'] else None,
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
    if sample_payload is None:
        sample_payload = _resolve_interval_anchor_sample(case_payload, response)
    predicted_plate_box = _rect_from_payload(sample_payload.get('plateBox') if sample_payload else None)
    predicted_target_box = _rect_from_payload(sample_payload.get('targetBox') if sample_payload else None)
    if predicted_target_box is None:
        predicted_target_box = _resolve_track_box_at_time(
            response.get('analysisTrack'),
            int(case_payload.get('anchorTimeMs') or case_payload.get('timeMs') or 0),
            int(case_payload.get('sampleEveryMs') or 120),
        )
    ground_truth_plate_box = _rect_from_payload(case_payload.get('groundTruthPlateBox') or case_payload.get('markerRect'))
    ground_truth_target_box = _rect_from_payload(case_payload.get('groundTruthTargetBox') or case_payload.get('selectedTargetBox'))

    plate_iou = predicted_plate_box.intersection_over_union(ground_truth_plate_box) if predicted_plate_box and ground_truth_plate_box else None
    target_iou = predicted_target_box.intersection_over_union(ground_truth_target_box) if predicted_target_box and ground_truth_target_box else None
    matched_prediction = sample_payload is not None or predicted_plate_box is not None or predicted_target_box is not None
    return {
        'groundTruthFrameCount': 1 if ground_truth_plate_box or ground_truth_target_box else 0,
        'matchedFrameCount': 1 if matched_prediction else 0,
        'plateMeanIoU': plate_iou,
        'plateRecall': 1.0 if plate_iou is not None and plate_iou >= 0.5 else 0.0 if ground_truth_plate_box else None,
        'targetMeanIoU': target_iou,
        'targetRecall': 1.0 if target_iou is not None and target_iou >= 0.5 else 0.0 if ground_truth_target_box else None,
    }


def _resolve_interval_anchor_sample(case_payload: dict[str, Any], response: dict[str, Any]) -> dict[str, Any] | None:
    anchor_time_ms = int(case_payload.get('anchorTimeMs') or case_payload.get('timeMs') or 0)
    sample_payloads = [sample for sample in (response.get('samples') or []) if isinstance(sample, dict)]
    if not sample_payloads:
        return None
    tolerance_ms = max(180, int(case_payload.get('sampleEveryMs') or 120) * 2)
    closest = min(sample_payloads, key=lambda sample: abs(int(sample.get('timeMs') or 0) - anchor_time_ms))
    if abs(int(closest.get('timeMs') or 0) - anchor_time_ms) > tolerance_ms:
        return None
    return closest


def _resolve_track_box_at_time(track_payload: Any, time_ms: int, tolerance_step_ms: int) -> NormalizedRect | None:
    if not isinstance(track_payload, dict):
        return None
    frames = [frame for frame in (track_payload.get('frames') or []) if isinstance(frame, dict)]
    if not frames:
        return None
    closest = min(frames, key=lambda frame: abs(int(frame.get('timeMs') or 0) - time_ms))
    tolerance_ms = max(180, int(tolerance_step_ms) * 2)
    if abs(int(closest.get('timeMs') or 0) - time_ms) > tolerance_ms:
        return None
    return _rect_from_payload(closest.get('box'))


def _evaluate_interval_localization(sample_payloads: list[Any], ground_truth_frames: list[Any], tolerance_ms: int) -> dict[str, Any]:
    valid_samples = [sample for sample in sample_payloads if isinstance(sample, dict)]
    valid_ground_truth_frames = [frame for frame in ground_truth_frames if isinstance(frame, dict)]
    matched_frames = 0
    plate_ious: list[float] = []
    target_ious: list[float] = []
    plate_hits = 0
    target_hits = 0
    used_sample_indexes: set[int] = set()

    for matched_ground_truth in valid_ground_truth_frames:
        sample_index = _match_sample_index_for_ground_truth(
            int(matched_ground_truth.get('timeMs') or 0),
            valid_samples,
            tolerance_ms,
            used_sample_indexes,
        )
        if sample_index is None:
            continue
        used_sample_indexes.add(sample_index)
        sample_payload = valid_samples[sample_index]
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

    ground_truth_count = len(valid_ground_truth_frames)
    return {
        'groundTruthFrameCount': ground_truth_count,
        'matchedFrameCount': matched_frames,
        'plateMeanIoU': (sum(plate_ious) / len(plate_ious)) if plate_ious else None,
        'plateRecall': (plate_hits / ground_truth_count) if ground_truth_count else None,
        'targetMeanIoU': (sum(target_ious) / len(target_ious)) if target_ious else None,
        'targetRecall': (target_hits / ground_truth_count) if ground_truth_count else None,
    }


def _match_sample_index_for_ground_truth(
    time_ms: int,
    sample_payloads: list[dict[str, Any]],
    tolerance_ms: int,
    used_sample_indexes: set[int],
) -> int | None:
    best_index: int | None = None
    best_distance: int | None = None
    for index, sample_payload in enumerate(sample_payloads):
        if index in used_sample_indexes:
            continue
        distance = abs(int(sample_payload.get('timeMs') or 0) - time_ms)
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_index = index
    if best_distance is None or best_distance > max(tolerance_ms, 1):
        return None
    return best_index


def _evaluate_track_consistency(response: dict[str, Any], expectation_kind: str, expected_text: str | None) -> dict[str, Any] | None:
    sample_payloads = [sample for sample in (response.get('samples') or []) if isinstance(sample, dict)]
    if not sample_payloads:
        return None

    ranked_texts: list[tuple[int, str]] = []
    text_counts: dict[str, int] = {}
    exact_matches = 0
    for sample in sample_payloads:
        normalized_text = _sample_top_candidate_text(sample)
        if expectation_kind != UNREADABLE_EXPECTATION_KIND and not normalized_text:
            continue
        sample_time_ms = int(sample.get('timeMs') or 0)
        ranked_texts.append((sample_time_ms, normalized_text))
        text_counts[normalized_text] = text_counts.get(normalized_text, 0) + 1
        if _matches_expectation(expectation_kind, expected_text, normalized_text):
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
    time_to_first_correct_ms = next((time_ms for time_ms, text in ranked_texts if _matches_expectation(expectation_kind, expected_text, text)), None)
    return {
        'sampleCount': len(sample_payloads),
        'predictionSwitchCount': prediction_switch_count,
        'majorityText': majority_text,
        'majorityExactMatch': _matches_expectation(expectation_kind, expected_text, majority_text),
        'sampleExactMatchRate': exact_matches / max(len(ranked_texts), 1),
        'timeToFirstCorrectMs': time_to_first_correct_ms,
    }


def _classify_failure_reason(
    expectation_kind: str,
    exact_match: bool,
    accepted_margin: float,
    localization: dict[str, Any],
    track_metrics_case: dict[str, Any] | None,
    response: dict[str, Any],
) -> str:
    if exact_match:
        return 'correct'
    if expectation_kind == UNREADABLE_EXPECTATION_KIND:
        return 'unexpected-read'
    if isinstance(localization.get('targetRecall'), (int, float)) and float(localization['targetRecall']) <= 0.25:
        return 'target-missed'
    if isinstance(localization.get('plateRecall'), (int, float)) and float(localization['plateRecall']) <= 0.25:
        return 'plate-localization-missed'

    quality_scores = _sample_quality_scores(response)
    if quality_scores and max(quality_scores) < 0.45:
        return 'plate-quality-poor'
    if track_metrics_case and int(track_metrics_case.get('predictionSwitchCount') or 0) >= 2:
        return 'fusion-unstable'
    if _sequence_indicates_instability(response):
        return 'fusion-unstable'
    if _has_candidate_disagreement(response, accepted_margin):
        return 'ocr-disagreement'
    return 'wrong-text'


def _sequence_indicates_instability(response: dict[str, Any]) -> bool:
    sequence_payload = response.get('sequence')
    if not isinstance(sequence_payload, dict):
        return False

    sequence_tier = str(sequence_payload.get('sequenceTier') or '').strip().lower()
    if sequence_tier in {'fragmented', 'gapped', 'drifting'}:
        return True

    persistence_ratio = _coerce_optional_float(sequence_payload.get('persistenceRatio'))
    if persistence_ratio is not None and persistence_ratio < 0.55:
        return True

    support_gap_count = _coerce_optional_int(sequence_payload.get('supportFrameGapCount'))
    return support_gap_count is not None and support_gap_count > 1


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


def _resolve_case_expectation(case_payload: dict[str, Any]) -> tuple[str, str | None]:
    expectation_payload = case_payload.get('expectation') if isinstance(case_payload.get('expectation'), dict) else None
    expected_text = normalize_plate_text(case_payload.get('expectedText'))
    if expectation_payload is None:
        if expected_text:
            return READABLE_EXPECTATION_KIND, expected_text
        return UNREADABLE_EXPECTATION_KIND, None

    expectation_kind = str(expectation_payload.get('kind') or '').strip().lower()
    if expectation_kind == READABLE_EXPECTATION_KIND:
        expectation_text = normalize_plate_text(expectation_payload.get('text'))
        return READABLE_EXPECTATION_KIND, expectation_text or expected_text or None
    if expectation_kind == UNREADABLE_EXPECTATION_KIND:
        return UNREADABLE_EXPECTATION_KIND, None
    if expected_text:
        return READABLE_EXPECTATION_KIND, expected_text
    return UNREADABLE_EXPECTATION_KIND, None


def _matches_expectation(expectation_kind: str, expected_text: str | None, observed_text: str) -> bool:
    if expectation_kind == UNREADABLE_EXPECTATION_KIND:
        return not observed_text
    return bool(expected_text and observed_text == expected_text)


def _top3_matches_expectation(expectation_kind: str, expected_text: str | None, observed_texts: list[str]) -> bool:
    if expectation_kind == UNREADABLE_EXPECTATION_KIND:
        return not any(observed_texts)
    return bool(expected_text and expected_text in observed_texts)


def _expectation_character_error_rate(expectation_kind: str, expected_text: str | None, observed_text: str) -> float:
    if expectation_kind == UNREADABLE_EXPECTATION_KIND:
        return 0.0 if not observed_text else 1.0
    if not expected_text:
        return 0.0 if not observed_text else 1.0
    return character_error_rate(observed_text, expected_text)


def _sample_top_candidate_text(sample_payload: dict[str, Any]) -> str:
    top_candidate = (sample_payload.get('candidates') or [None])[0]
    if not isinstance(top_candidate, dict):
        return ''
    return normalize_plate_text(top_candidate.get('text'))


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


def _normalized_sequence_payload(response: dict[str, Any]) -> dict[str, Any] | None:
    sequence_payload = response.get('sequence')
    if not isinstance(sequence_payload, dict):
        return None

    character_consistency = [
        float(value)
        for value in sequence_payload.get('characterConsistency') or []
        if isinstance(value, (int, float))
    ]
    dominant_text = normalize_plate_text(sequence_payload.get('dominantText')) or None
    persistence_ratio = _coerce_optional_float(sequence_payload.get('persistenceRatio')) or 0.0
    support_frame_count = _coerce_optional_int(sequence_payload.get('supportFrameCount')) or 0
    sample_count = _coerce_optional_int(sequence_payload.get('sampleCount')) or 0
    support_gap_count = _coerce_optional_int(sequence_payload.get('supportFrameGapCount')) or 0
    prediction_switch_count = _coerce_optional_int(sequence_payload.get('predictionSwitchCount')) or 0
    character_consistency_mean = _coerce_optional_float(sequence_payload.get('characterConsistencyMean'))
    if character_consistency_mean is None:
        character_consistency_mean = (sum(character_consistency) / len(character_consistency)) if character_consistency else 0.0

    return {
        'sequenceTier': str(sequence_payload.get('sequenceTier') or 'fragmented'),
        'dominantText': dominant_text,
        'persistenceRatio': persistence_ratio,
        'supportFrameCount': support_frame_count,
        'sampleCount': sample_count,
        'supportFrameGapCount': support_gap_count,
        'predictionSwitchCount': prediction_switch_count,
        'characterConsistency': character_consistency,
        'characterConsistencyMean': character_consistency_mean,
    }
