from __future__ import annotations

from typing import Any, Protocol

from .models import PlateCandidate, TrackedRegion
from .value_objects import NormalizedRect


class FrameReader(Protocol):
    def read_frame(self, source_path: str, time_ms: int) -> Any: ...


class TargetDetector(Protocol):
    def detect_targets(
        self,
        frame: Any,
        time_ms: int,
        vehicle_kind: str,
        marker_rect: NormalizedRect | None,
    ) -> list[TrackedRegion]: ...


class PlateRecognizer(Protocol):
    def recognize(
        self,
        image: Any,
        time_ms: int,
        crop_box: NormalizedRect | None,
    ) -> list[PlateCandidate]: ...

    def recognize_plate_crop(
        self,
        image: Any,
        time_ms: int,
        plate_box: NormalizedRect | None,
        country_hints: list[str] | None = None,
        model_names: list[str] | None = None,
    ) -> list[PlateCandidate]: ...
