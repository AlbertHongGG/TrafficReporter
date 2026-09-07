from __future__ import annotations

import math
from typing import Any

from traffic_lpr_runtime.domain.models import TrackedRegion


def _build_temporal_range_diagnostics(
    tracked_frames: list[TrackedRegion],
    tracking_times: list[int],
    trajectory_step_ms: int,
    anchor_time_ms: int,
) -> dict[str, Any]:
    if not tracking_times:
        return {
            'requestedStartMs': anchor_time_ms,
            'requestedEndMs': anchor_time_ms,
            'trackedStartMs': None,
            'trackedEndMs': None,
            'trackedSpanMs': 0,
            'coverageRatio': 0.0,
            'reachedRequestedStart': False,
            'reachedRequestedEnd': False,
            'gapCount': 0,
            'maxGapMs': 0,
            'averageGapMs': 0.0,
            'averageMotion': 0.0,
            'motionVariance': 0.0,
            'motionStdDev': 0.0,
            'maxMotion': 0.0,
            'motionHotspotThreshold': 0.0,
        }

    requested_start_ms = tracking_times[0]
    requested_end_ms = tracking_times[-1]
    tracked_start_ms = tracked_frames[0].time_ms if tracked_frames else None
    tracked_end_ms = tracked_frames[-1].time_ms if tracked_frames else None
    tracked_span_ms = max(0, (tracked_end_ms or requested_start_ms) - (tracked_start_ms or requested_start_ms))
    coverage_ratio = 0.0 if not tracking_times else max(0.0, min(1.0, len(tracked_frames) / max(len(tracking_times), 1)))

    gaps_ms: list[int] = []
    motion_samples: list[float] = []
    for previous, current in zip(tracked_frames, tracked_frames[1:]):
        gaps_ms.append(max(0, current.time_ms - previous.time_ms))
        motion_samples.append(current.box.center_distance(previous.box))

    average_gap_ms = sum(gaps_ms) / len(gaps_ms) if gaps_ms else 0.0
    gap_threshold_ms = max(int(round(trajectory_step_ms * 1.5)), trajectory_step_ms + 1)
    gap_count = sum(1 for gap_ms in gaps_ms if gap_ms > gap_threshold_ms)
    max_gap_ms = max(gaps_ms, default=0)

    average_motion = sum(motion_samples) / len(motion_samples) if motion_samples else 0.0
    motion_variance = (
        sum((motion - average_motion) ** 2 for motion in motion_samples) / len(motion_samples)
        if motion_samples
        else 0.0
    )
    motion_std_dev = math.sqrt(motion_variance)
    max_motion = max(motion_samples, default=0.0)
    motion_hotspot_threshold = max(average_motion + motion_std_dev, max_motion * 0.85)
    if motion_hotspot_threshold <= 0.0:
        motion_hotspot_threshold = 0.0

    return {
        'requestedStartMs': requested_start_ms,
        'requestedEndMs': requested_end_ms,
        'trackedStartMs': tracked_start_ms,
        'trackedEndMs': tracked_end_ms,
        'trackedSpanMs': tracked_span_ms,
        'coverageRatio': coverage_ratio,
        'reachedRequestedStart': tracked_start_ms == requested_start_ms,
        'reachedRequestedEnd': tracked_end_ms == requested_end_ms,
        'gapCount': gap_count,
        'maxGapMs': max_gap_ms,
        'averageGapMs': average_gap_ms,
        'averageMotion': average_motion,
        'motionVariance': motion_variance,
        'motionStdDev': motion_std_dev,
        'maxMotion': max_motion,
        'motionHotspotThreshold': motion_hotspot_threshold,
    }
