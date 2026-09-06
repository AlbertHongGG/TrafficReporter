from __future__ import annotations

from typing import Any
from traffic_lpr_runtime.domain.analysis_options import AnalysisOptions
from traffic_lpr_runtime.domain.models import FrameSample, TrackedRegion

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


def _resolve_temporal_support_budget(
    tracked_frame_count: int,
    sample_count: int,
    options: AnalysisOptions,
) -> int:
    if sample_count <= 0 or options.temporal_neighbor_count <= 1 or options.temporal_window_ms <= 0:
        return 0

    budget = sample_count
    if tracked_frame_count >= 60:
        budget = min(budget, 4)
    elif tracked_frame_count >= 32:
        budget = min(budget, 6)

    return max(1, budget)


def _resolve_temporal_support_reason(
    sample: FrameSample,
    tracked_frame: TrackedRegion,
    options: AnalysisOptions,
) -> str | None:
    if options.temporal_neighbor_count <= 1 or options.temporal_window_ms <= 0:
        return None

    if not sample.candidates:
        return 'no-candidate'
    if sample.quality is None:
        return 'missing-quality'

    quality = sample.quality
    best_confidence = max((candidate.confidence for candidate in sample.candidates), default=0.0)
    legibility_level = quality.legibility_level.lower()
    if legibility_level in {'poor', 'very-poor', 'unreadable'}:
        return 'poor-legibility'
    if quality.overall_score < 0.76 or quality.legibility_score < 0.79:
        return 'low-quality'
    if best_confidence < max(0.84, options.min_accepted_confidence + 0.18):
        return 'low-confidence'

    diagnostics = tracked_frame.diagnostics or {}
    if (
        diagnostics.get('isAnchorFrame') is True or diagnostics.get('isMotionHotspot') is True
    ) and best_confidence < max(0.9, options.min_accepted_confidence + 0.24):
        return 'priority-frame'
    return None


