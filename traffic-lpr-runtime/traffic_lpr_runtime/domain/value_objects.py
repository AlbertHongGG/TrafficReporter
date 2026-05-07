from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


RectPayload = dict[str, float]


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


@dataclass(frozen=True, slots=True)
class NormalizedRect:
    x: float
    y: float
    width: float
    height: float

    def to_payload(self) -> RectPayload:
        return {
            'x': self.x,
            'y': self.y,
            'width': self.width,
            'height': self.height,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, float] | None) -> 'NormalizedRect | None':
        if payload is None:
            return None
        x = clamp(float(payload.get('x', 0.0)), 0.0, 1.0)
        y = clamp(float(payload.get('y', 0.0)), 0.0, 1.0)
        return cls(
            x=x,
            y=y,
            width=clamp(float(payload.get('width', 0.0)), 0.0, 1.0 - x),
            height=clamp(float(payload.get('height', 0.0)), 0.0, 1.0 - y),
        )

    @classmethod
    def from_xyxy(
        cls,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        frame_width: int,
        frame_height: int,
    ) -> 'NormalizedRect':
        if frame_width <= 0 or frame_height <= 0:
            return cls(0.0, 0.0, 0.0, 0.0)

        x = clamp(x1 / frame_width, 0.0, 1.0)
        y = clamp(y1 / frame_height, 0.0, 1.0)
        width = clamp((x2 - x1) / frame_width, 0.0, 1.0 - x)
        height = clamp((y2 - y1) / frame_height, 0.0, 1.0 - y)
        return cls(x=x, y=y, width=width, height=height)

    def to_pixels(self, frame_width: int, frame_height: int) -> tuple[int, int, int, int]:
        x = int(round(clamp(self.x, 0.0, 1.0) * frame_width))
        y = int(round(clamp(self.y, 0.0, 1.0) * frame_height))
        rect_width = int(round(clamp(self.width, 0.0, 1.0) * frame_width))
        rect_height = int(round(clamp(self.height, 0.0, 1.0) * frame_height))
        x2 = int(clamp(x + rect_width, x + 1, frame_width))
        y2 = int(clamp(y + rect_height, y + 1, frame_height))
        return x, y, x2, y2

    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    def center_distance(self, other: 'NormalizedRect') -> float:
        return math.hypot(
            (self.x + (self.width / 2.0)) - (other.x + (other.width / 2.0)),
            (self.y + (self.height / 2.0)) - (other.y + (other.height / 2.0)),
        )

    def intersection_over_union(self, other: 'NormalizedRect | None') -> float:
        if other is None:
            return 0.0

        ax2 = self.x + self.width
        ay2 = self.y + self.height
        bx2 = other.x + other.width
        by2 = other.y + other.height

        inter_x1 = max(self.x, other.x)
        inter_y1 = max(self.y, other.y)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)

        inter_w = max(0.0, inter_x2 - inter_x1)
        inter_h = max(0.0, inter_y2 - inter_y1)
        inter_area = inter_w * inter_h
        union = self.area() + other.area() - inter_area
        if union <= 0.0:
            return 0.0
        return inter_area / union


def crop_image(image: Any, rect: NormalizedRect | None) -> Any:
    if image is None or rect is None:
        return image

    frame_height, frame_width = image.shape[:2]
    x1, y1, x2, y2 = rect.to_pixels(frame_width, frame_height)
    return image[y1:y2, x1:x2].copy()
