from __future__ import annotations

from traffic_lpr_runtime.domain.models import TrackedRegion
from traffic_lpr_runtime.domain.value_objects import NormalizedRect, clamp


class IntervalAnchorMixin:
    def match_anchor_target(
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

    def calibrate_interval_target_boxes(
        self,
        tracked_frames: list[TrackedRegion],
        anchor_time_ms: int,
        selected_target_box: NormalizedRect | None,
    ) -> dict[int, NormalizedRect]:
        if selected_target_box is None or not tracked_frames:
            return {}

        anchor_frame = next((frame for frame in tracked_frames if frame.time_ms == anchor_time_ms), None)
        if anchor_frame is None:
            anchor_frame = min(tracked_frames, key=lambda frame: abs(frame.time_ms - anchor_time_ms))

        anchor_box = anchor_frame.box if anchor_frame is not None else None
        if anchor_box is None or anchor_box.width <= 0.0 or anchor_box.height <= 0.0:
            return {}
        if anchor_box.intersection_over_union(selected_target_box) < 0.1 and anchor_box.center_distance(selected_target_box) > 0.12:
            return {}

        anchor_width = max(anchor_box.width, 1e-6)
        anchor_height = max(anchor_box.height, 1e-6)
        left_ratio = (anchor_box.x - selected_target_box.x) / anchor_width
        top_ratio = (anchor_box.y - selected_target_box.y) / anchor_height
        right_ratio = ((selected_target_box.x + selected_target_box.width) - (anchor_box.x + anchor_box.width)) / anchor_width
        bottom_ratio = ((selected_target_box.y + selected_target_box.height) - (anchor_box.y + anchor_box.height)) / anchor_height

        calibrated: dict[int, NormalizedRect] = {}
        for tracked_frame in tracked_frames:
            raw_box = tracked_frame.box
            x1 = clamp(raw_box.x - (left_ratio * raw_box.width), 0.0, 1.0)
            y1 = clamp(raw_box.y - (top_ratio * raw_box.height), 0.0, 1.0)
            x2 = clamp(raw_box.x + raw_box.width + (right_ratio * raw_box.width), min(1.0, x1 + 0.01), 1.0)
            y2 = clamp(raw_box.y + raw_box.height + (bottom_ratio * raw_box.height), min(1.0, y1 + 0.01), 1.0)
            calibrated[tracked_frame.time_ms] = NormalizedRect(
                x=x1,
                y=y1,
                width=x2 - x1,
                height=y2 - y1,
            )

        return calibrated

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
