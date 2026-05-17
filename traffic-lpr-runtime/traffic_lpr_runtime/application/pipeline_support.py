from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from traffic_lpr_runtime.application.analysis_profiles import resolve_analysis_profile_options
from traffic_lpr_runtime.domain.models import TrackedRegion
from traffic_lpr_runtime.domain.value_objects import NormalizedRect, clamp
from traffic_lpr_runtime.infrastructure.dependencies import DependencyRegistry


DEFAULT_OCR_MODEL_NAMES = [
    'cct-xs-v2-global-model',
    'cct-s-v2-global-model',
    'global-plates-mobile-vit-v2-model',
]


@dataclass(slots=True)
class AnalysisOptions:
    analysis_profile_id: str = 'balanced'
    enable_developer_diagnostics: bool = False
    persist_artifacts: bool = False
    artifact_dir: str | None = None
    tracker_mode: str = 'botsort'
    fusion_mode: str = 'aligned-char'
    restoration_mode: str = 'mambairv2'
    enable_rectification: bool = True
    enable_enhancement: bool = True
    enable_recognizer_comparison: bool = True
    debug_tag: str | None = None
    ocr_model_names: list[str] = field(default_factory=lambda: list(DEFAULT_OCR_MODEL_NAMES))
    max_plate_candidates: int = 3
    tracker_high_confidence: float = 0.35
    tracker_low_confidence: float = 0.15
    max_tracking_gap: int = 3
    min_alignment_score: float = 0.05
    enable_reliability_gates: bool = True
    min_accepted_confidence: float = 0.62
    min_candidate_margin: float = 0.08
    min_interval_support_frames: int = 2

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> 'AnalysisOptions':
        request_payload = payload or {}
        analysis_profile_id, profile_options = resolve_analysis_profile_options(
            _to_optional_str(request_payload.get('analysisProfileId')),
            request_payload.get('enableDeveloperDiagnostics') is True,
        )
        raw = {
            **profile_options,
            **dict(request_payload.get('analysisOptions') or {}),
        }
        return cls(
            analysis_profile_id=analysis_profile_id,
            enable_developer_diagnostics=request_payload.get('enableDeveloperDiagnostics') is True,
            persist_artifacts=bool(raw.get('persistArtifacts') or False),
            artifact_dir=_to_optional_str(raw.get('artifactDir')),
            tracker_mode=_to_optional_str(raw.get('trackerMode')) or 'botsort',
            fusion_mode=_to_optional_str(raw.get('fusionMode')) or 'aligned-char',
            restoration_mode=_to_optional_str(raw.get('restorationMode')) or 'mambairv2',
            enable_rectification=raw.get('enableRectification', True) is not False,
            enable_enhancement=raw.get('enableEnhancement', True) is not False,
            enable_recognizer_comparison=raw.get('enableRecognizerComparison', True) is not False,
            debug_tag=_to_optional_str(raw.get('debugTag')),
            ocr_model_names=[str(name) for name in (raw.get('ocrModelNames') or DEFAULT_OCR_MODEL_NAMES)],
            max_plate_candidates=max(1, min(int(raw.get('maxPlateCandidates') or 3), 6)),
            tracker_high_confidence=float(raw.get('trackerHighConfidence') or 0.35),
            tracker_low_confidence=float(raw.get('trackerLowConfidence') or 0.15),
            max_tracking_gap=max(1, min(int(raw.get('maxTrackingGap') or 3), 8)),
            min_alignment_score=float(raw.get('minAlignmentScore') or 0.05),
            enable_reliability_gates=raw.get('enableReliabilityGates', True) is not False,
            min_accepted_confidence=float(raw.get('minAcceptedConfidence') or 0.62),
            min_candidate_margin=float(raw.get('minCandidateMargin') or 0.08),
            min_interval_support_frames=max(1, min(int(raw.get('minIntervalSupportFrames') or 2), 8)),
        )

    def resolve_artifact_root(self, runtime_root: Path, suffix: str | None = None) -> Path | None:
        if not self.persist_artifacts:
            return None
        if self.artifact_dir:
            root = Path(self.artifact_dir)
        else:
            timestamp = datetime.now(UTC).strftime('%Y%m%d-%H%M%S')
            base_name = self.debug_tag or 'analysis'
            root = runtime_root / '.runtime' / 'analysis' / f'{timestamp}-{base_name}'
        if suffix:
            root = root / suffix
        root.mkdir(parents=True, exist_ok=True)
        return root

    def ocr_models(self) -> list[str]:
        return self.ocr_model_names if self.enable_recognizer_comparison else self.ocr_model_names[:1]

    def to_payload(self) -> dict[str, Any]:
        return {
            'analysisProfileId': self.analysis_profile_id,
            'enableDeveloperDiagnostics': self.enable_developer_diagnostics,
            'persistArtifacts': self.persist_artifacts,
            'artifactDir': self.artifact_dir,
            'trackerMode': self.tracker_mode,
            'fusionMode': self.fusion_mode,
            'restorationMode': self.restoration_mode,
            'enableRectification': self.enable_rectification,
            'enableEnhancement': self.enable_enhancement,
            'enableRecognizerComparison': self.enable_recognizer_comparison,
            'debugTag': self.debug_tag,
            'ocrModelNames': self.ocr_model_names,
            'maxPlateCandidates': self.max_plate_candidates,
            'trackerHighConfidence': self.tracker_high_confidence,
            'trackerLowConfidence': self.tracker_low_confidence,
            'maxTrackingGap': self.max_tracking_gap,
            'minAlignmentScore': self.min_alignment_score,
            'enableReliabilityGates': self.enable_reliability_gates,
            'minAcceptedConfidence': self.min_accepted_confidence,
            'minCandidateMargin': self.min_candidate_margin,
            'minIntervalSupportFrames': self.min_interval_support_frames,
        }


@dataclass(slots=True)
class _TrackerState:
    reference_box: NormalizedRect | None
    last_box: NormalizedRect | None
    velocity: tuple[float, float, float, float]
    last_time_ms: int
    misses: int = 0


class _UltralyticsTrackerDetections:
    def __init__(self, xyxy: Any, confidence: Any, class_ids: Any, numpy_module: Any) -> None:
        self._numpy = numpy_module
        self.xyxy = self._as_rows(xyxy, 4)
        self.conf = self._as_vector(confidence)
        self.cls = self._as_vector(class_ids)
        self.xywh = self._to_xywh(self.xyxy)

    def __len__(self) -> int:
        return int(self.conf.shape[0])

    def __getitem__(self, index: Any) -> '_UltralyticsTrackerDetections':
        return _UltralyticsTrackerDetections(self.xyxy[index], self.conf[index], self.cls[index], self._numpy)

    def _as_rows(self, values: Any, width: int) -> Any:
        array = self._numpy.asarray(values, dtype='float32')
        if array.size == 0:
            return self._numpy.empty((0, width), dtype='float32')
        return array.reshape(-1, width).astype('float32')

    def _as_vector(self, values: Any) -> Any:
        array = self._numpy.asarray(values, dtype='float32')
        if array.size == 0:
            return self._numpy.empty((0,), dtype='float32')
        return array.reshape(-1).astype('float32')

    def _to_xywh(self, xyxy: Any) -> Any:
        if getattr(xyxy, 'size', 0) == 0:
            return self._numpy.empty((0, 4), dtype='float32')
        x1 = xyxy[:, 0]
        y1 = xyxy[:, 1]
        x2 = xyxy[:, 2]
        y2 = xyxy[:, 3]
        return self._numpy.stack(((x1 + x2) / 2.0, (y1 + y2) / 2.0, x2 - x1, y2 - y1), axis=1).astype('float32')


class TargetCentricTracker:
    def __init__(self, dependencies: DependencyRegistry, frame_reader: Any, target_detector: Any) -> None:
        self._dependencies = dependencies
        self._frame_reader = frame_reader
        self._target_detector = target_detector

    def track(
        self,
        source_path: str,
        interval: dict[str, int],
        anchor_time_ms: int,
        vehicle_kind: str,
        selected_target_box: NormalizedRect | None,
        sample_times: list[int],
        options: AnalysisOptions,
    ) -> tuple[list[TrackedRegion], dict[str, Any]]:
        tracker_mode = (options.tracker_mode or 'botsort').strip().lower()
        if tracker_mode in {'botsort', 'bot-sort', 'bytetrack', 'byte-track'}:
            return self._track_with_ultralytics_tracker(
                source_path,
                interval,
                anchor_time_ms,
                vehicle_kind,
                selected_target_box,
                sample_times,
                options,
            )

        anchor_frame = self._frame_reader.read_frame(source_path, anchor_time_ms)
        anchor_detections = self._target_detector.detect_targets(anchor_frame, anchor_time_ms, vehicle_kind, None)
        anchor_region = _select_best_anchor(anchor_detections, selected_target_box)
        seed_box = anchor_region.box if anchor_region else selected_target_box

        if seed_box is None:
            return [], {
                'trackerMode': options.tracker_mode,
                'matchedFrames': 0,
                'missedFrames': 0,
                'averageMatchScore': 0.0,
                'anchorDetected': False,
            }

        before, before_stats = self._walk(
            source_path,
            sorted([time_ms for time_ms in sample_times if time_ms < anchor_time_ms], reverse=True),
            anchor_time_ms,
            anchor_frame,
            vehicle_kind,
            seed_box,
            options,
        )
        after, after_stats = self._walk(
            source_path,
            sorted([time_ms for time_ms in sample_times if time_ms > anchor_time_ms]),
            anchor_time_ms,
            anchor_frame,
            vehicle_kind,
            seed_box,
            options,
        )

        tracked_frames = list(reversed(before))
        if anchor_region is not None and anchor_time_ms in sample_times:
            tracked_frames.append(anchor_region)
        tracked_frames.extend(after)

        scores = before_stats['scores'] + after_stats['scores']
        diagnostics = {
            'trackerMode': options.tracker_mode,
            'matchedFrames': len(tracked_frames),
            'missedFrames': before_stats['misses'] + after_stats['misses'],
            'averageMatchScore': (sum(scores) / len(scores)) if scores else 0.0,
            'anchorDetected': anchor_region is not None,
        }
        return tracked_frames, diagnostics

    def _track_with_ultralytics_tracker(
        self,
        source_path: str,
        interval: dict[str, int],
        anchor_time_ms: int,
        vehicle_kind: str,
        selected_target_box: NormalizedRect | None,
        sample_times: list[int],
        options: AnalysisOptions,
    ) -> tuple[list[TrackedRegion], dict[str, Any]]:
        traversal_times = self._tracker_times(interval, anchor_time_ms, sample_times)
        frame_rate = self._estimate_frame_rate(traversal_times)
        tracker = self._build_ultralytics_tracker(options, frame_rate)

        tracked_by_time: dict[int, list[TrackedRegion]] = {}
        anchor_track_id: str | None = None
        anchor_region: TrackedRegion | None = None

        for time_ms in traversal_times:
            frame = self._frame_reader.read_frame(source_path, time_ms)
            detections = self._target_detector.detect_targets(frame, time_ms, vehicle_kind, None)
            tracked_regions = self._update_ultralytics_tracker(tracker, frame, detections, time_ms)
            tracked_by_time[time_ms] = tracked_regions

            if time_ms == anchor_time_ms:
                anchor_region = _select_best_anchor(tracked_regions, selected_target_box)
                anchor_track_id = anchor_region.id if anchor_region is not None else None

        if anchor_track_id is None:
            return [], {
                'trackerMode': options.tracker_mode,
                'matchedFrames': 0,
                'missedFrames': len(sample_times),
                'averageMatchScore': 0.0,
                'anchorDetected': False,
                'frameRate': frame_rate,
            }

        tracked_frames: list[TrackedRegion] = []
        confidences: list[float] = []
        missed_frames = 0
        for time_ms in sorted(sample_times):
            matched = next((region for region in tracked_by_time.get(time_ms, []) if region.id == anchor_track_id), None)
            if matched is None:
                missed_frames += 1
                continue
            tracked_frames.append(matched)
            confidences.append(matched.confidence)

        diagnostics = {
            'trackerMode': options.tracker_mode,
            'matchedFrames': len(tracked_frames),
            'missedFrames': missed_frames,
            'averageMatchScore': (sum(confidences) / len(confidences)) if confidences else 0.0,
            'anchorDetected': anchor_region is not None,
            'anchorTrackId': anchor_track_id,
            'frameRate': frame_rate,
        }
        return tracked_frames, diagnostics

    def _tracker_times(self, interval: dict[str, int], anchor_time_ms: int, sample_times: list[int]) -> list[int]:
        start_ms = int(interval['startMs'])
        end_ms = int(interval['endMs'])
        traversal_times = set(sample_times)
        traversal_times.add(anchor_time_ms)
        if anchor_time_ms < start_ms:
            traversal_times.update(time_ms for time_ms in sample_times if time_ms >= start_ms)
        elif anchor_time_ms > end_ms:
            traversal_times.update(time_ms for time_ms in sample_times if time_ms <= end_ms)
        return sorted(traversal_times)

    def _estimate_frame_rate(self, traversal_times: list[int]) -> int:
        if len(traversal_times) < 2:
            return 30
        deltas = [max(current - previous, 1) for previous, current in zip(traversal_times, traversal_times[1:])]
        average_delta = sum(deltas) / len(deltas)
        return max(1, int(round(1000.0 / average_delta)))

    def _build_ultralytics_tracker(self, options: AnalysisOptions, frame_rate: int) -> Any:
        tracker_mode = (options.tracker_mode or 'botsort').strip().lower()
        if tracker_mode in {'bytetrack', 'byte-track'}:
            from ultralytics.trackers.byte_tracker import BYTETracker

            return BYTETracker(
                SimpleNamespace(
                    track_high_thresh=max(0.1, options.tracker_high_confidence),
                    track_low_thresh=max(0.01, min(options.tracker_low_confidence, options.tracker_high_confidence)),
                    new_track_thresh=max(0.1, options.tracker_high_confidence),
                    track_buffer=max(12, int(round(frame_rate * 2.5))),
                    match_thresh=0.82,
                    fuse_score=True,
                ),
                frame_rate=frame_rate,
            )

        from ultralytics.trackers.bot_sort import BOTSORT

        return BOTSORT(
            SimpleNamespace(
                track_high_thresh=max(0.1, options.tracker_high_confidence),
                track_low_thresh=max(0.01, min(options.tracker_low_confidence, options.tracker_high_confidence)),
                new_track_thresh=max(0.1, options.tracker_high_confidence),
                track_buffer=max(12, int(round(frame_rate * 2.5))),
                match_thresh=0.82,
                fuse_score=True,
                gmc_method='sparseOptFlow',
                proximity_thresh=0.5,
                appearance_thresh=0.25,
                with_reid=False,
                model='auto',
            ),
            frame_rate=frame_rate,
        )

    def _update_ultralytics_tracker(
        self,
        tracker: Any,
        frame: Any,
        detections: list[TrackedRegion],
        time_ms: int,
    ) -> list[TrackedRegion]:
        numpy = self._dependencies.numpy
        if numpy is None:
            return []

        tracker_inputs = self._build_tracker_detections(detections, frame)
        outputs = tracker.update(tracker_inputs, img=frame)
        if outputs is None or getattr(outputs, 'size', 0) == 0:
            return []

        frame_height, frame_width = frame.shape[:2]
        tracked_regions: list[TrackedRegion] = []
        for output in outputs:
            xyxy = output[:4]
            track_id = int(round(float(output[4])))
            confidence = float(output[5])
            class_id = int(round(float(output[6]))) if len(output) > 6 else -1
            detection_index = int(round(float(output[7]))) if len(output) > 7 else -1
            class_name = detections[detection_index].class_name if 0 <= detection_index < len(detections) else _tracker_class_name(class_id)
            tracked_regions.append(
                TrackedRegion(
                    id=f'track-{track_id}',
                    time_ms=time_ms,
                    box=NormalizedRect.from_xyxy(float(xyxy[0]), float(xyxy[1]), float(xyxy[2]), float(xyxy[3]), frame_width, frame_height),
                    confidence=confidence,
                    class_name=class_name,
                    diagnostics={
                        'trackerId': track_id,
                        'classId': class_id,
                        'detectionIndex': detection_index,
                    },
                )
            )

        tracked_regions.sort(key=lambda candidate: candidate.confidence, reverse=True)
        return tracked_regions

    def _build_tracker_detections(self, detections: list[TrackedRegion], frame: Any) -> _UltralyticsTrackerDetections:
        numpy = self._dependencies.numpy
        frame_height, frame_width = frame.shape[:2]
        boxes: list[list[float]] = []
        confidences: list[float] = []
        class_ids: list[float] = []

        for detection in detections:
            x1, y1, x2, y2 = detection.box.to_pixels(frame_width, frame_height)
            boxes.append([float(x1), float(y1), float(x2), float(y2)])
            confidences.append(float(detection.confidence))
            class_ids.append(float(_tracker_class_id(detection.class_name)))

        return _UltralyticsTrackerDetections(boxes, confidences, class_ids, numpy)

    def _walk(
        self,
        source_path: str,
        traversal_times: list[int],
        anchor_time_ms: int,
        anchor_frame: Any,
        vehicle_kind: str,
        seed_box: NormalizedRect,
        options: AnalysisOptions,
    ) -> tuple[list[TrackedRegion], dict[str, Any]]:
        tracked_frames: list[TrackedRegion] = []
        scores: list[float] = []
        total_misses = 0
        state = _TrackerState(
            reference_box=seed_box,
            last_box=seed_box,
            velocity=(0.0, 0.0, 0.0, 0.0),
            last_time_ms=anchor_time_ms,
        )
        previous_frame = anchor_frame

        for time_ms in traversal_times:
            frame = self._frame_reader.read_frame(source_path, time_ms)
            detections = self._target_detector.detect_targets(frame, time_ms, vehicle_kind, None)
            predicted_box, global_shift = self._predict_box(previous_frame, frame, state)
            chosen, score, match_diagnostics = self._associate(detections, predicted_box, state.last_box, options)
            if chosen is None:
                state.misses += 1
                total_misses += 1
                previous_frame = frame
                state.last_time_ms = time_ms
                if state.misses > options.max_tracking_gap:
                    state.last_box = predicted_box
                continue

            state.misses = 0
            state.velocity = _update_velocity(state.last_box, chosen.box, state.last_time_ms, time_ms, state.velocity)
            state.last_box = chosen.box
            chosen.diagnostics = {
                'matchScore': score,
                'match': match_diagnostics,
                'globalShift': global_shift,
            }
            tracked_frames.append(chosen)
            scores.append(score)
            previous_frame = frame
            state.last_time_ms = time_ms

        return tracked_frames, {'scores': scores, 'misses': total_misses}

    def _predict_box(
        self,
        previous_frame: Any,
        frame: Any,
        state: _TrackerState,
    ) -> tuple[NormalizedRect, dict[str, float]]:
        dx_norm, dy_norm, phase_score = self._estimate_global_shift(previous_frame, frame)
        dt = 1.0
        pred = _shift_rect(
            state.last_box or state.reference_box,
            dx_norm + (state.velocity[0] * dt),
            dy_norm + (state.velocity[1] * dt),
            state.velocity[2] * dt,
            state.velocity[3] * dt,
        )
        return pred, {'dx': dx_norm, 'dy': dy_norm, 'score': phase_score}

    def _estimate_global_shift(self, previous_frame: Any, frame: Any) -> tuple[float, float, float]:
        cv2 = self._dependencies.cv2
        numpy = self._dependencies.numpy
        if cv2 is None or numpy is None:
            return 0.0, 0.0, 0.0

        prev_gray = cv2.cvtColor(previous_frame, cv2.COLOR_BGR2GRAY)
        curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        target_size = (320, 180)
        prev_resized = cv2.resize(prev_gray, target_size).astype('float32')
        curr_resized = cv2.resize(curr_gray, target_size).astype('float32')
        try:
            (shift_x, shift_y), response = cv2.phaseCorrelate(prev_resized, curr_resized)
        except Exception:
            return 0.0, 0.0, 0.0

        frame_height, frame_width = frame.shape[:2]
        dx_norm = float(shift_x) / max(frame_width, 1)
        dy_norm = float(shift_y) / max(frame_height, 1)
        return dx_norm, dy_norm, float(response)

    def _associate(
        self,
        detections: list[TrackedRegion],
        predicted_box: NormalizedRect,
        previous_box: NormalizedRect | None,
        options: AnalysisOptions,
    ) -> tuple[TrackedRegion | None, float, dict[str, Any]]:
        ranked: list[tuple[float, TrackedRegion, dict[str, Any]]] = []
        for candidate in detections:
            predicted_iou = candidate.box.intersection_over_union(predicted_box)
            previous_iou = candidate.box.intersection_over_union(previous_box)
            center_distance = candidate.box.center_distance(predicted_box)
            area_similarity = min(candidate.box.area(), predicted_box.area()) / max(candidate.box.area(), predicted_box.area(), 0.0001)
            confidence_band = 1.0 if candidate.confidence >= options.tracker_high_confidence else 0.8
            score = (
                (predicted_iou * 0.52)
                + (previous_iou * 0.18)
                + (area_similarity * 0.15)
                + (candidate.confidence * 0.25 * confidence_band)
                - (center_distance * 0.35)
            )
            diagnostics = {
                'predictedIou': predicted_iou,
                'previousIou': previous_iou,
                'centerDistance': center_distance,
                'areaSimilarity': area_similarity,
                'confidenceBand': confidence_band,
            }
            ranked.append((score, candidate, diagnostics))

        ranked.sort(key=lambda item: item[0], reverse=True)
        if not ranked:
            return None, 0.0, {'reason': 'no-detections'}

        best_score, best_candidate, best_diagnostics = ranked[0]
        if best_score < 0.05:
            return None, best_score, {'reason': 'below-threshold'} | best_diagnostics
        return best_candidate, best_score, best_diagnostics


def _select_best_anchor(
    detections: list[TrackedRegion],
    selected_target_box: NormalizedRect | None,
) -> TrackedRegion | None:
    if not detections:
        return None
    if selected_target_box is None:
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


def _update_velocity(
    previous_box: NormalizedRect | None,
    current_box: NormalizedRect,
    previous_time_ms: int,
    current_time_ms: int,
    prior_velocity: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    if previous_box is None:
        return prior_velocity
    delta_time = max(abs(current_time_ms - previous_time_ms), 1)
    measured_velocity = (
        (current_box.x - previous_box.x) / delta_time,
        (current_box.y - previous_box.y) / delta_time,
        (current_box.width - previous_box.width) / delta_time,
        (current_box.height - previous_box.height) / delta_time,
    )
    return tuple((prior * 0.6) + (observed * 0.4) for prior, observed in zip(prior_velocity, measured_velocity, strict=True))


def _shift_rect(
    rect: NormalizedRect | None,
    delta_x: float,
    delta_y: float,
    delta_width: float,
    delta_height: float,
) -> NormalizedRect:
    if rect is None:
        return NormalizedRect(0.0, 0.0, 0.0, 0.0)
    x = clamp(rect.x + delta_x, 0.0, 1.0)
    y = clamp(rect.y + delta_y, 0.0, 1.0)
    width = clamp(rect.width + delta_width, 0.01, 1.0 - x)
    height = clamp(rect.height + delta_height, 0.01, 1.0 - y)
    return NormalizedRect(x=x, y=y, width=width, height=height)


def _tracker_class_id(class_name: str) -> int:
    return {
        'car': 2,
        'motorcycle': 3,
        'bus': 5,
        'truck': 7,
    }.get(str(class_name), 0)


def _tracker_class_name(class_id: int) -> str:
    return {
        2: 'car',
        3: 'motorcycle',
        5: 'bus',
        7: 'truck',
    }.get(int(class_id), 'vehicle')


def _to_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None