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
from traffic_lpr_runtime.protocol import emit_runtime_progress


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
    selected_target_box: NormalizedRect | None,
) -> NormalizedRect | None:
    anchor_frame = next((frame for frame in tracked_frames if frame.time_ms == anchor_time_ms), None)
    raw_anchor_box = anchor_frame.box if anchor_frame is not None else None
    calibrated_anchor_box = calibrated_target_boxes.get(anchor_time_ms)
    analysis_anchor_box, _ = _resolve_analysis_target_box(raw_anchor_box, calibrated_anchor_box, selected_target_box)
    return analysis_anchor_box


def _resolve_analysis_target_box(
    raw_tracking_box: NormalizedRect | None,
    calibrated_target_box: NormalizedRect | None,
    selected_target_box: NormalizedRect | None,
    sample_time_ms: int | None = None,
    anchor_time_ms: int | None = None,
) -> tuple[NormalizedRect | None, str]:
    if (
        selected_target_box is not None
        and sample_time_ms is not None
        and anchor_time_ms is not None
        and sample_time_ms < anchor_time_ms
        and anchor_time_ms - sample_time_ms <= 180
    ):
        return selected_target_box, 'selected-anchor-fallback'

    if calibrated_target_box is None:
        return raw_tracking_box, 'raw-tracking'

    if raw_tracking_box is not None and _boxes_remain_anchored(raw_tracking_box, calibrated_target_box):
        return calibrated_target_box, 'calibrated'

    if raw_tracking_box is None and selected_target_box is not None and _boxes_remain_anchored(selected_target_box, calibrated_target_box):
        return calibrated_target_box, 'calibrated'

    if raw_tracking_box is not None:
        return raw_tracking_box, 'raw-tracking-fallback'
    return calibrated_target_box, 'calibrated'


def _request_run_id(payload: dict[str, Any]) -> str | None:
    value = payload.get('requestId')
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _selected_target_track_id(payload: dict[str, Any], track_diagnostics: dict[str, Any]) -> str | None:
    for value in [
        payload.get('selectedTargetTrackId'),
        track_diagnostics.get('canonicalTargetId'),
        track_diagnostics.get('anchorDetectionId'),
    ]:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _is_evidence_sample_frame(frame: TrackedRegion) -> bool:
    diagnostics = frame.diagnostics or {}
    return diagnostics.get('isEvidenceSample') is True


def _mark_selected_for_evidence_analysis(
    tracked_frames: list[TrackedRegion],
    selected_times: set[int],
) -> list[TrackedRegion]:
    for frame in tracked_frames:
        frame.diagnostics = {
            **(frame.diagnostics or {}),
            'selectedForEvidenceAnalysis': frame.time_ms in selected_times,
        }
    return [frame for frame in tracked_frames if frame.time_ms in selected_times]


def _select_interval_evidence_frames(tracked_frames: list[TrackedRegion], options: AnalysisOptions) -> list[TrackedRegion]:
    if not tracked_frames:
        return []

    scheduled_frames = [frame for frame in tracked_frames if _is_evidence_sample_frame(frame)]
    if options.temporal_evidence_mode == 'scheduled':
        selected_frames = scheduled_frames or tracked_frames
        return _mark_selected_for_evidence_analysis(
            tracked_frames,
            {frame.time_ms for frame in selected_frames},
        )

    anchor_frame = next((frame for frame in tracked_frames if (frame.diagnostics or {}).get('isAnchorFrame') is True), None)
    if scheduled_frames:
        selected_times = {frame.time_ms for frame in scheduled_frames}
        if anchor_frame is not None:
            selected_times.add(anchor_frame.time_ms)
        return _mark_selected_for_evidence_analysis(tracked_frames, selected_times)

    evidence_budget = len(scheduled_frames) if scheduled_frames else len(tracked_frames)
    evidence_budget = max(1, min(evidence_budget, len(tracked_frames)))
    if evidence_budget >= len(tracked_frames):
        return _mark_selected_for_evidence_analysis(
            tracked_frames,
            {frame.time_ms for frame in tracked_frames},
        )

    chosen_by_time: dict[int, TrackedRegion] = {}

    def choose(frame: TrackedRegion | None) -> None:
        if frame is None:
            return
        chosen_by_time.setdefault(frame.time_ms, frame)

    choose(tracked_frames[0])
    choose(tracked_frames[-1])
    choose(next((frame for frame in tracked_frames if (frame.diagnostics or {}).get('isAnchorFrame') is True), None))

    hotspot_frames = [
        frame
        for frame in tracked_frames
        if (frame.diagnostics or {}).get('isMotionHotspot') is True
    ]
    for frame in sorted(
        hotspot_frames,
        key=lambda candidate: float((candidate.diagnostics or {}).get('localMotion') or 0.0),
        reverse=True,
    ):
        if len(chosen_by_time) >= evidence_budget:
            break
        choose(frame)

    ranked_frames = sorted(
        tracked_frames,
        key=lambda candidate: (
            float((candidate.diagnostics or {}).get('evidencePriority') or 0.0),
            candidate.confidence,
        ),
        reverse=True,
    )
    for frame in ranked_frames:
        if len(chosen_by_time) >= evidence_budget:
            break
        choose(frame)

    return _mark_selected_for_evidence_analysis(tracked_frames, set(chosen_by_time))


def _select_temporal_support_frames(
    tracked_frames: list[TrackedRegion],
    reference_time_ms: int,
    options: AnalysisOptions,
) -> list[TrackedRegion]:
    candidates = [
        frame
        for frame in tracked_frames
        if frame.time_ms != reference_time_ms and abs(frame.time_ms - reference_time_ms) <= options.temporal_window_ms
    ]
    candidates.sort(
        key=lambda frame: (
            abs(frame.time_ms - reference_time_ms),
            -float((frame.diagnostics or {}).get('evidencePriority') or 0.0),
            -frame.confidence,
        ),
    )
    return candidates[:max(0, options.temporal_neighbor_count - 1)]


def _build_sample_selection_payload(sample: FrameSample, tracked_frame: TrackedRegion) -> dict[str, Any]:
    reasons = [
        reason
        for reason in ((tracked_frame.diagnostics or {}).get('evidenceReasons') or [])
        if isinstance(reason, str)
    ]
    if sample.quality is not None and sample.quality.sharpness >= 0.72 and 'sharpness-peak' not in reasons:
        reasons.append('sharpness-peak')
    return {
        'selected': True,
        'priority': float((tracked_frame.diagnostics or {}).get('evidencePriority') or sample.quality.overall_score if sample.quality is not None else 0.0),
        'reasons': reasons,
    }


def _decision_source_for_candidate(candidate: PlateCandidate, sample: FrameSample | None) -> str:
    if candidate.source.startswith('fused-image:'):
        return 'fused-image'
    if candidate.source == 'fused-char':
        return 'fused-char'
    if candidate.source == 'legacy-vote':
        return 'legacy-vote'
    if sample is not None and sample.ocr_input is not None and sample.ocr_input.get('stage') == 'temporal-restored':
        return 'temporal-restored'
    if (candidate.diagnostics or {}).get('bestFrameCarryThrough') is True:
        return 'support-carry'
    return 'single-frame'


def _build_decision_trace(
    candidates: list[PlateCandidate],
    accepted_candidate_id: str | None,
    selection_diagnostics: dict[str, Any],
    samples: list[FrameSample],
    sequence_summary: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    candidate_id = accepted_candidate_id or selection_diagnostics.get('suggestedCandidateId')
    chosen_candidate = next((candidate for candidate in candidates if candidate.id == candidate_id), candidates[0] if candidates else None)
    if chosen_candidate is None:
        return None

    chosen_sample = None
    if chosen_candidate.frame_time_ms is not None:
        chosen_sample = next((sample for sample in samples if sample.time_ms == chosen_candidate.frame_time_ms), None)
    if chosen_sample is None:
        chosen_sample = next(
            (
                sample
                for sample in samples
                if any(candidate.id == chosen_candidate.id or candidate.text == chosen_candidate.text for candidate in sample.candidates)
            ),
            None,
        )

    support_frame_count = 1
    if chosen_sample is not None and chosen_sample.temporal_support is not None:
        support_frame_count = int(chosen_sample.temporal_support.get('supportFrameCount') or support_frame_count)
    else:
        support_frame_count = int((chosen_candidate.diagnostics or {}).get('supportFrameCount') or support_frame_count)

    agreement_ratio = (chosen_candidate.diagnostics or {}).get('sequenceSupportRatio')
    if agreement_ratio is None and sequence_summary:
        agreement_ratio = sequence_summary.get('persistenceRatio')

    stage = None
    if chosen_sample is not None and chosen_sample.ocr_input is not None:
        stage = chosen_sample.ocr_input.get('stage')

    return {
        'source': _decision_source_for_candidate(chosen_candidate, chosen_sample),
        'candidateId': chosen_candidate.id,
        'sampleId': chosen_sample.id if chosen_sample is not None else None,
        'frameTimeMs': chosen_candidate.frame_time_ms,
        'stage': stage,
        'supportFrameCount': support_frame_count,
        'agreementRatio': float(agreement_ratio) if isinstance(agreement_ratio, (int, float)) else None,
        'margin': float(selection_diagnostics.get('acceptedMargin')) if isinstance(selection_diagnostics.get('acceptedMargin'), (int, float)) else None,
    }


def _sequence_hard_review_reasons(sequence_summary: dict[str, Any], options: AnalysisOptions) -> list[str]:
    if not sequence_summary or options.sequence_review_mode == 'off':
        return []

    support_frame_count = _safe_int(sequence_summary.get('supportFrameCount'))
    reasons: list[str] = []

    if support_frame_count < options.min_interval_support_frames:
        reasons.append('too few interval samples produced readable plate support')

    return _merge_reasons([], reasons)


def _sequence_advisory_reasons(sequence_summary: dict[str, Any], options: AnalysisOptions) -> list[str]:
    if not sequence_summary or options.sequence_review_mode == 'off':
        return []

    sequence_tier = str(sequence_summary.get('sequenceTier') or 'fragmented')
    persistence_ratio = float(sequence_summary.get('persistenceRatio') or 0.0)
    gap_count = _safe_int(sequence_summary.get('supportFrameGapCount'))
    reasons: list[str] = []

    if sequence_tier == 'fragmented':
        reasons.append('sequence evidence stayed fragmented across the interval')
    if persistence_ratio < options.min_sequence_persistence:
        reasons.append('plate text did not remain stable across interval samples')
    if gap_count > options.max_sequence_gap_count:
        reasons.append('readable OCR evidence had large gaps across the interval')
    if options.sequence_review_mode == 'strict' and sequence_tier in {'drifting', 'gapped'}:
        reasons.append('sequence evidence drifted during the interval review path')
    elif options.sequence_review_mode == 'balanced' and sequence_tier == 'gapped':
        reasons.append('sequence evidence lost continuity across the interval')

    return _merge_reasons([], reasons)


def _tracking_identity_review_reasons(track_diagnostics: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    identity_breaks = int(track_diagnostics.get('identityBreaks') or 0)

    if identity_breaks > 0:
        reasons.append('tracking identity became ambiguous across the interval')
    return reasons


def _tracking_advisory_reasons(track_diagnostics: dict[str, Any], tracking_summary: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    reassociated_frames = int(track_diagnostics.get('reassociatedFrames') or 0)
    detection_fallback_frames = int(track_diagnostics.get('detectionFallbackFrames') or 0)

    if track_diagnostics.get('terminatedEarly') is True:
        reasons.append('tracking stopped early after the target drifted')
    if detection_fallback_frames > 0 and reassociated_frames > 0:
        reasons.append('tracker had to reacquire the target from fresh detections')

    degraded_reason = tracking_summary.get('degradedReason')
    if isinstance(degraded_reason, str) and degraded_reason.strip():
        reasons.append(degraded_reason.strip())
    return _merge_reasons([], reasons)


def _merge_reasons(existing: list[str], additions: list[str]) -> list[str]:
    merged: list[str] = []
    for reason in [*existing, *additions]:
        if reason and reason not in merged:
            merged.append(reason)
    return merged


def _emit_progress(progress: float, stage: str, detail: str, **extra: Any) -> None:
    emit_runtime_progress({
        'progress': progress,
        'stage': stage,
        'detail': detail,
        'done': False,
        'failed': False,
        **extra,
    })


def _tracking_tier(track_diagnostics: dict[str, Any], tracked_frame_count: int, anchor_ok: bool) -> str:
    if not anchor_ok:
        return 'anchor-invalid'
    if _safe_int(track_diagnostics.get('detectionFallbackFrames')) > 0:
        return 'detection-fallback'
    if tracked_frame_count <= 1:
        return 'anchor-only'
    if track_diagnostics.get('terminatedEarly') is True:
        return 'partial'
    return 'full'


def _anchor_status(
    selected_target_box: NormalizedRect | None,
    anchor_time_ms: int,
    start_ms: int,
    end_ms: int,
    anchor_box: NormalizedRect | None,
) -> str:
    if selected_target_box is None:
        return 'missing-selection'
    if anchor_time_ms < start_ms or anchor_time_ms > end_ms:
        return 'outside-interval'
    if anchor_box is None:
        return 'not-detected'
    if not _boxes_remain_anchored(anchor_box, selected_target_box):
        return 'mismatched'
    return 'valid'


def _build_tracking_summary(
    track_diagnostics: dict[str, Any],
    tracked_frame_count: int,
    requested_frame_count: int,
    anchor_ok: bool,
    anchor_status: str,
) -> dict[str, Any]:
    coverage_ratio = 0.0
    if requested_frame_count > 0:
        coverage_ratio = max(0.0, min(1.0, tracked_frame_count / requested_frame_count))
    tracking_tier = _tracking_tier(track_diagnostics, tracked_frame_count, anchor_ok)
    degraded_reason = None
    if tracking_tier == 'partial':
        degraded_reason = 'tracking stopped before covering the full interval'
    elif tracking_tier == 'detection-fallback':
        degraded_reason = 'tracking required fresh detection fallback to keep the target alive'
    elif tracking_tier == 'anchor-only':
        degraded_reason = 'only the anchor frame remained reliable across the interval'
    elif tracking_tier == 'anchor-invalid':
        degraded_reason = 'anchor validation drifted away from the selected target'
    return {
        'trackingTier': tracking_tier,
        'anchorStatus': 'degraded' if anchor_ok and tracking_tier != 'full' else anchor_status,
        'coverageRatio': coverage_ratio,
        'trackedFrameCount': tracked_frame_count,
        'requestedFrameCount': requested_frame_count,
        'degradedReason': degraded_reason,
        'terminatedEarly': track_diagnostics.get('terminatedEarly') is True,
    }


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
        options = AnalysisOptions.from_payload(payload).for_interactive_frame()
        artifact_root = options.resolve_artifact_root(self._runtime_root(), f'frame-{time_ms}', _request_run_id(payload))
        marker_rect = NormalizedRect.from_payload(payload.get('markerRect'))
        selected_target_box = NormalizedRect.from_payload(payload.get('selectedTargetBox'))
        _emit_progress(0.12, 'Frame', 'Reading the selected frame for interactive analysis.')
        frame = self._frame_reader.read_frame(payload['sourcePath'], time_ms)
        _emit_progress(0.28, 'Frame', 'Locating the selected vehicle and plate candidates.')
        detections = self._detect_targets(
            frame,
            time_ms,
            payload.get('targetVehicleKind', 'vehicle'),
            marker_rect,
        )
        target_region = self._match_anchor_target(detections, selected_target_box)
        target_box = target_region.box if target_region else selected_target_box
        _emit_progress(0.64, 'Frame', 'Running the interactive plate analysis fast path.')
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
        sample.selection = {'selected': True, 'priority': 1.0, 'reasons': ['anchor']}
        sample.diagnostics = {
            **(sample.diagnostics or {}),
            'selection': selection_diagnostics,
        }
        _emit_progress(0.9, 'Frame', 'Finalizing the frame analysis result.')
        runtime_status = self._status()
        decision = _build_decision_trace(candidates, accepted_candidate_id, selection_diagnostics, [sample])
        return {
            'detections': [detection.to_payload() for detection in detections],
            'sample': sample.to_payload(),
            'candidates': [candidate.to_payload() for candidate in candidates[:8]],
            'acceptedCandidateId': accepted_candidate_id,
            'review': build_review_state(candidates, accepted_candidate_id, selection_diagnostics),
            'provenance': build_analysis_provenance('analyze-frame', payload, runtime_status, options.to_payload()),
            'decision': decision,
            'runtime': runtime_status,
            'jobStatus': 'completed',
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
        requested_frame_count = max(1, _safe_int(payload.get('maxSamples'), 0))

        _emit_progress(0.1, 'Interval', 'Validating the anchor frame and starting interval tracking.')
        tracked_frames, track_diagnostics = self._track_target_across_interval(
            payload['sourcePath'],
            interval,
            anchor_time_ms,
            payload.get('targetVehicleKind', 'vehicle'),
            selected_target_box,
            payload.get('sampleEveryMs'),
            payload.get('maxSamples'),
            options,
            isinstance(payload.get('groundTruthFrames'), list) and len(payload.get('groundTruthFrames') or []) > 0,
        )
        requested_tracking_frame_count = max(
            requested_frame_count,
            _safe_int(track_diagnostics.get('requestedTrackingFrameCount'), len(tracked_frames)),
            1,
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
        resolved_anchor_box = _resolve_interval_anchor_box(
            tracked_frames,
            calibrated_target_boxes,
            anchor_time_ms,
            selected_target_box,
        )
        anchor_status = _anchor_status(selected_target_box, anchor_time_ms, start_ms, end_ms, resolved_anchor_box)
        anchor_ok = anchor_status == 'valid'
        tracking = _build_tracking_summary(
            track_diagnostics,
            len(tracked_frames),
            requested_tracking_frame_count,
            anchor_ok,
            anchor_status,
        )
        _emit_progress(
            0.32,
            'Interval',
            'Interval tracking finished. Preparing sample analysis.',
            trackingTier=tracking['trackingTier'],
            coverageRatio=tracking['coverageRatio'],
        )
        if not anchor_ok and len(tracked_frames) == 0:
            raise RuntimeFailure('Range analysis lost the selected target at the anchor frame. Reselect the vehicle on the intended frame and retry.')

        sample_options = options.for_interval_sample(sample_count_hint=len(tracked_frames))
        evidence_frames = _select_interval_evidence_frames(tracked_frames, options)

        samples: list[FrameSample] = []
        observations: list[PlateObservation] = []
        observation_cache: dict[int, PlateObservation | None] = {}
        sample_count = len(evidence_frames)
        for index, tracked_frame in enumerate(evidence_frames, start=1):
            raw_tracking_box = tracked_frame.box
            calibrated_target_box = calibrated_target_boxes.get(tracked_frame.time_ms)
            analysis_target_box, analysis_box_source = _resolve_analysis_target_box(
                raw_tracking_box,
                calibrated_target_box,
                selected_target_box,
                tracked_frame.time_ms,
                anchor_time_ms,
            )
            sample_progress = 0.35 if sample_count == 0 else 0.35 + (0.35 * (index - 1) / sample_count)
            _emit_progress(
                sample_progress,
                'Interval',
                f'Analyzing tracked sample {index}/{sample_count}.',
                trackingTier=tracking['trackingTier'],
                coverageRatio=tracking['coverageRatio'],
            )
            support_observations: list[PlateObservation] = []
            for support_frame in _select_temporal_support_frames(tracked_frames, tracked_frame.time_ms, sample_options):
                cached_support = observation_cache.get(support_frame.time_ms)
                if cached_support is not None:
                    support_observations.append(cached_support)
                    continue
                support_calibrated_box = calibrated_target_boxes.get(support_frame.time_ms)
                support_target_box, _ = _resolve_analysis_target_box(
                    support_frame.box,
                    support_calibrated_box,
                    selected_target_box,
                    support_frame.time_ms,
                    anchor_time_ms,
                )
                support_frame_image = self._frame_reader.read_frame(payload['sourcePath'], support_frame.time_ms)
                _, _, cached_support = self._analyze_plate_candidates(
                    support_frame_image,
                    support_frame.time_ms,
                    None,
                    support_target_box,
                    payload.get('countryHints') or [],
                    sample_options,
                    None,
                )
                observation_cache[support_frame.time_ms] = cached_support
                if cached_support is not None:
                    support_observations.append(cached_support)
            frame = self._frame_reader.read_frame(payload['sourcePath'], tracked_frame.time_ms)
            _, sample, observation = self._analyze_plate_candidates(
                frame,
                tracked_frame.time_ms,
                None,
                analysis_target_box,
                payload.get('countryHints') or [],
                sample_options,
                artifact_root / f'sample-{tracked_frame.time_ms}' if artifact_root else None,
                support_observations,
            )
            observation_cache[tracked_frame.time_ms] = observation
            if calibrated_target_box is not None:
                tracked_frame.diagnostics = {
                    **(tracked_frame.diagnostics or {}),
                    'analysisBox': analysis_target_box.to_payload(),
                    'analysisBoxSource': analysis_box_source,
                    'rawTrackingBox': raw_tracking_box.to_payload(),
                    'calibratedBox': calibrated_target_box.to_payload(),
                }
                if analysis_box_source == 'calibrated':
                    tracked_frame.box = calibrated_target_box
            sample.selection = _build_sample_selection_payload(sample, tracked_frame)
            sample.diagnostics = {
                **(sample.diagnostics or {}),
                'analysisTargetBox': analysis_target_box.to_payload(),
                'analysisBoxSource': analysis_box_source,
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
        sequence_summary = dict(fusion_diagnostics.get('sequence') or {})
        _emit_progress(0.78, 'Interval', 'Fusing candidates across interval samples.', trackingTier=tracking['trackingTier'], coverageRatio=tracking['coverageRatio'])
        candidates, accepted_candidate_id, selection_diagnostics = self._apply_reliability_selection(
            candidates,
            samples,
            payload.get('countryHints') or [],
            options,
            True,
        )
        identity_review_reasons = _tracking_identity_review_reasons(track_diagnostics)
        sequence_hard_review_reasons = _sequence_hard_review_reasons(sequence_summary, options)
        sequence_advisory_reasons = _sequence_advisory_reasons(sequence_summary, options)
        tracking_advisory_reasons = _tracking_advisory_reasons(track_diagnostics, tracking)
        selection_review_reasons = [reason for reason in selection_diagnostics.get('reasons') or [] if isinstance(reason, str)]
        hard_review_reasons = _merge_reasons(
            selection_review_reasons,
            [*identity_review_reasons, *sequence_hard_review_reasons],
        )
        if tracking['trackingTier'] == 'anchor-invalid':
            hard_review_reasons = _merge_reasons(
                hard_review_reasons,
                [str(tracking.get('degradedReason') or 'anchor validation drifted away from the selected target')],
            )
        advisory_reasons = _merge_reasons(
            sequence_advisory_reasons,
            tracking_advisory_reasons,
        )
        selection_diagnostics = {
            **selection_diagnostics,
            'acceptedCandidateId': accepted_candidate_id,
            'reviewRequired': bool(hard_review_reasons),
            'hardReviewReasons': hard_review_reasons,
            'advisoryReasons': advisory_reasons,
            'reasons': _merge_reasons(hard_review_reasons, advisory_reasons),
            'tracking': track_diagnostics,
            'sequence': sequence_summary,
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
        if tracking['trackingTier'] != 'full':
            coverage_percent = round(float(tracking['coverageRatio']) * 100)
            summary = f'{summary} Coverage {coverage_percent}% ({tracking["trackingTier"]}).'
        if sequence_summary.get('sequenceTier') and sequence_summary['sequenceTier'] != 'stable':
            summary = f'{summary} Sequence {sequence_summary["sequenceTier"]}.'

        _emit_progress(0.92, 'Interval', 'Finalizing the interval analysis result.', trackingTier=tracking['trackingTier'], coverageRatio=tracking['coverageRatio'])
        runtime_status = self._status()
        job_status = 'degraded' if tracking['trackingTier'] != 'full' else 'completed'
        analysis_tracks = self._build_track_payload(tracked_frames, track_diagnostics)
        analysis_track = analysis_tracks[0].to_payload() if analysis_tracks else None
        decision = _build_decision_trace(candidates, accepted_candidate_id, selection_diagnostics, samples, sequence_summary)
        return {
            'targetTracks': [track.to_payload() for track in analysis_tracks],
            'analysisTrack': analysis_track,
            'samples': [sample.to_payload() for sample in samples],
            'candidates': [candidate.to_payload() for candidate in candidates],
            'acceptedCandidateId': accepted_candidate_id,
            'review': build_review_state(candidates, accepted_candidate_id, selection_diagnostics),
            'sequence': sequence_summary,
            'provenance': build_analysis_provenance('analyze-interval', payload, runtime_status, options.to_payload()),
            'decision': decision,
            'summary': summary,
            'runtime': runtime_status,
            'jobStatus': job_status,
            'tracking': tracking,
            'diagnostics': {
                'analysisOptions': options.to_payload(),
                'artifactRoot': str(artifact_root) if artifact_root else None,
                'tracker': track_diagnostics,
                'trackingSummary': tracking,
                'sequence': sequence_summary,
                'fusion': fusion_diagnostics,
                'selection': selection_diagnostics,
            },
        }
