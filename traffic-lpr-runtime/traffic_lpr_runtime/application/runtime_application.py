from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from traffic_lpr_runtime.domain.errors import RuntimeFailure
from traffic_lpr_runtime.domain.interfaces import FrameReader, PlateRecognizer, TargetDetector
from traffic_lpr_runtime.domain.models import FrameSample, PlateCandidate, TargetTrack, TrackedRegion
from traffic_lpr_runtime.domain.text import character_error_rate, normalize_plate_text
from traffic_lpr_runtime.domain.value_objects import NormalizedRect, clamp, crop_image
from traffic_lpr_runtime.application.pipeline_support import AnalysisOptions, PlateObservation, PlatePreprocessor, TargetCentricTracker
from traffic_lpr_runtime.infrastructure.dependencies import DependencyRegistry
from traffic_lpr_runtime.infrastructure.frame_reader import OpenCvFrameReader
from traffic_lpr_runtime.infrastructure.image_processing import QualityScorer
from traffic_lpr_runtime.infrastructure.model_runtime import (
    FastAlprPlateRecognizer,
    ModelRegistry,
    UltralyticsTargetDetector,
)


class LprRuntimeApplication:
    def __init__(
        self,
        dependencies: DependencyRegistry,
        frame_reader: FrameReader,
        target_detector: TargetDetector,
        primary_recognizer: PlateRecognizer,
        quality_scorer: QualityScorer,
    ) -> None:
        self._dependencies = dependencies
        self._frame_reader = frame_reader
        self._target_detector = target_detector
        self._primary_recognizer = primary_recognizer
        self._quality_scorer = quality_scorer
        self._plate_preprocessor = PlatePreprocessor(dependencies, quality_scorer)
        self._tracker = TargetCentricTracker(dependencies, frame_reader, target_detector)

    def dispatch(self, subcommand: str, payload: dict[str, Any]) -> dict[str, Any]:
        if subcommand == 'status':
            return self.status()
        if subcommand == 'benchmark-run':
            return self.benchmark_run(payload)
        if subcommand == 'scan-targets':
            return self.scan_targets(payload)
        if subcommand == 'analyze-frame':
            return self.analyze_frame(payload)
        if subcommand == 'analyze-interval':
            return self.analyze_interval(payload)
        raise RuntimeFailure(f'Unsupported LPR runtime subcommand: {subcommand}')

    def status(self) -> dict[str, Any]:
        return self._dependencies.build_status().to_payload()

    def scan_targets(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._dependencies.ensure_ready()
        time_ms = int(payload['timeMs'])
        frame = self._frame_reader.read_frame(payload['sourcePath'], time_ms)
        detections = self._detect_targets(
            frame,
            time_ms,
            payload.get('targetVehicleKind', 'vehicle'),
            NormalizedRect.from_payload(payload.get('markerRect')),
        )
        return {
            'detections': [detection.to_payload() for detection in detections],
            'runtime': self.status(),
        }

    def analyze_frame(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._dependencies.ensure_ready()
        time_ms = int(payload['timeMs'])
        options = AnalysisOptions.from_payload(payload)
        artifact_root = options.resolve_artifact_root(self._dependencies.runtime_root(), f'frame-{time_ms}')
        marker_rect = NormalizedRect.from_payload(payload.get('markerRect'))
        selected_target_box = NormalizedRect.from_payload(payload.get('selectedTargetBox'))
        frame = self._frame_reader.read_frame(payload['sourcePath'], time_ms)
        detections = self._detect_targets(
            frame,
            time_ms,
            payload.get('targetVehicleKind', 'vehicle'),
            marker_rect,
        )
        target_region = self._match_anchor_target(detections, selected_target_box)
        target_box = target_region.box if target_region else selected_target_box
        candidates, sample, observation = self._analyze_plate_candidates(
            frame,
            time_ms,
            marker_rect,
            target_box,
            payload.get('countryHints') or [],
            options,
            artifact_root,
        )
        candidates, accepted_candidate_id, selection_diagnostics = _apply_reliability_selection(
            candidates,
            [sample],
            payload.get('countryHints') or [],
            options,
            interval_mode=False,
        )
        sample.diagnostics = {
            **(sample.diagnostics or {}),
            'selection': selection_diagnostics,
        }
        return {
            'detections': [detection.to_payload() for detection in detections],
            'sample': sample.to_payload(),
            'candidates': [candidate.to_payload() for candidate in candidates[:8]],
            'acceptedCandidateId': accepted_candidate_id,
            'runtime': self.status(),
            'diagnostics': {
                'analysisOptions': options.to_payload(),
                'artifactRoot': str(artifact_root) if artifact_root else None,
                'observation': observation.diagnostics if observation else None,
                'selection': selection_diagnostics,
            },
        }

    def analyze_interval(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._dependencies.ensure_ready()
        options = AnalysisOptions.from_payload(payload)
        artifact_root = options.resolve_artifact_root(self._dependencies.runtime_root(), 'interval')
        selected_target_box = NormalizedRect.from_payload(payload.get('selectedTargetBox'))
        if selected_target_box is None:
            raise RuntimeFailure('Range analysis requires a selected target on the anchor frame.')

        tracked_frames, track_diagnostics = self._track_target_across_interval(
            payload['sourcePath'],
            payload['interval'],
            int(payload['anchorTimeMs']),
            payload.get('targetVehicleKind', 'vehicle'),
            selected_target_box,
            payload.get('sampleEveryMs'),
            payload.get('maxSamples'),
            options,
        )
        calibrated_target_boxes = self._calibrate_interval_target_boxes(
            tracked_frames,
            int(payload['anchorTimeMs']),
            selected_target_box,
        )

        samples: list[FrameSample] = []
        observations: list[PlateObservation] = []
        for tracked_frame in tracked_frames:
            analysis_target_box = tracked_frame.box
            frame = self._frame_reader.read_frame(payload['sourcePath'], tracked_frame.time_ms)
            _, sample, observation = self._analyze_plate_candidates(
                frame,
                tracked_frame.time_ms,
                None,
                analysis_target_box,
                payload.get('countryHints') or [],
                options,
                artifact_root / f'sample-{tracked_frame.time_ms}' if artifact_root else None,
            )
            calibrated_target_box = calibrated_target_boxes.get(tracked_frame.time_ms)
            if calibrated_target_box is not None:
                tracked_frame.diagnostics = {
                    **(tracked_frame.diagnostics or {}),
                    'analysisBox': analysis_target_box.to_payload(),
                    'calibratedBox': calibrated_target_box.to_payload(),
                }
                tracked_frame.box = calibrated_target_box
                sample.target_box = calibrated_target_box
                sample.diagnostics = {
                    **(sample.diagnostics or {}),
                    'analysisTargetBox': analysis_target_box.to_payload(),
                }
            samples.append(sample)
            if observation is not None:
                observations.append(observation)

        candidates, fusion_diagnostics = self._aggregate_candidates(
            samples,
            observations,
            payload.get('countryHints') or [],
            options,
            artifact_root,
        )
        candidates, accepted_candidate_id, selection_diagnostics = _apply_reliability_selection(
            candidates,
            samples,
            payload.get('countryHints') or [],
            options,
            interval_mode=True,
        )
        if candidates:
            suggested_candidate = next((candidate for candidate in candidates if candidate.id == selection_diagnostics.get('suggestedCandidateId')), candidates[0])
            summary = (
                f'{len(samples)} samples, {len(candidates)} fused candidate(s), '
                f'best={suggested_candidate.text}, tracker={track_diagnostics.get("trackerMode", "legacy")}'
            )
            if selection_diagnostics.get('reviewRequired'):
                summary = f'{summary}, review needed.'
        else:
            summary = f'{len(samples)} samples, no confident plate candidate.'

        return {
            'targetTracks': [track.to_payload() for track in self._build_track_payload(tracked_frames, track_diagnostics)],
            'samples': [sample.to_payload() for sample in samples],
            'candidates': [candidate.to_payload() for candidate in candidates],
            'acceptedCandidateId': accepted_candidate_id,
            'summary': summary,
            'runtime': self.status(),
            'diagnostics': {
                'analysisOptions': options.to_payload(),
                'artifactRoot': str(artifact_root) if artifact_root else None,
                'tracker': track_diagnostics,
                'fusion': fusion_diagnostics,
                'selection': selection_diagnostics,
            },
        }

    def benchmark_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._dependencies.ensure_ready()
        cases = list(payload.get('cases') or [])
        manifest_path = payload.get('manifestPath')
        if manifest_path:
            import json

            manifest_payload = json.loads(Path(str(manifest_path)).read_text(encoding='utf-8'))
            cases.extend(manifest_payload.get('cases') or [])

        if not cases:
            return {
                'summary': 'No benchmark cases were provided.',
                'cases': [],
                'metrics': {
                    'totalCases': 0,
                    'exactMatchRate': 0.0,
                    'top3MatchRate': 0.0,
                    'meanCharacterErrorRate': 0.0,
                },
                'runtime': self.status(),
            }

        benchmark_results: list[dict[str, Any]] = []
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

        for index, case_payload in enumerate(cases):
            mode = str(case_payload.get('mode') or 'interval')
            case_id = str(case_payload.get('id') or f'case-{index + 1}')
            expected_text = normalize_plate_text(case_payload.get('expectedText'))
            case_metadata = dict(case_payload.get('metadata') or {})
            timer_started = time.perf_counter()

            if mode == 'frame':
                response = self.analyze_frame(case_payload)
                candidates = response.get('candidates') or []
            else:
                response = self.analyze_interval(case_payload)
                candidates = response.get('candidates') or []

            latency_ms = max(0.0, (time.perf_counter() - timer_started) * 1000.0)
            latency_values_ms.append(latency_ms)

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

            exact_matches += 1 if exact_match else 0
            top3_matches += 1 if top3_match else 0
            total_character_error_rate += case_character_error_rate
            calibration_points.append((best_confidence, exact_match))
            failure_counts[failure_reason] = failure_counts.get(failure_reason, 0) + 1
            if best_source:
                source_wins[best_source] = source_wins.get(best_source, 0) + 1

            case_metrics = {
                'exactMatch': exact_match,
                'top3Match': top3_match,
                'characterErrorRate': case_character_error_rate,
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

            for tag in list(case_payload.get('tags') or []):
                _update_metric_bucket(tag_metrics.setdefault(str(tag), _new_metric_bucket()), case_metrics)

            dataset_name = str(case_metadata.get('dataset') or 'unknown')
            split_name = str(case_metadata.get('split') or case_payload.get('split') or 'unknown')
            _update_metric_bucket(dataset_metrics.setdefault(dataset_name, _new_metric_bucket()), case_metrics)
            _update_metric_bucket(split_metrics.setdefault(split_name, _new_metric_bucket()), case_metrics)

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
                    'acceptedConfidence': best_confidence,
                    'acceptedMargin': accepted_margin,
                    'latencyMs': latency_ms,
                    'localization': localization,
                    'trackMetrics': track_metrics_case,
                    'failureReason': failure_reason,
                    'summary': response.get('summary') or '',
                    'tags': list(case_payload.get('tags') or []),
                    'metadata': case_metadata,
                }
            )

        total_cases = len(benchmark_results)
        metrics = {
            'totalCases': total_cases,
            'exactMatchRate': exact_matches / total_cases,
            'top3MatchRate': top3_matches / total_cases,
            'meanCharacterErrorRate': total_character_error_rate / total_cases,
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
            f"plateIoU={_safe_metric_average(benchmark_results, 'localization', 'plateMeanIoU'):.3f}, "
            f"p95={metrics['latencyMs']['p95']:.1f}ms"
        )
        return {
            'summary': summary,
            'cases': benchmark_results,
            'metrics': metrics,
            'runtime': self.status(),
        }

    def _detect_targets(
        self,
        frame: Any,
        time_ms: int,
        vehicle_kind: str,
        marker_rect: NormalizedRect | None,
    ) -> list[TrackedRegion]:
        return self._target_detector.detect_targets(frame, time_ms, vehicle_kind, marker_rect)

    def _select_analysis_roi(
        self,
        frame: Any,
        marker_rect: NormalizedRect | None,
        target_box: NormalizedRect | None,
    ) -> tuple[Any, NormalizedRect | None]:
        if target_box:
            return crop_image(frame, target_box), target_box
        if marker_rect:
            return crop_image(frame, marker_rect), marker_rect
        return frame, None

    def _analyze_plate_candidates(
        self,
        frame: Any,
        time_ms: int,
        marker_rect: NormalizedRect | None,
        target_box: NormalizedRect | None,
        country_hints: list[str],
        options: AnalysisOptions,
        artifact_root: Path | None,
    ) -> tuple[list[PlateCandidate], FrameSample, PlateObservation | None]:
        working_image, crop_box = self._select_analysis_roi(frame, marker_rect, target_box)
        baseline_candidates = self._primary_recognizer.recognize(working_image, time_ms, crop_box)
        best_baseline = baseline_candidates[0] if baseline_candidates else None
        observation = None
        crop_candidates: list[PlateCandidate] = []

        if best_baseline and best_baseline.box is not None:
            observation = self._plate_preprocessor.prepare(
                frame,
                time_ms,
                target_box,
                best_baseline.box,
                options,
                artifact_root,
            )
            if observation is not None:
                crop_candidates = self._recognize_observation_crop(
                    observation,
                    time_ms,
                    best_baseline.box,
                    country_hints,
                    options,
                )
                observation.ocr_candidates = crop_candidates
        elif marker_rect is not None and target_box is None and _looks_like_plate_roi(marker_rect):
            observation = self._plate_preprocessor.prepare(
                frame,
                time_ms,
                None,
                marker_rect,
                options,
                artifact_root,
            )
            if observation is not None:
                crop_candidates = self._recognize_observation_crop(
                    observation,
                    time_ms,
                    marker_rect,
                    country_hints,
                    options,
                    extra_diagnostics={'directPlateRoi': True},
                )
                for candidate in crop_candidates:
                    candidate.confidence = max(candidate.confidence, min(1.0, candidate.confidence * 1.06))
                observation.ocr_candidates = crop_candidates

        candidates = self._rank_sample_candidates(baseline_candidates, crop_candidates, observation)
        best_candidate = candidates[0] if candidates else best_baseline
        sample_quality = (
            observation.quality
            if observation is not None and observation.quality is not None
            else best_candidate.quality if best_candidate else self._quality_scorer.score(working_image, None)
        )
        sample = FrameSample(
            id=f'sample-{time_ms}',
            time_ms=time_ms,
            target_box=target_box,
            plate_box=(observation.plate_box if observation is not None else None) or (best_candidate.box if best_candidate else None),
            quality=sample_quality,
            candidates=candidates[:6],
            image_path=(observation.artifact_paths.get('working') if observation is not None else None),
            diagnostics={
                'analysisOptions': options.to_payload(),
                'baselineCandidateCount': len(baseline_candidates),
                'ocrCandidateCount': len(crop_candidates),
                'baselineCandidates': [
                    {
                        'text': candidate.text,
                        'confidence': candidate.confidence,
                        'source': candidate.source,
                    }
                    for candidate in baseline_candidates[: options.max_plate_candidates]
                ],
                'ocrCandidates': [
                    {
                        'text': candidate.text,
                        'confidence': candidate.confidence,
                        'source': candidate.source,
                        'diagnostics': candidate.diagnostics,
                    }
                    for candidate in crop_candidates[: max(options.max_plate_candidates, 3)]
                ],
                'plateProcessing': observation.diagnostics if observation is not None else None,
            },
        )
        return candidates, sample, observation

    def _recognize_observation_crop(
        self,
        observation: PlateObservation,
        time_ms: int,
        plate_box: NormalizedRect | None,
        country_hints: list[str],
        options: AnalysisOptions,
        extra_diagnostics: dict[str, Any] | None = None,
    ) -> list[PlateCandidate]:
        diagnostics_extra = dict(extra_diagnostics or {})
        crop_candidates = self._primary_recognizer.recognize_plate_crop(
            observation.working_image,
            time_ms,
            plate_box,
            country_hints,
            options.ocr_models(),
        )
        for candidate in crop_candidates:
            candidate.diagnostics = {
                **(candidate.diagnostics or {}),
                **diagnostics_extra,
                'ocrVariant': 'working',
            }

        if crop_candidates:
            return crop_candidates

        for variant_name, variant_image in [
            ('enhanced', observation.enhanced_image),
            ('rectified', observation.rectified_image),
            ('original', observation.original_image),
        ]:
            if variant_image is None or getattr(variant_image, 'size', 0) == 0 or variant_image is observation.working_image:
                continue
            variant_candidates = self._primary_recognizer.recognize_plate_crop(
                variant_image,
                time_ms,
                plate_box,
                country_hints,
                options.ocr_models(),
            )
            for candidate in variant_candidates:
                candidate.diagnostics = {
                    **(candidate.diagnostics or {}),
                    **diagnostics_extra,
                    'ocrVariant': variant_name,
                }
            crop_candidates.extend(variant_candidates)

        return crop_candidates

    def _aggregate_candidates(
        self,
        samples: list[FrameSample],
        observations: list[PlateObservation],
        country_hints: list[str],
        options: AnalysisOptions,
        artifact_root: Path | None,
    ) -> tuple[list[PlateCandidate], dict[str, Any]]:
        source_weights = {
            'baseline': 0.96,
            'fused': 1.08,
            'legacy-vote': 1.0,
            'fused-char': 1.12,
            'fused-image': 1.16,
        }
        aggregated: dict[str, dict[str, Any]] = {}
        candidate_pool: list[PlateCandidate] = []

        for sample in samples:
            for candidate in sample.candidates:
                candidate_pool.append(candidate)

        char_fused_candidate = self._fuse_by_character_position(samples)
        if char_fused_candidate is not None:
            candidate_pool.append(char_fused_candidate)

        legacy_candidate = self._legacy_vote_candidate(samples)
        if legacy_candidate is not None:
            candidate_pool.append(legacy_candidate)

        fused_image_candidates, fused_image_diagnostics = self._fuse_aligned_plate_images(
            observations,
            country_hints,
            options,
            artifact_root,
        )
        candidate_pool.extend(fused_image_candidates)

        for candidate in candidate_pool:
            text = normalize_plate_text(candidate.text)
            if not text:
                continue
            source_key = candidate.source.split(':', 1)[0]
            quality_weight = candidate.quality.overall_score if candidate.quality else 0.55
            taiwan_prior = float((candidate.diagnostics or {}).get('taiwanPrior') or 1.0)
            weight = candidate.confidence * quality_weight * source_weights.get(source_key, 1.0) * taiwan_prior

            current = aggregated.get(text)
            if current is None:
                aggregated[text] = {
                    'weight': weight,
                    'supportFrames': {candidate.frame_time_ms} if candidate.frame_time_ms is not None else set(),
                    'best_raw_confidence': candidate.confidence,
                    'candidate': PlateCandidate(
                        id=f'candidate-{len(aggregated)}',
                        text=text,
                        confidence=weight,
                        source='fused',
                        frame_time_ms=candidate.frame_time_ms,
                        country_code=candidate.country_code,
                        box=candidate.box,
                        quality=candidate.quality,
                        diagnostics={
                            'supportFrames': [candidate.frame_time_ms] if candidate.frame_time_ms is not None else [],
                            'sources': [candidate.source],
                        },
                    ),
                }
                continue

            current['weight'] += weight
            if candidate.frame_time_ms is not None:
                current['supportFrames'].add(candidate.frame_time_ms)
            diagnostics = current['candidate'].diagnostics or {'supportFrames': [], 'sources': []}
            diagnostics['supportFrames'] = sorted(time for time in current['supportFrames'] if time is not None)
            diagnostics['sources'] = sorted({*diagnostics.get('sources', []), candidate.source})
            current['candidate'].diagnostics = diagnostics
            if candidate.confidence >= current['best_raw_confidence']:
                current['best_raw_confidence'] = candidate.confidence
                current['candidate'].frame_time_ms = candidate.frame_time_ms
                current['candidate'].country_code = candidate.country_code
                current['candidate'].box = candidate.box
                current['candidate'].quality = candidate.quality

        ranked = sorted(aggregated.values(), key=lambda item: item['weight'], reverse=True)
        if not ranked:
            return [], {
                'fusionMode': options.fusion_mode,
                'candidatePoolSize': len(candidate_pool),
                'fusedImage': fused_image_diagnostics,
            }

        best_weight = max(item['weight'] for item in ranked) or 1.0
        fused_candidates: list[PlateCandidate] = []
        for item in ranked[:8]:
            candidate = item['candidate']
            candidate.confidence = max(0.0, min(1.0, item['weight'] / best_weight))
            fused_candidates.append(candidate)

        return fused_candidates, {
            'fusionMode': options.fusion_mode,
            'candidatePoolSize': len(candidate_pool),
            'charFusionApplied': char_fused_candidate is not None,
            'legacyVoteApplied': legacy_candidate is not None,
            'fusedImage': fused_image_diagnostics,
        }

    def _resolve_sample_step_ms(
        self,
        interval: dict[str, int],
        requested_every_ms: int | None,
        requested_max_samples: int | None,
    ) -> int:
        start_ms = int(interval['startMs'])
        end_ms = int(interval['endMs'])
        duration_ms = max(0, end_ms - start_ms)
        max_samples = max(4, min(int(requested_max_samples or 18), 48))

        if duration_ms == 0:
            return max(120, int(requested_every_ms or 120))

        return requested_every_ms or max(120, int(duration_ms / max_samples))

    def _sample_times(
        self,
        interval: dict[str, int],
        requested_every_ms: int | None,
        requested_max_samples: int | None,
    ) -> list[int]:
        start_ms = int(interval['startMs'])
        end_ms = int(interval['endMs'])
        duration_ms = max(0, end_ms - start_ms)
        max_samples = max(4, min(int(requested_max_samples or 18), 48))

        if duration_ms == 0:
            return [start_ms]

        sample_every_ms = self._resolve_sample_step_ms(interval, requested_every_ms, requested_max_samples)
        times = list(range(start_ms, end_ms + 1, sample_every_ms))
        if times[-1] != end_ms:
            times.append(end_ms)
        return times[:max_samples]

    def _match_anchor_target(
        self,
        detections: list[TrackedRegion],
        selected_target_box: NormalizedRect | None,
    ) -> TrackedRegion | None:
        if not detections:
            return None
        if not selected_target_box:
            return detections[0]

        ranked = sorted(
            detections,
            key=lambda candidate: (
                candidate.box.intersection_over_union(selected_target_box),
                -candidate.box.center_distance(selected_target_box),
                candidate.confidence,
            ),
            reverse=True,
        )
        return ranked[0]

    def _match_tracked_target(
        self,
        detections: list[TrackedRegion],
        previous_box: NormalizedRect | None,
    ) -> TrackedRegion | None:
        if not detections:
            return None
        if previous_box is None:
            return detections[0]

        ranked = sorted(
            detections,
            key=lambda candidate: (
                candidate.box.intersection_over_union(previous_box),
                -candidate.box.center_distance(previous_box),
                candidate.confidence,
            ),
            reverse=True,
        )
        return ranked[0]

    def _track_target_across_interval(
        self,
        source_path: str,
        interval: dict[str, int],
        anchor_time_ms: int,
        vehicle_kind: str,
        selected_target_box: NormalizedRect | None,
        sample_every_ms: int | None,
        max_samples: int | None,
        options: AnalysisOptions,
    ) -> tuple[list[TrackedRegion], dict[str, Any]]:
        start_ms = int(interval['startMs'])
        end_ms = int(interval['endMs'])
        sample_times = sorted(set(self._sample_times(interval, sample_every_ms, max_samples)))
        sample_time_set = set(sample_times)
        sample_step_ms = self._resolve_sample_step_ms(interval, sample_every_ms, max_samples)

        if start_ms <= anchor_time_ms <= end_ms and anchor_time_ms not in sample_time_set:
            sample_times.append(anchor_time_ms)
            sample_times.sort()
            sample_time_set.add(anchor_time_ms)

        if options.tracker_mode != 'legacy':
            tracked_frames, diagnostics = self._tracker.track(
                source_path,
                interval,
                anchor_time_ms,
                vehicle_kind,
                selected_target_box,
                sample_times,
                options,
            )
            return tracked_frames, diagnostics

        anchor_frame = self._frame_reader.read_frame(source_path, anchor_time_ms)
        anchor_detections = self._detect_targets(anchor_frame, anchor_time_ms, vehicle_kind, None)
        anchor_region = self._match_anchor_target(anchor_detections, selected_target_box)
        seed_box = anchor_region.box if anchor_region else selected_target_box

        bridge_times: set[int] = set()
        if anchor_time_ms < start_ms:
            bridge_times.update(range(anchor_time_ms + sample_step_ms, start_ms, sample_step_ms))
        elif anchor_time_ms > end_ms:
            bridge_times.update(range(anchor_time_ms - sample_step_ms, end_ms, -sample_step_ms))

        traversal_times = sample_time_set | bridge_times
        backward_times = sorted((time_ms for time_ms in traversal_times if time_ms < anchor_time_ms), reverse=True)
        forward_times = sorted(time_ms for time_ms in traversal_times if time_ms > anchor_time_ms)

        tracked_before: list[TrackedRegion] = []
        previous_box = seed_box
        for time_ms in backward_times:
            frame = self._frame_reader.read_frame(source_path, time_ms)
            detections = self._detect_targets(frame, time_ms, vehicle_kind, None)
            chosen = self._match_tracked_target(detections, previous_box)
            if chosen is None:
                continue

            previous_box = chosen.box
            if time_ms in sample_time_set:
                tracked_before.append(chosen)

        tracked_after: list[TrackedRegion] = []
        previous_box = seed_box
        for time_ms in forward_times:
            frame = self._frame_reader.read_frame(source_path, time_ms)
            detections = self._detect_targets(frame, time_ms, vehicle_kind, None)
            chosen = self._match_tracked_target(detections, previous_box)
            if chosen is None:
                continue

            previous_box = chosen.box
            if time_ms in sample_time_set:
                tracked_after.append(chosen)

        tracked_frames: list[TrackedRegion] = list(reversed(tracked_before))
        if anchor_time_ms in sample_time_set and anchor_region is not None:
            tracked_frames.append(anchor_region)
        tracked_frames.extend(tracked_after)
        diagnostics = {
            'trackerMode': 'legacy',
            'matchedFrames': len(tracked_frames),
            'missedFrames': 0,
            'averageMatchScore': 0.0,
            'anchorDetected': anchor_region is not None,
        }
        return tracked_frames, diagnostics

    def _calibrate_interval_target_boxes(
        self,
        tracked_frames: list[TrackedRegion],
        anchor_time_ms: int,
        selected_target_box: NormalizedRect | None,
    ) -> dict[int, NormalizedRect]:
        if selected_target_box is None or not tracked_frames:
            return {}

        anchor_frame = next((frame for frame in tracked_frames if frame.time_ms == anchor_time_ms), None)
        if anchor_frame is None:
            anchor_frame = min(tracked_frames, key=lambda frame: abs(frame.time_ms - anchor_time_ms))

        anchor_box = anchor_frame.box if anchor_frame is not None else None
        if anchor_box is None or anchor_box.width <= 0.0 or anchor_box.height <= 0.0:
            return {}

        anchor_width = max(anchor_box.width, 1e-6)
        anchor_height = max(anchor_box.height, 1e-6)
        left_ratio = (anchor_box.x - selected_target_box.x) / anchor_width
        top_ratio = (anchor_box.y - selected_target_box.y) / anchor_height
        right_ratio = ((selected_target_box.x + selected_target_box.width) - (anchor_box.x + anchor_box.width)) / anchor_width
        bottom_ratio = ((selected_target_box.y + selected_target_box.height) - (anchor_box.y + anchor_box.height)) / anchor_height

        calibrated: dict[int, NormalizedRect] = {}
        for tracked_frame in tracked_frames:
            raw_box = tracked_frame.box
            x1 = clamp(raw_box.x - (left_ratio * raw_box.width), 0.0, 1.0)
            y1 = clamp(raw_box.y - (top_ratio * raw_box.height), 0.0, 1.0)
            x2 = clamp(raw_box.x + raw_box.width + (right_ratio * raw_box.width), min(1.0, x1 + 0.01), 1.0)
            y2 = clamp(raw_box.y + raw_box.height + (bottom_ratio * raw_box.height), min(1.0, y1 + 0.01), 1.0)
            calibrated[tracked_frame.time_ms] = NormalizedRect(
                x=x1,
                y=y1,
                width=x2 - x1,
                height=y2 - y1,
            )

        return calibrated

    def _build_track_payload(self, tracked_frames: list[TrackedRegion], diagnostics: dict[str, Any]) -> list[TargetTrack]:
        if not tracked_frames:
            return []
        average_confidence = sum(frame.confidence for frame in tracked_frames) / len(tracked_frames)
        return [
            TargetTrack(
                id='tracked-target-0',
                class_name=tracked_frames[0].class_name,
                label=f'{tracked_frames[0].class_name} {tracked_frames[0].time_ms}ms',
                confidence=average_confidence,
                frames=tracked_frames,
                diagnostics=diagnostics,
            )
        ]

    def _rank_sample_candidates(
        self,
        baseline_candidates: list[PlateCandidate],
        crop_candidates: list[PlateCandidate],
        observation: PlateObservation | None,
    ) -> list[PlateCandidate]:
        aggregated: dict[str, PlateCandidate] = {}
        for candidate in [*baseline_candidates, *crop_candidates]:
            text = normalize_plate_text(candidate.text)
            if not text:
                continue
            quality_weight = candidate.quality.overall_score if candidate.quality else (observation.quality.overall_score if observation and observation.quality else 0.55)
            taiwan_prior = float((candidate.diagnostics or {}).get('taiwanPrior') or 1.0)
            source_weight = 1.04 if candidate.source.startswith('ocr:') else 0.96
            candidate.confidence = max(0.0, min(1.0, candidate.confidence * (0.72 + (quality_weight * 0.28)) * source_weight * taiwan_prior))

            current = aggregated.get(text)
            if current is None or candidate.confidence >= current.confidence:
                aggregated[text] = candidate

        return sorted(
            aggregated.values(),
            key=lambda candidate: (
                candidate.confidence,
                candidate.quality.overall_score if candidate.quality else 0.0,
            ),
            reverse=True,
        )

    def _legacy_vote_candidate(self, samples: list[FrameSample]) -> PlateCandidate | None:
        weighted_by_text: dict[str, float] = {}
        representative: PlateCandidate | None = None
        for sample in samples:
            candidate = sample.candidates[0] if sample.candidates else None
            if candidate is None:
                continue
            text = normalize_plate_text(candidate.text)
            if not text:
                continue
            weighted_by_text[text] = weighted_by_text.get(text, 0.0) + candidate.confidence
            if representative is None or candidate.confidence > representative.confidence:
                representative = candidate

        if not weighted_by_text or representative is None:
            return None
        fused_text = max(weighted_by_text.items(), key=lambda item: item[1])[0]
        return PlateCandidate(
            id='legacy-vote-0',
            text=fused_text,
            confidence=max(weighted_by_text.values()) / max(sum(weighted_by_text.values()), 1.0),
            source='legacy-vote',
            frame_time_ms=representative.frame_time_ms,
            country_code=representative.country_code,
            box=representative.box,
            quality=representative.quality,
            diagnostics={'supportTexts': weighted_by_text},
        )

    def _fuse_by_character_position(self, samples: list[FrameSample]) -> PlateCandidate | None:
        length_votes: dict[int, float] = {}
        best_candidate: PlateCandidate | None = None
        for sample in samples:
            candidate = sample.candidates[0] if sample.candidates else None
            if candidate is None:
                continue
            text = normalize_plate_text(candidate.text)
            if not text:
                continue
            weight = candidate.confidence * (candidate.quality.overall_score if candidate.quality else 0.55)
            length_votes[len(text)] = length_votes.get(len(text), 0.0) + weight
            if best_candidate is None or candidate.confidence > best_candidate.confidence:
                best_candidate = candidate

        if not length_votes or best_candidate is None:
            return None

        target_length = max(length_votes.items(), key=lambda item: item[1])[0]
        position_votes: list[dict[str, float]] = [dict() for _ in range(target_length)]
        support_frames: list[int] = []

        for sample in samples:
            candidate = sample.candidates[0] if sample.candidates else None
            if candidate is None:
                continue
            text = normalize_plate_text(candidate.text)
            if not text or abs(len(text) - target_length) > 1:
                continue
            char_confidences = list((candidate.diagnostics or {}).get('charConfidences') or [])
            sample_weight = candidate.confidence * (candidate.quality.overall_score if candidate.quality else 0.55)
            for index, character in enumerate(text[:target_length]):
                character_weight = sample_weight * (float(char_confidences[index]) if index < len(char_confidences) else 1.0)
                position_votes[index][character] = position_votes[index].get(character, 0.0) + character_weight
            if candidate.frame_time_ms is not None:
                support_frames.append(candidate.frame_time_ms)

        if any(not votes for votes in position_votes):
            return None

        fused_text = ''.join(max(votes.items(), key=lambda item: item[1])[0] for votes in position_votes)
        confidence = sum(max(votes.values()) / max(sum(votes.values()), 1.0) for votes in position_votes) / len(position_votes)
        return PlateCandidate(
            id='fused-char-0',
            text=fused_text,
            confidence=confidence,
            source='fused-char',
            frame_time_ms=best_candidate.frame_time_ms,
            country_code=best_candidate.country_code,
            box=best_candidate.box,
            quality=best_candidate.quality,
            diagnostics={'supportFrames': sorted(set(support_frames)), 'targetLength': target_length},
        )

    def _fuse_aligned_plate_images(
        self,
        observations: list[PlateObservation],
        country_hints: list[str],
        options: AnalysisOptions,
        artifact_root: Path | None,
    ) -> tuple[list[PlateCandidate], dict[str, Any]]:
        if len(observations) < 2 or self._dependencies.cv2 is None or self._dependencies.numpy is None:
            return [], {'applied': False, 'reason': 'insufficient-observations'}

        cv2 = self._dependencies.cv2
        numpy = self._dependencies.numpy
        reference = max(observations, key=lambda observation: observation.quality.overall_score if observation.quality else 0.0)
        reference_image = reference.working_image
        if reference_image is None or getattr(reference_image, 'size', 0) == 0:
            return [], {'applied': False, 'reason': 'empty-reference'}

        reference_height, reference_width = reference_image.shape[:2]
        accum = reference_image.astype('float32')
        total_weight = 1.0
        support = 1
        alignment_scores: list[float] = [1.0]

        for observation in observations:
            if observation is reference:
                continue
            candidate_image = observation.working_image
            if candidate_image is None or getattr(candidate_image, 'size', 0) == 0:
                continue
            resized = cv2.resize(candidate_image, (reference_width, reference_height), interpolation=cv2.INTER_LANCZOS4)
            aligned, score = self._align_plate_to_reference(reference_image, resized)
            if aligned is None or score < options.min_alignment_score:
                continue

            weight = max(observation.quality.overall_score if observation.quality else 0.55, 0.2) * max(score, 0.2)
            accum += aligned.astype('float32') * weight
            total_weight += weight
            support += 1
            alignment_scores.append(score)

        if support < 2:
            return [], {'applied': False, 'reason': 'insufficient-aligned'}

        fused_image = (accum / max(total_weight, 1.0)).clip(0, 255).astype('uint8')
        if artifact_root is not None:
            fused_path = artifact_root / 'fused-image.png'
            cv2.imwrite(str(fused_path), fused_image)

        fused_candidates = self._primary_recognizer.recognize_plate_crop(
            fused_image,
            reference.time_ms,
            reference.plate_box,
            country_hints,
            options.ocr_models()[:2],
        )
        for candidate in fused_candidates:
            if candidate.source.startswith('ocr:'):
                candidate.source = f'fused-image:{candidate.source.split(":", 1)[1]}'
            candidate.diagnostics = (candidate.diagnostics or {}) | {
                'supportFrames': support,
                'meanAlignmentScore': sum(alignment_scores) / len(alignment_scores),
            }

        return fused_candidates, {
            'applied': True,
            'supportFrames': support,
            'meanAlignmentScore': sum(alignment_scores) / len(alignment_scores),
        }

    def _align_plate_to_reference(self, reference_image: Any, candidate_image: Any) -> tuple[Any | None, float]:
        cv2 = self._dependencies.cv2
        numpy = self._dependencies.numpy
        if cv2 is None or numpy is None:
            return None, 0.0

        reference_gray = cv2.cvtColor(reference_image, cv2.COLOR_BGR2GRAY).astype('float32') / 255.0
        candidate_gray = cv2.cvtColor(candidate_image, cv2.COLOR_BGR2GRAY).astype('float32') / 255.0
        warp_matrix = numpy.eye(2, 3, dtype='float32')
        criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 35, 1e-4)

        try:
            score, warp_matrix = cv2.findTransformECC(reference_gray, candidate_gray, warp_matrix, cv2.MOTION_AFFINE, criteria)
            aligned = cv2.warpAffine(
                candidate_image,
                warp_matrix,
                (reference_image.shape[1], reference_image.shape[0]),
                flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
            )
            return aligned, float(score)
        except Exception:
            try:
                (shift_x, shift_y), response = cv2.phaseCorrelate(reference_gray, candidate_gray)
                translation = numpy.array([[1.0, 0.0, shift_x], [0.0, 1.0, shift_y]], dtype='float32')
                aligned = cv2.warpAffine(candidate_image, translation, (reference_image.shape[1], reference_image.shape[0]))
                return aligned, float(response)
            except Exception:
                return None, 0.0


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


def _evaluate_interval_localization(
    sample_payloads: list[Any],
    ground_truth_frames: list[Any],
    tolerance_ms: int,
) -> dict[str, Any]:
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


def _apply_reliability_selection(
    candidates: list[PlateCandidate],
    samples: list[FrameSample],
    country_hints: list[str],
    options: AnalysisOptions,
    interval_mode: bool,
) -> tuple[list[PlateCandidate], str | None, dict[str, Any]]:
    if not candidates:
        return [], None, {
            'acceptedCandidateId': None,
            'suggestedCandidateId': None,
            'fallbackCandidateId': None,
            'reviewRequired': True,
            'usedFallback': False,
            'reasons': ['no-candidate'],
        }

    ordered_candidates = list(candidates)
    top_candidate = ordered_candidates[0]
    fallback_candidate = _best_sample_candidate(samples, country_hints)
    accepted_margin = max(0.0, top_candidate.confidence - (ordered_candidates[1].confidence if len(ordered_candidates) > 1 else 0.0))

    review_reasons = [] if not options.enable_reliability_gates else _review_reasons(
        top_candidate,
        accepted_margin,
        country_hints,
        options,
        interval_mode,
    )
    suggested_candidate = top_candidate
    used_fallback = False
    if review_reasons and fallback_candidate is not None and fallback_candidate.id != top_candidate.id:
        top_score = _candidate_reliability_score(top_candidate, country_hints)
        fallback_score = _candidate_reliability_score(fallback_candidate, country_hints)
        format_advantage = _plate_format_score(fallback_candidate.text, country_hints) - _plate_format_score(top_candidate.text, country_hints)
        if fallback_score >= top_score + 0.05 or format_advantage >= 0.2:
            suggested_candidate = fallback_candidate
            used_fallback = True
            review_reasons = [] if not options.enable_reliability_gates else _review_reasons(
                suggested_candidate,
                max(0.0, suggested_candidate.confidence - top_candidate.confidence),
                country_hints,
                options,
                interval_mode,
            )

    if all(candidate.id != suggested_candidate.id for candidate in ordered_candidates):
        ordered_candidates.insert(0, suggested_candidate)
    else:
        ordered_candidates.sort(key=lambda candidate: 0 if candidate.id == suggested_candidate.id else 1)

    review_required = bool(review_reasons)
    accepted_candidate_id = None if review_required else suggested_candidate.id
    selection_diagnostics = {
        'acceptedCandidateId': accepted_candidate_id,
        'suggestedCandidateId': suggested_candidate.id,
        'fallbackCandidateId': fallback_candidate.id if fallback_candidate is not None else None,
        'topCandidateId': top_candidate.id,
        'reviewRequired': review_required,
        'usedFallback': used_fallback,
        'reasons': review_reasons,
        'acceptedMargin': accepted_margin,
        'suggestedConfidence': suggested_candidate.confidence,
        'supportFrameCount': _candidate_support_frame_count(suggested_candidate),
        'formatScore': _plate_format_score(suggested_candidate.text, country_hints),
    }

    for candidate in ordered_candidates:
        candidate.diagnostics = {
            **(candidate.diagnostics or {}),
            'selection': {
                'isAccepted': candidate.id == accepted_candidate_id,
                'isSuggested': candidate.id == suggested_candidate.id,
                'reviewRequired': review_required,
                'usedFallback': used_fallback and candidate.id == suggested_candidate.id,
                'reasons': review_reasons if candidate.id == suggested_candidate.id else [],
            },
        }
    return ordered_candidates[:8], accepted_candidate_id, selection_diagnostics


def _review_reasons(
    candidate: PlateCandidate,
    accepted_margin: float,
    country_hints: list[str],
    options: AnalysisOptions,
    interval_mode: bool,
) -> list[str]:
    reasons: list[str] = []
    if candidate.confidence < options.min_accepted_confidence:
        reasons.append('low-confidence')
    if accepted_margin < options.min_candidate_margin:
        reasons.append('low-margin')
    if interval_mode and _candidate_support_frame_count(candidate) < options.min_interval_support_frames:
        reasons.append('insufficient-support')
    if _uses_taiwan_hint(country_hints) and _plate_format_score(candidate.text, country_hints) < 0.65:
        reasons.append('format-mismatch')
    return reasons


def _best_sample_candidate(samples: list[FrameSample], country_hints: list[str]) -> PlateCandidate | None:
    best_candidate: PlateCandidate | None = None
    best_score = 0.0
    for sample in samples:
        for candidate in sample.candidates:
            score = _candidate_reliability_score(candidate, country_hints)
            if best_candidate is None or score > best_score:
                best_candidate = candidate
                best_score = score
    return best_candidate


def _candidate_reliability_score(candidate: PlateCandidate, country_hints: list[str]) -> float:
    quality_score = candidate.quality.overall_score if candidate.quality is not None else 0.0
    support_score = min(_candidate_support_frame_count(candidate), 4) / 4.0
    format_score = _plate_format_score(candidate.text, country_hints)
    return (
        (candidate.confidence * 0.58)
        + (quality_score * 0.20)
        + (support_score * 0.12)
        + (format_score * 0.10)
    )


def _candidate_support_frame_count(candidate: PlateCandidate) -> int:
    diagnostics = candidate.diagnostics or {}
    support_frames = diagnostics.get('supportFrames')
    if isinstance(support_frames, list):
        return len({int(frame) for frame in support_frames if isinstance(frame, (int, float))})
    if isinstance(support_frames, (int, float)):
        return max(1, int(support_frames))
    return 1 if candidate.frame_time_ms is not None else 0


def _plate_format_score(text: str | None, country_hints: list[str]) -> float:
    normalized = normalize_plate_text(text)
    if not normalized:
        return 0.0
    if _uses_taiwan_hint(country_hints):
        if len(normalized) < 5 or len(normalized) > 7:
            return 0.2
        if any(character in {'I', 'O', 'Q'} for character in normalized):
            return 0.55
        if normalized[:2].isalpha() and normalized[-4:].isdigit():
            return 1.0
        if normalized[:3].isalpha() and normalized[-4:].isdigit() and len(normalized) == 7:
            return 0.94
        if normalized[:4].isalpha() and normalized[-3:].isdigit() and len(normalized) == 7:
            return 0.9
        if normalized[:3].isdigit() and normalized[-4:].isalpha() and len(normalized) == 7:
            return 0.82
        if any(character.isalpha() for character in normalized) and any(character.isdigit() for character in normalized):
            return 0.68
        return 0.35
    return 1.0 if 5 <= len(normalized) <= 8 else 0.5


def _uses_taiwan_hint(country_hints: list[str]) -> bool:
    return any(str(hint).upper() in {'TW', 'TWN', 'TAIWAN'} for hint in country_hints)


def _looks_like_plate_roi(rect: NormalizedRect) -> bool:
    if rect.height <= 0 or rect.width <= 0:
        return False
    aspect_ratio = rect.width / max(rect.height, 1e-6)
    return rect.area() <= 0.12 and 1.1 <= aspect_ratio <= 12.0


def build_default_application(runtime_script: Path) -> LprRuntimeApplication:
    dependencies = DependencyRegistry.load(runtime_script)
    frame_reader = OpenCvFrameReader(dependencies)
    quality_scorer = QualityScorer(dependencies)
    model_registry = ModelRegistry(dependencies)
    target_detector = UltralyticsTargetDetector(model_registry)
    primary_recognizer = FastAlprPlateRecognizer(model_registry, quality_scorer)
    return LprRuntimeApplication(
        dependencies=dependencies,
        frame_reader=frame_reader,
        target_detector=target_detector,
        primary_recognizer=primary_recognizer,
        quality_scorer=quality_scorer,
    )
