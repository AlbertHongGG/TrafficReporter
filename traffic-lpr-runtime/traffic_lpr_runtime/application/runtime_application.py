from __future__ import annotations

from pathlib import Path
from typing import Any

from traffic_lpr_runtime.domain.errors import RuntimeFailure
from traffic_lpr_runtime.domain.interfaces import FrameReader, PlateRecognizer, TargetDetector
from traffic_lpr_runtime.domain.models import FrameSample, PlateCandidate, TargetTrack, TrackedRegion
from traffic_lpr_runtime.domain.text import character_error_rate, normalize_plate_text
from traffic_lpr_runtime.domain.value_objects import NormalizedRect, crop_image
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
        return {
            'detections': [detection.to_payload() for detection in detections],
            'sample': sample.to_payload(),
            'candidates': [candidate.to_payload() for candidate in candidates[:8]],
            'runtime': self.status(),
            'diagnostics': {
                'analysisOptions': options.to_payload(),
                'artifactRoot': str(artifact_root) if artifact_root else None,
                'observation': observation.diagnostics if observation else None,
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

        samples: list[FrameSample] = []
        observations: list[PlateObservation] = []
        for tracked_frame in tracked_frames:
            frame = self._frame_reader.read_frame(payload['sourcePath'], tracked_frame.time_ms)
            _, sample, observation = self._analyze_plate_candidates(
                frame,
                tracked_frame.time_ms,
                None,
                tracked_frame.box,
                payload.get('countryHints') or [],
                options,
                artifact_root / f'sample-{tracked_frame.time_ms}' if artifact_root else None,
            )
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
        accepted_candidate_id = candidates[0].id if candidates else None
        summary = (
            f'{len(samples)} samples, {len(candidates)} fused candidate(s), best={candidates[0].text}, tracker={track_diagnostics.get("trackerMode", "legacy")}'
            if candidates
            else f'{len(samples)} samples, no confident plate candidate.'
        )

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

        for index, case_payload in enumerate(cases):
            mode = str(case_payload.get('mode') or 'interval')
            case_id = str(case_payload.get('id') or f'case-{index + 1}')
            expected_text = normalize_plate_text(case_payload.get('expectedText'))

            if mode == 'frame':
                response = self.analyze_frame(case_payload)
                candidates = response.get('candidates') or []
            else:
                response = self.analyze_interval(case_payload)
                candidates = response.get('candidates') or []

            ranked_texts = [normalize_plate_text(candidate.get('text')) for candidate in candidates if candidate.get('text')]
            ranked_sources = [str(candidate.get('source') or '') for candidate in candidates if candidate.get('text')]
            best_text = ranked_texts[0] if ranked_texts else ''
            best_source = ranked_sources[0] if ranked_sources else ''
            exact_match = bool(expected_text and best_text == expected_text)
            top3_match = bool(expected_text and expected_text in ranked_texts[:3])
            case_character_error_rate = character_error_rate(best_text, expected_text)

            exact_matches += 1 if exact_match else 0
            top3_matches += 1 if top3_match else 0
            total_character_error_rate += case_character_error_rate
            if best_source:
                source_wins[best_source] = source_wins.get(best_source, 0) + 1

            for tag in list(case_payload.get('tags') or []):
                tag_entry = tag_metrics.setdefault(str(tag), {'total': 0.0, 'exact': 0.0, 'top3': 0.0, 'cer': 0.0})
                tag_entry['total'] += 1.0
                tag_entry['exact'] += 1.0 if exact_match else 0.0
                tag_entry['top3'] += 1.0 if top3_match else 0.0
                tag_entry['cer'] += case_character_error_rate

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
                    'summary': response.get('summary') or '',
                    'tags': list(case_payload.get('tags') or []),
                }
            )

        total_cases = len(benchmark_results)
        metrics = {
            'totalCases': total_cases,
            'exactMatchRate': exact_matches / total_cases,
            'top3MatchRate': top3_matches / total_cases,
            'meanCharacterErrorRate': total_character_error_rate / total_cases,
            'sourceWinCounts': source_wins,
            'tagBreakdown': {
                tag: {
                    'totalCases': int(values['total']),
                    'exactMatchRate': values['exact'] / max(values['total'], 1.0),
                    'top3MatchRate': values['top3'] / max(values['total'], 1.0),
                    'meanCharacterErrorRate': values['cer'] / max(values['total'], 1.0),
                }
                for tag, values in sorted(tag_metrics.items())
            },
        }
        summary = (
            f"{total_cases} cases, exact={metrics['exactMatchRate']:.1%}, "
            f"top3={metrics['top3MatchRate']:.1%}, cer={metrics['meanCharacterErrorRate']:.3f}"
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
                crop_candidates = self._primary_recognizer.recognize_plate_crop(
                    observation.working_image,
                    time_ms,
                    best_baseline.box,
                    country_hints,
                    options.ocr_models(),
                )
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
