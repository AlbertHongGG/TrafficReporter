from __future__ import annotations

from typing import Any


def _order_quad_points(points: Any) -> Any:
    numpy = __import__('numpy')
    ordered = numpy.zeros((4, 2), dtype='float32')
    sums = points.sum(axis=1)
    diffs = points[:, 0] - points[:, 1]
    ordered[0] = points[sums.argmin()]
    ordered[2] = points[sums.argmax()]
    ordered[1] = points[diffs.argmin()]
    ordered[3] = points[diffs.argmax()]
    return ordered


def _distance(left: Any, right: Any) -> float:
    return float((((left[0] - right[0]) ** 2) + ((left[1] - right[1]) ** 2)) ** 0.5)
