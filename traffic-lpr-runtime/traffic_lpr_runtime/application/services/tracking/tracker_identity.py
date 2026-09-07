from __future__ import annotations

from typing import Any

from traffic_lpr_runtime.domain.models import TrackedRegion

from .tracker_state import _TransitionDecision
from .tracker_utils import _normalize_scene_motion, _scene_motion_is_active, _to_float


def _identity_transition_is_allowed(
    *,
    current_track_id: str | None,
    selected: TrackedRegion,
    selected_source: str,
    selection_score: float,
    selection_diagnostics: dict[str, Any],
    tracker_match: TrackedRegion | None,
    tracker_score: float,
    tracker_diagnostics: dict[str, Any],
    scene_motion: dict[str, float],
    pending_confirmation: bool,
    traversal_direction: str,
) -> _TransitionDecision:
    if current_track_id is None:
        return _TransitionDecision(True, None, 'confirmed', 1.0, 0.0, False, False, False)
    if selected_source == 'tracker' and selected.id == current_track_id:
        return _TransitionDecision(True, None, 'confirmed', 1.0, 0.0, False, False, False)

    motion_ok = selection_diagnostics.get('motionGatePassed') is True
    predicted_iou = _to_float(selection_diagnostics.get('predictedIou'))
    previous_iou = _to_float(selection_diagnostics.get('previousIou'))
    center_distance = _to_float(selection_diagnostics.get('centerDistance'), default=1.0)
    tracker_overlap = _to_float(tracker_diagnostics.get('predictedIou'))
    tracker_center_distance = _to_float(tracker_diagnostics.get('centerDistance'), default=1.0)
    scene_motion_active = _scene_motion_is_active(scene_motion)
    continuity_credit = min(0.12, _to_float(scene_motion.get('magnitude')) * 1.15) if scene_motion_active else 0.0
    directional_continuity_boost = 0.06 if traversal_direction == 'backward' and motion_ok else 0.0
    continuity_score = max(predicted_iou, previous_iou) + continuity_credit
    continuity_score += directional_continuity_boost
    strong_continuity = motion_ok and (
        continuity_score >= 0.28
        or center_distance <= max(0.055, 0.055 + (continuity_credit * 0.55) + (0.03 if traversal_direction == 'backward' else 0.0))
    ) and selection_score >= max(0.24, 0.28 - (continuity_credit * 0.5))

    tracker_competitive = (
        tracker_match is not None
        and tracker_diagnostics.get('motionGatePassed') is True
        and tracker_score >= (selection_score - 0.16)
    )
    tracker_bonus_only = tracker_overlap < 0.08 and _to_float(tracker_diagnostics.get('trackBonus')) >= 0.2
    detection_has_geometric_edge = (
        continuity_score >= (tracker_overlap + 0.14)
        or center_distance <= max(0.0, tracker_center_distance - 0.05)
    )
    if tracker_competitive and tracker_bonus_only and detection_has_geometric_edge:
        tracker_competitive = False
    if selected_source == 'detection-fallback':
        if tracker_competitive:
            if pending_confirmation and detection_has_geometric_edge and continuity_score >= 0.3 and selection_score >= (tracker_score + 0.03):
                return _TransitionDecision(True, None, 'uncertain', continuity_score, continuity_credit, True, scene_motion_active, True)
            return _TransitionDecision(False, 'detection-fallback-identity-break', 'rejected', continuity_score, continuity_credit, True, scene_motion_active, pending_confirmation)
        if strong_continuity:
            return _TransitionDecision(True, None, 'uncertain', continuity_score, continuity_credit, False, scene_motion_active, True)
        if traversal_direction == 'backward' and motion_ok and selection_score >= 0.16 and continuity_score >= 0.12:
            return _TransitionDecision(True, None, 'uncertain', continuity_score, continuity_credit, False, scene_motion_active, True)
        if motion_ok and scene_motion_active and selection_score >= 0.22 and continuity_score >= 0.18:
            return _TransitionDecision(True, None, 'uncertain', continuity_score, continuity_credit, False, True, True)
        return _TransitionDecision(False, 'detection-fallback-identity-break', 'rejected', continuity_score, continuity_credit, False, scene_motion_active, pending_confirmation)

    if selected.id.startswith('track-') and selected.id != current_track_id:
        if strong_continuity or (pending_confirmation and motion_ok and selection_score >= 0.3):
            return _TransitionDecision(True, None, 'confirmed', continuity_score, continuity_credit, tracker_competitive, scene_motion_active, False)
        return _TransitionDecision(False, 'track-switch-identity-break', 'rejected', continuity_score, continuity_credit, tracker_competitive, scene_motion_active, pending_confirmation)

    return _TransitionDecision(False, 'untrusted-target-transition', 'rejected', continuity_score, continuity_credit, tracker_competitive, scene_motion_active, pending_confirmation)


def _uncertain_grace_limit(
    transition: _TransitionDecision,
    selection_score: float,
    traversal_direction: str,
) -> int:
    if traversal_direction == 'backward':
        if transition.continuity_score >= 0.2 and selection_score >= 0.18:
            return 6
        return 4
    if transition.continuity_score >= 0.3 and selection_score >= 0.45:
        return 4
    return 2


def _detection_fallback_score_margin(
    *,
    tracker_motion_ok: bool,
    has_active_track: bool,
    pending_confirmation: bool,
) -> float:
    margin = 0.12 if tracker_motion_ok else 0.04
    if has_active_track:
        margin += 0.06 if tracker_motion_ok else 0.04
    if pending_confirmation and tracker_motion_ok:
        margin = max(0.1, margin - 0.02)
    return margin


def _should_soft_skip_identity_rejection(transition: _TransitionDecision, selection_score: float) -> bool:
    return (
        transition.reason == 'track-switch-identity-break'
        and transition.continuity_score < 0.12
        and selection_score < 0.32
    )


__all__ = [
    '_identity_transition_is_allowed',
    '_uncertain_grace_limit',
    '_detection_fallback_score_margin',
    '_should_soft_skip_identity_rejection',
]
