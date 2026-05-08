from __future__ import annotations

from pathlib import Path
from typing import Any

from traffic_lpr_runtime.domain.errors import RuntimeFailure
from traffic_lpr_runtime.domain.interfaces import FrameReader, PlateRecognizer, TargetDetector
from traffic_lpr_runtime.domain.models import FrameSample, PlateCandidate, TargetTrack, TrackedRegion
from traffic_lpr_runtime.domain.text import normalize_plate_text
from traffic_lpr_runtime.domain.value_objects import NormalizedRect, crop_image
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

    def dispatch(self, subcommand: str, payload: dict[str, Any]) -> dict[str, Any]:
        if subcommand == 'status':
            return self.status()
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
        candidates, sample = self._analyze_plate_candidates(
            frame,
            time_ms,
            marker_rect,
            target_box,
        )
        return {
            'detections': [detection.to_payload() for detection in detections],
            'sample': sample.to_payload(),
            'candidates': [candidate.to_payload() for candidate in candidates[:8]],
            'runtime': self.status(),
        }

    def analyze_interval(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._dependencies.ensure_ready()
        selected_target_box = NormalizedRect.from_payload(payload.get('selectedTargetBox'))
        if selected_target_box is None:
            raise RuntimeFailure('Range analysis requires a selected target on the anchor frame.')

        tracked_frames = self._track_target_across_interval(
            payload['sourcePath'],
            payload['interval'],
            int(payload['anchorTimeMs']),
            payload.get('targetVehicleKind', 'vehicle'),
            selected_target_box,
            payload.get('sampleEveryMs'),
            payload.get('maxSamples'),
        )

        samples: list[FrameSample] = []
        for tracked_frame in tracked_frames:
            frame = self._frame_reader.read_frame(payload['sourcePath'], tracked_frame.time_ms)
            _, sample = self._analyze_plate_candidates(
                frame,
                tracked_frame.time_ms,
                None,
                tracked_frame.box,
            )
            samples.append(sample)

        candidates = self._aggregate_candidates(samples)
        accepted_candidate_id = candidates[0].id if candidates else None
        summary = (
            f'{len(samples)} samples, {len(candidates)} fused candidate(s), best={candidates[0].text}'
            if candidates
            else f'{len(samples)} samples, no confident plate candidate.'
        )

        return {
            'targetTracks': [track.to_payload() for track in self._build_track_payload(tracked_frames)],
            'samples': [sample.to_payload() for sample in samples],
            'candidates': [candidate.to_payload() for candidate in candidates],
            'acceptedCandidateId': accepted_candidate_id,
            'summary': summary,
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
    ) -> tuple[list[PlateCandidate], FrameSample]:
        working_image, crop_box = self._select_analysis_roi(frame, marker_rect, target_box)
        candidates = self._primary_recognizer.recognize(working_image, time_ms, crop_box)

        candidates.sort(
            key=lambda candidate: (
                candidate.confidence,
                candidate.quality.overall_score if candidate.quality else 0.0,
            ),
            reverse=True,
        )

        best_candidate = candidates[0] if candidates else None
        sample_quality = best_candidate.quality if best_candidate else self._quality_scorer.score(working_image, None)
        sample = FrameSample(
            id=f'sample-{time_ms}',
            time_ms=time_ms,
            target_box=target_box,
            plate_box=best_candidate.box if best_candidate else None,
            quality=sample_quality,
            candidates=candidates[:6],
            image_path=None,
        )
        return candidates, sample

    def _aggregate_candidates(self, samples: list[FrameSample]) -> list[PlateCandidate]:
        source_weights = {'baseline': 1.0, 'fused': 1.05}
        aggregated: dict[str, dict[str, Any]] = {}

        for sample in samples:
            for candidate in sample.candidates:
                text = normalize_plate_text(candidate.text)
                if not text:
                    continue
                quality_weight = candidate.quality.overall_score if candidate.quality else 0.55
                weight = candidate.confidence * quality_weight * source_weights.get(candidate.source, 1.0)

                current = aggregated.get(text)
                if current is None:
                    aggregated[text] = {
                        'weight': weight,
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
                        ),
                    }
                    continue

                current['weight'] += weight
                if candidate.confidence >= current['best_raw_confidence']:
                    current['best_raw_confidence'] = candidate.confidence
                    current['candidate'].frame_time_ms = candidate.frame_time_ms
                    current['candidate'].country_code = candidate.country_code
                    current['candidate'].box = candidate.box
                    current['candidate'].quality = candidate.quality

        ranked = sorted(aggregated.values(), key=lambda item: item['weight'], reverse=True)
        if not ranked:
            return []

        best_weight = max(item['weight'] for item in ranked) or 1.0
        fused_candidates: list[PlateCandidate] = []
        for item in ranked[:8]:
            candidate = item['candidate']
            candidate.confidence = max(0.0, min(1.0, item['weight'] / best_weight))
            fused_candidates.append(candidate)

        return fused_candidates

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
    ) -> list[TrackedRegion]:
        start_ms = int(interval['startMs'])
        end_ms = int(interval['endMs'])
        sample_times = sorted(set(self._sample_times(interval, sample_every_ms, max_samples)))
        sample_time_set = set(sample_times)
        sample_step_ms = self._resolve_sample_step_ms(interval, sample_every_ms, max_samples)

        if start_ms <= anchor_time_ms <= end_ms and anchor_time_ms not in sample_time_set:
            sample_times.append(anchor_time_ms)
            sample_times.sort()
            sample_time_set.add(anchor_time_ms)

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
        return tracked_frames

    def _build_track_payload(self, tracked_frames: list[TrackedRegion]) -> list[TargetTrack]:
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
            )
        ]


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
