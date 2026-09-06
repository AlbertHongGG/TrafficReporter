from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable
from typing import Any

from traffic_lpr_runtime.domain.value_objects import NormalizedRect, clamp


class AlprPredictionMapper:
    """Handles serialization, coordinates projection, and data sanitization for ALPR outputs."""

    @staticmethod
    def write_temp_image(cv2_module: Any, image: Any) -> str:
        handle = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        handle.close()
        cv2_module.imwrite(handle.name, image)
        return handle.name

    @staticmethod
    def cleanup_temp_image(path: str) -> None:
        try:
            os.unlink(path)
        except FileNotFoundError:
            return

    @classmethod
    def serialize_prediction(cls, prediction: Any) -> dict[str, Any]:
        serialized = cls._serialize_value(prediction)
        return serialized if isinstance(serialized, dict) else {'raw': serialized}

    @classmethod
    def _serialize_value(cls, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {key: cls._serialize_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._serialize_value(item) for item in value]
        if hasattr(value, '_asdict'):
            return {key: cls._serialize_value(item) for key, item in value._asdict().items()}
        if hasattr(value, '__dict__'):
            return {key: cls._serialize_value(item) for key, item in vars(value).items()}
        return str(value)

    @staticmethod
    def is_prediction_iterable(raw_predictions: Any) -> bool:
        return isinstance(raw_predictions, Iterable) and not isinstance(raw_predictions, (dict, str, bytes))

    @staticmethod
    def to_float(value: Any) -> float:
        if isinstance(value, (list, tuple)):
            values = [AlprPredictionMapper.to_float(item) for item in value if item is not None]
            return sum(values) / len(values) if values else 0.0
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def to_float_list(value: Any) -> list[float] | None:
        if value is None:
            return None
        if hasattr(value, 'tolist'):
            value = value.tolist()
        if isinstance(value, Iterable) and not isinstance(value, (str, bytes, dict)):
            converted = [AlprPredictionMapper.to_float(item) for item in value if item is not None]
            return converted or None
        return None

    @staticmethod
    def first_present(*values: Any) -> Any:
        for value in values:
            if value is None:
                continue
            if isinstance(value, str) and not value:
                continue
            return value
        return None

    @staticmethod
    def nested_get(value: Any, *keys: str) -> Any:
        current = value
        for key in keys:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    @staticmethod
    def to_optional_str(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def translate_rect_from_crop(
        rect: NormalizedRect | None,
        crop_rect: NormalizedRect | None,
    ) -> NormalizedRect | None:
        if rect is None:
            return None
        if crop_rect is None:
            return rect
        x = clamp(crop_rect.x + (rect.x * crop_rect.width), 0.0, 1.0)
        y = clamp(crop_rect.y + (rect.y * crop_rect.height), 0.0, 1.0)
        width = clamp(rect.width * crop_rect.width, 0.0, 1.0 - x)
        height = clamp(rect.height * crop_rect.height, 0.0, 1.0 - y)
        return NormalizedRect(x=x, y=y, width=width, height=height)

    @staticmethod
    def normalize_candidate_box(
        raw_box: Any,
        frame_width: int,
        frame_height: int,
    ) -> NormalizedRect | None:
        if raw_box is None:
            return None

        if isinstance(raw_box, dict):
            values = raw_box
            if {'xmin', 'ymin', 'xmax', 'ymax'} <= set(values):
                x1, y1, x2, y2 = values['xmin'], values['ymin'], values['xmax'], values['ymax']
            elif {'x1', 'y1', 'x2', 'y2'} <= set(values):
                x1, y1, x2, y2 = values['x1'], values['y1'], values['x2'], values['y2']
            elif {'x', 'y', 'width', 'height'} <= set(values):
                x1 = values['x']
                y1 = values['y']
                x2 = values['x'] + values['width']
                y2 = values['y'] + values['height']
            else:
                return None
        elif isinstance(raw_box, (list, tuple)) and len(raw_box) >= 4:
            x1, y1, x2, y2 = raw_box[:4]
        else:
            return None

        try:
            x1 = float(x1)
            y1 = float(y1)
            x2 = float(x2)
            y2 = float(y2)
        except (TypeError, ValueError):
            return None

        return NormalizedRect.from_xyxy(x1, y1, x2, y2, frame_width, frame_height)
