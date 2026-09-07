from __future__ import annotations

from typing import Any

from traffic_lpr_runtime.domain.value_objects import NormalizedRect, clamp


def _motion_gate(candidate_box: NormalizedRect, reference_box: NormalizedRect, scene_motion: dict[str, float] | None = None) -> dict[str, float | bool]:
    candidate_center_x = candidate_box.x + (candidate_box.width / 2.0)
    candidate_center_y = candidate_box.y + (candidate_box.height / 2.0)
    reference_center_x = reference_box.x + (reference_box.width / 2.0)
    reference_center_y = reference_box.y + (reference_box.height / 2.0)
    delta_x = abs(candidate_center_x - reference_center_x)
    delta_y = abs(candidate_center_y - reference_center_y)
    base_width = max(candidate_box.width, reference_box.width)
    base_height = max(candidate_box.height, reference_box.height)
    normalized_motion = _normalize_scene_motion(scene_motion or {})
    motion_credit_x = min(0.08, (_to_float(normalized_motion.get('magnitude')) * 0.75) + (abs(_to_float(normalized_motion.get('dx'))) * 0.45))
    motion_credit_y = min(0.12, (_to_float(normalized_motion.get('magnitude')) * 0.55) + (abs(_to_float(normalized_motion.get('dy'))) * 0.75))
    max_horizontal_shift = clamp((base_width * 0.45) + 0.035 + motion_credit_x, 0.08, 0.2)
    max_vertical_shift = clamp((base_height * 1.1) + 0.05 + motion_credit_y, 0.12, 0.38)
    passed = delta_x <= max_horizontal_shift and delta_y <= max_vertical_shift
    return {
        'passed': passed,
        'deltaX': delta_x,
        'deltaY': delta_y,
        'maxHorizontalShift': max_horizontal_shift,
        'maxVerticalShift': max_vertical_shift,
        'sceneMotionMagnitude': _to_float(normalized_motion.get('magnitude')),
        'sceneMotionScore': _to_float(normalized_motion.get('score')),
    }


def _update_velocity(
    previous_box: NormalizedRect | None,
    current_box: NormalizedRect,
    previous_time_ms: int,
    current_time_ms: int,
    prior_velocity: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    if previous_box is None:
        return prior_velocity
    delta_time = max(abs(current_time_ms - previous_time_ms), 1)
    measured_velocity = (
        (current_box.x - previous_box.x) / delta_time,
        (current_box.y - previous_box.y) / delta_time,
        (current_box.width - previous_box.width) / delta_time,
        (current_box.height - previous_box.height) / delta_time,
    )
    return tuple((prior * 0.6) + (observed * 0.4) for prior, observed in zip(prior_velocity, measured_velocity, strict=True))


def _shift_rect(
    rect: NormalizedRect | None,
    delta_x: float,
    delta_y: float,
    delta_width: float,
    delta_height: float,
) -> NormalizedRect:
    if rect is None:
        return NormalizedRect(0.0, 0.0, 0.0, 0.0)
    x = clamp(rect.x + delta_x, 0.0, 1.0)
    y = clamp(rect.y + delta_y, 0.0, 1.0)
    width = clamp(rect.width + delta_width, 0.01, 1.0 - x)
    height = clamp(rect.height + delta_height, 0.01, 1.0 - y)
    return NormalizedRect(x=x, y=y, width=width, height=height)


def _normalize_scene_motion(scene_motion: dict[str, Any]) -> dict[str, float]:
    dx = _to_float(scene_motion.get('dx'))
    dy = _to_float(scene_motion.get('dy'))
    magnitude = _to_float(scene_motion.get('magnitude'))
    if magnitude <= 0.0:
        magnitude = (dx ** 2 + dy ** 2) ** 0.5
    return {
        'dx': dx,
        'dy': dy,
        'magnitude': magnitude,
        'score': max(0.0, _to_float(scene_motion.get('score'))),
    }


def _scene_motion_is_active(scene_motion: dict[str, Any]) -> bool:
    normalized = _normalize_scene_motion(scene_motion)
    return normalized['magnitude'] >= 0.025 and normalized['score'] >= 0.08


def _compensate_reference_box(reference_box: NormalizedRect, scene_motion: dict[str, Any]) -> NormalizedRect:
    normalized = _normalize_scene_motion(scene_motion)
    if not _scene_motion_is_active(normalized):
        return reference_box
    motion_weight = clamp(0.35 + min(normalized['score'], 1.0) * 0.45, 0.35, 0.8)
    return _shift_rect(reference_box, normalized['dx'] * motion_weight, normalized['dy'] * motion_weight, 0.0, 0.0)


def _resolve_directional_scene_motion(
    scene_motion_by_time: dict[int, dict[str, float]],
    time_ms: int,
    reference_time_ms: int,
    traversal_direction: str,
) -> dict[str, float]:
    if traversal_direction == 'backward':
        return _invert_scene_motion(scene_motion_by_time.get(reference_time_ms) or {})
    return _normalize_scene_motion(scene_motion_by_time.get(time_ms) or {})


def _invert_scene_motion(scene_motion: dict[str, Any]) -> dict[str, float]:
    normalized = _normalize_scene_motion(scene_motion)
    return {
        'dx': -normalized['dx'],
        'dy': -normalized['dy'],
        'magnitude': normalized['magnitude'],
        'score': normalized['score'],
    }


def _tracker_class_id(class_name: str) -> int:
    return {
        'car': 2,
        'motorcycle': 3,
        'bus': 5,
        'truck': 7,
    }.get(str(class_name), 0)


def _tracker_class_name(class_id: int) -> str:
    return {
        2: 'car',
        3: 'motorcycle',
        5: 'bus',
        7: 'truck',
    }.get(int(class_id), 'vehicle')


def _to_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    '_motion_gate',
    '_update_velocity',
    '_shift_rect',
    '_normalize_scene_motion',
    '_scene_motion_is_active',
    '_compensate_reference_box',
    '_resolve_directional_scene_motion',
    '_invert_scene_motion',
    '_tracker_class_id',
    '_tracker_class_name',
    '_to_optional_str',
    '_to_float',
]
