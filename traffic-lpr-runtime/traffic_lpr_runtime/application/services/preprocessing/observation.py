from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from traffic_lpr_runtime.domain.models import PlateCandidate, QualityMetrics
from traffic_lpr_runtime.domain.value_objects import NormalizedRect


@dataclass(slots=True)
class PlateObservation:
    time_ms: int
    target_box: NormalizedRect | None
    plate_box: NormalizedRect | None
    quality: QualityMetrics | None
    original_image: Any
    rectified_image: Any
    enhanced_image: Any
    restored_image: Any | None
    working_image: Any
    working_stage: str
    artifact_paths: dict[str, str]
    diagnostics: dict[str, Any]
    temporal_support: dict[str, Any] | None = None
    ocr_candidates: list[PlateCandidate] = field(default_factory=list)


def _observation_quality_score(observation: PlateObservation) -> float:
    return observation.quality.overall_score if observation.quality is not None else 0.0
