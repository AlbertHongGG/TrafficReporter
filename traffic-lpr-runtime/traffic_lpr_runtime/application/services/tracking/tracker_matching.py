from __future__ import annotations

from traffic_lpr_runtime.domain.models import TrackedRegion
from traffic_lpr_runtime.domain.value_objects import NormalizedRect


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


def _anchor_matches_reference(
    candidate: TrackedRegion | None,
    reference_box: NormalizedRect | None,
) -> bool:
    if candidate is None or reference_box is None:
        return False

    overlap = candidate.box.intersection_over_union(reference_box)
    center_distance = candidate.box.center_distance(reference_box)
    return overlap >= 0.18 or center_distance <= 0.08


__all__ = [
    '_select_best_anchor',
    '_anchor_matches_reference',
]
