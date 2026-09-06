from __future__ import annotations

from typing import Any
from traffic_lpr_runtime.application.services.fusion.review_decision import _merge_reasons, _safe_int
from traffic_lpr_runtime.domain.models import TrackedRegion
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

