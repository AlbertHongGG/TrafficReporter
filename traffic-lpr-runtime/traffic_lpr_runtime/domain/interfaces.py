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


class VisionChatImage(Protocol):
    frame_id: str
    label: str
    image_base64: str


class VisionLlmProvider(Protocol):
    kind: str

    def describe(self) -> dict[str, object]: ...

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        images: Any,
        timeout_s: int = 1200,
        request_metadata: dict[str, Any] | None = None,
        progress_callback: Any | None = None,
    ) -> dict[str, object]: ...

