from __future__ import annotations

from typing import Any, Protocol

from .analysis_options import AnalysisOptions
from .models import PlateCandidate, QualityMetrics, TrackedRegion
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


class PlateRestorer(Protocol):
    def restore(self, image: Any, scale: int = 2) -> Any: ...

    def restore_plate(
        self,
        image: Any,
        options: AnalysisOptions,
    ) -> tuple[Any | None, dict[str, Any]]: ...


class QualityScorer(Protocol):
    def score(
        self,
        image: Any,
        box: NormalizedRect | None,
    ) -> QualityMetrics: ...


class ProgressSink(Protocol):
    def emit(
        self,
        progress: float,
        stage: str,
        detail: str,
        *,
        done: bool = False,
        failed: bool = False,
        **kwargs: Any,
    ) -> None: ...

