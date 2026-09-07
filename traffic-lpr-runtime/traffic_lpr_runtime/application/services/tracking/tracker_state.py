from __future__ import annotations

from dataclasses import dataclass

from traffic_lpr_runtime.domain.value_objects import NormalizedRect


@dataclass(slots=True)
class _TrackerState:
    reference_box: NormalizedRect | None
    last_box: NormalizedRect | None
    velocity: tuple[float, float, float, float]
    last_time_ms: int
    misses: int = 0


@dataclass(slots=True)
class _TransitionDecision:
    allowed: bool
    reason: str | None
    tracking_state: str
    continuity_score: float
    continuity_credit: float
    tracker_competitive: bool
    scene_motion_active: bool
    pending_confirmation: bool


__all__ = [
    '_TrackerState',
    '_TransitionDecision',
]
