from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from traffic_lpr_runtime.application.pipeline_support import AnalysisOptions
from traffic_lpr_runtime.application.preprocessing import PlateObservation
from traffic_lpr_runtime.application.provenance import build_analysis_provenance
from traffic_lpr_runtime.application.review_state import build_review_state
from traffic_lpr_runtime.domain.errors import RuntimeFailure
from traffic_lpr_runtime.domain.models import FrameSample, PlateCandidate, TargetTrack, TrackedRegion
from traffic_lpr_runtime.domain.value_objects import NormalizedRect


def _boxes_remain_anchored(anchor_box: NormalizedRect | None, selected_target_box: NormalizedRect | None) -> bool:
    if anchor_box is None or selected_target_box is None:
        return False

    iou = anchor_box.intersection_over_union(selected_target_box)
    center_distance = anchor_box.center_distance(selected_target_box)
    area_similarity = min(anchor_box.area(), selected_target_box.area()) / max(anchor_box.area(), selected_target_box.area(), 1e-6)
    return iou >= 0.1 or (center_distance <= 0.12 and area_similarity >= 0.45)


def _resolve_interval_anchor_box(
    tracked_frames: list[TrackedRegion],
    calibrated_target_boxes: dict[int, NormalizedRect],
    anchor_time_ms: int,
) -> NormalizedRect | None:
    if anchor_time_ms in calibrated_target_boxes:
        return calibrated_target_boxes[anchor_time_ms]

    anchor_frame = next((frame for frame in tracked_frames if frame.time_ms == anchor_time_ms), None)
    return anchor_frame.box if anchor_frame is not None else None


def _request_run_id(payload: dict[str, Any]) -> str | None:
    value = payload.get('requestId')
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _selected_target_track_id(payload: dict[str, Any], track_diagnostics: dict[str, Any]) -> str | None:
    for value in [
        payload.get('selectedTargetTrackId'),
        track_diagnostics.get('canonicalTargetId'),
        track_diagnostics.get('anchorDetectionId'),
    ]:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _tracking_identity_review_reasons(track_diagnostics: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    identity_breaks = int(track_diagnostics.get('identityBreaks') or 0)
    reassociated_frames = int(track_diagnostics.get('reassociatedFrames') or 0)
    detection_fallback_frames = int(track_diagnostics.get('detectionFallbackFrames') or 0)

    if identity_breaks > 0:
        reasons.append('tracking identity became ambiguous across the interval')
    if track_diagnostics.get('terminatedEarly') is True:
        reasons.append('tracking stopped early after the target drifted')
    if detection_fallback_frames > 0 and reassociated_frames > 0:
        reasons.append('tracker had to reacquire the target from fresh detections')
    return reasons


def _merge_reasons(existing: list[str], additions: list[str]) -> list[str]:
    merged: list[str] = []
    for reason in [*existing, *additions]:
        if reason and reason not in merged:
            merged.append(reason)
    return merged


class TargetScanWorkflow:
    def __init__(
        self,
        ensure_ready: Callable[[], None],
        status: Callable[[], dict[str, Any]],
        frame_reader: Any,
        detect_targets: Callable[[Any, int, str, NormalizedRect | None], list[TrackedRegion]],
    ) -> None:
        self._ensure_ready = ensure_ready
        self._status = status
        self._frame_reader = frame_reader
        self._detect_targets = detect_targets

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
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
            'runtime': self._status(),
        }


class FrameAnalysisWorkflow:
    def __init__(
        self,
        ensure_ready: Callable[[], None],
        status: Callable[[], dict[str, Any]],
        runtime_root: Callable[[], Path],
        frame_reader: Any,
        detect_targets: Callable[[Any, int, str, NormalizedRect | None], list[TrackedRegion]],
        match_anchor_target: Callable[[list[TrackedRegion], NormalizedRect | None], TrackedRegion | None],
        analyze_plate_candidates: Callable[[Any, int, NormalizedRect | None, NormalizedRect | None, list[str], AnalysisOptions, Path | None], tuple[list[PlateCandidate], FrameSample, PlateObservation | None]],
        apply_reliability_selection: Callable[[list[PlateCandidate], list[FrameSample], list[str], AnalysisOptions, bool], tuple[list[PlateCandidate], str | None, dict[str, Any]]],
    ) -> None:
        self._ensure_ready = ensure_ready
        self._status = status
        self._runtime_root = runtime_root
        self._frame_reader = frame_reader
        self._detect_targets = detect_targets
        self._match_anchor_target = match_anchor_target
        self._analyze_plate_candidates = analyze_plate_candidates
        self._apply_reliability_selection = apply_reliability_selection

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        time_ms = int(payload['timeMs'])
        options = AnalysisOptions.from_payload(payload)
        artifact_root = options.resolve_artifact_root(self._runtime_root(), f'frame-{time_ms}', _request_run_id(payload))
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
        candidates, accepted_candidate_id, selection_diagnostics = self._apply_reliability_selection(
            candidates,
            [sample],
            payload.get('countryHints') or [],
            options,
            False,
        )
        sample.diagnostics = {
            **(sample.diagnostics or {}),
            'selection': selection_diagnostics,
        }
        runtime_status = self._status()
        return {
            'detections': [detection.to_payload() for detection in detections],
            'sample': sample.to_payload(),
            'candidates': [candidate.to_payload() for candidate in candidates[:8]],
            'acceptedCandidateId': accepted_candidate_id,
            'review': build_review_state(candidates, accepted_candidate_id, selection_diagnostics),
            'provenance': build_analysis_provenance('analyze-frame', payload, runtime_status),
            'runtime': runtime_status,
            'diagnostics': {
                'analysisOptions': options.to_payload(),
                'artifactRoot': str(artifact_root) if artifact_root else None,
                'observation': observation.diagnostics if observation else None,
                'selection': selection_diagnostics,
            },
        }


class IntervalAnalysisWorkflow:
    def __init__(
        self,
        ensure_ready: Callable[[], None],
        status: Callable[[], dict[str, Any]],
        runtime_root: Callable[[], Path],
        frame_reader: Any,
        track_target_across_interval: Callable[[str, dict[str, Any], int, str, NormalizedRect | None, int | None, int | None, AnalysisOptions], tuple[list[TrackedRegion], dict[str, Any]]],
        calibrate_interval_target_boxes: Callable[[list[TrackedRegion], int, NormalizedRect | None], dict[int, NormalizedRect]],
        analyze_plate_candidates: Callable[[Any, int, NormalizedRect | None, NormalizedRect | None, list[str], AnalysisOptions, Path | None], tuple[list[PlateCandidate], FrameSample, PlateObservation | None]],
        aggregate_candidates: Callable[[list[FrameSample], list[PlateObservation], list[str], AnalysisOptions, Path | None], tuple[list[PlateCandidate], dict[str, Any]]],
        apply_reliability_selection: Callable[[list[PlateCandidate], list[FrameSample], list[str], AnalysisOptions, bool], tuple[list[PlateCandidate], str | None, dict[str, Any]]],
        build_track_payload: Callable[[list[TrackedRegion], dict[str, Any]], list[TargetTrack]],
    ) -> None:
        self._ensure_ready = ensure_ready
        self._status = status
        self._runtime_root = runtime_root
        self._frame_reader = frame_reader
        self._track_target_across_interval = track_target_across_interval
        self._calibrate_interval_target_boxes = calibrate_interval_target_boxes
        self._analyze_plate_candidates = analyze_plate_candidates
        self._aggregate_candidates = aggregate_candidates
        self._apply_reliability_selection = apply_reliability_selection
        self._build_track_payload = build_track_payload

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        options = AnalysisOptions.from_payload(payload)
        artifact_root = options.resolve_artifact_root(self._runtime_root(), 'interval', _request_run_id(payload))
        interval = payload['interval']
        anchor_time_ms = int(payload['anchorTimeMs'])
        start_ms = int(interval['startMs'])
        end_ms = int(interval['endMs'])
        selected_target_box = NormalizedRect.from_payload(payload.get('selectedTargetBox'))
        if selected_target_box is None:
            raise RuntimeFailure('Range analysis requires a selected target on the anchor frame.')
        if anchor_time_ms < start_ms or anchor_time_ms > end_ms:
            raise RuntimeFailure('Range analysis requires the selected target anchor to stay inside the requested interval.')

        tracked_frames, track_diagnostics = self._track_target_across_interval(
            payload['sourcePath'],
            interval,
            anchor_time_ms,
            payload.get('targetVehicleKind', 'vehicle'),
            selected_target_box,
            payload.get('sampleEveryMs'),
            payload.get('maxSamples'),
            options,
        )
        canonical_target_track_id = _selected_target_track_id(payload, track_diagnostics)
        if canonical_target_track_id is not None:
            track_diagnostics = {
                **track_diagnostics,
                'canonicalTargetId': canonical_target_track_id,
            }
        calibrated_target_boxes = self._calibrate_interval_target_boxes(
            tracked_frames,
            anchor_time_ms,
            selected_target_box,
        )
        resolved_anchor_box = _resolve_interval_anchor_box(tracked_frames, calibrated_target_boxes, anchor_time_ms)
        if not _boxes_remain_anchored(resolved_anchor_box, selected_target_box):
            raise RuntimeFailure('Range analysis lost the selected target at the anchor frame. Reselect the vehicle on the intended frame and retry.')

        sample_options = options.for_interval_sample(sample_count_hint=len(tracked_frames))

        samples: list[FrameSample] = []
        observations: list[PlateObservation] = []
        for tracked_frame in tracked_frames:
            raw_tracking_box = tracked_frame.box
            calibrated_target_box = calibrated_target_boxes.get(tracked_frame.time_ms)
            analysis_target_box = calibrated_target_box or raw_tracking_box
            frame = self._frame_reader.read_frame(payload['sourcePath'], tracked_frame.time_ms)
            _, sample, observation = self._analyze_plate_candidates(
                frame,
                tracked_frame.time_ms,
                None,
                analysis_target_box,
                payload.get('countryHints') or [],
                sample_options,
                artifact_root / f'sample-{tracked_frame.time_ms}' if artifact_root else None,
            )
            if calibrated_target_box is not None:
                tracked_frame.diagnostics = {
                    **(tracked_frame.diagnostics or {}),
                    'analysisBox': analysis_target_box.to_payload(),
                    'rawTrackingBox': raw_tracking_box.to_payload(),
                    'calibratedBox': calibrated_target_box.to_payload(),
                }
                tracked_frame.box = calibrated_target_box
            sample.diagnostics = {
                **(sample.diagnostics or {}),
                'analysisTargetBox': analysis_target_box.to_payload(),
                'rawTrackingBox': raw_tracking_box.to_payload(),
                'tracking': tracked_frame.diagnostics,
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
        candidates, accepted_candidate_id, selection_diagnostics = self._apply_reliability_selection(
            candidates,
            samples,
            payload.get('countryHints') or [],
            options,
            True,
        )
        identity_review_reasons = _tracking_identity_review_reasons(track_diagnostics)
        if identity_review_reasons:
            accepted_candidate_id = None
            selection_diagnostics = {
                **selection_diagnostics,
                'acceptedCandidateId': None,
                'reviewRequired': True,
                'reasons': _merge_reasons(
                    [reason for reason in selection_diagnostics.get('reasons') or [] if isinstance(reason, str)],
                    identity_review_reasons,
                ),
                'tracking': track_diagnostics,
            }
        if candidates:
            suggested_candidate = next(
                (candidate for candidate in candidates if candidate.id == selection_diagnostics.get('suggestedCandidateId')),
                candidates[0],
            )
            summary = (
                f'{len(samples)} samples, {len(candidates)} fused candidate(s), '
                f'best={suggested_candidate.text}, tracker={track_diagnostics.get("trackerMode", "legacy")}'
            )
            if selection_diagnostics.get('reviewRequired'):
                summary = f'{summary}, review needed.'
        else:
            summary = f'{len(samples)} samples, no confident plate candidate.'

        runtime_status = self._status()
        return {
            'targetTracks': [track.to_payload() for track in self._build_track_payload(tracked_frames, track_diagnostics)],
            'samples': [sample.to_payload() for sample in samples],
            'candidates': [candidate.to_payload() for candidate in candidates],
            'acceptedCandidateId': accepted_candidate_id,
            'review': build_review_state(candidates, accepted_candidate_id, selection_diagnostics),
            'provenance': build_analysis_provenance('analyze-interval', payload, runtime_status),
            'summary': summary,
            'runtime': runtime_status,
            'diagnostics': {
                'analysisOptions': options.to_payload(),
                'artifactRoot': str(artifact_root) if artifact_root else None,
                'tracker': track_diagnostics,
                'fusion': fusion_diagnostics,
                'selection': selection_diagnostics,
            },
        }
