from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .value_objects import NormalizedRect


@dataclass(slots=True)
class RuntimeStatus:
    available: bool
    python_executable: str | None
    runtime_script: str | None
    version: str | None
    missing_packages: list[str]
    installed_packages: list[str]
    detail: str

    def to_payload(self) -> dict[str, Any]:
        return {
            'available': self.available,
            'pythonExecutable': self.python_executable,
            'runtimeScript': self.runtime_script,
            'version': self.version,
            'missingPackages': self.missing_packages,
            'installedPackages': self.installed_packages,
            'detail': self.detail,
        }


@dataclass(slots=True)
class QualityMetrics:
    sharpness: float
    contrast: float
    plate_area: float
    angle_score: float
    occlusion_score: float
    glare_score: float
    legibility_score: float
    overall_score: float
    legibility_level: str

    def to_payload(self) -> dict[str, Any]:
        return {
            'sharpness': self.sharpness,
            'contrast': self.contrast,
            'plateArea': self.plate_area,
            'angleScore': self.angle_score,
            'occlusionScore': self.occlusion_score,
            'glareScore': self.glare_score,
            'legibilityScore': self.legibility_score,
            'overallScore': self.overall_score,
            'legibilityLevel': self.legibility_level,
        }


@dataclass(slots=True)
class TrackedRegion:
    id: str
    time_ms: int
    box: NormalizedRect
    confidence: float
    class_name: str
    diagnostics: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'timeMs': self.time_ms,
            'box': self.box.to_payload(),
            'confidence': self.confidence,
            'className': self.class_name,
            'diagnostics': self.diagnostics,
        }


@dataclass(slots=True)
class TargetTrack:
    id: str
    class_name: str
    label: str
    confidence: float
    frames: list[TrackedRegion]
    diagnostics: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'className': self.class_name,
            'label': self.label,
            'confidence': self.confidence,
            'frames': [frame.to_payload() for frame in self.frames],
            'diagnostics': self.diagnostics,
        }


@dataclass(slots=True)
class PlateCandidate:
    id: str
    text: str
    confidence: float
    source: str
    frame_time_ms: int | None
    country_code: str | None
    box: NormalizedRect | None
    quality: QualityMetrics | None
    diagnostics: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'text': self.text,
            'confidence': self.confidence,
            'source': self.source,
            'frameTimeMs': self.frame_time_ms,
            'countryCode': self.country_code,
            'box': self.box.to_payload() if self.box else None,
            'quality': self.quality.to_payload() if self.quality else None,
            'diagnostics': self.diagnostics,
        }


@dataclass(slots=True)
class FrameSample:
    id: str
    time_ms: int
    target_box: NormalizedRect | None
    plate_box: NormalizedRect | None
    quality: QualityMetrics | None
    candidates: list[PlateCandidate]
    image_path: str | None
    diagnostics: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'timeMs': self.time_ms,
            'targetBox': self.target_box.to_payload() if self.target_box else None,
            'plateBox': self.plate_box.to_payload() if self.plate_box else None,
            'quality': self.quality.to_payload() if self.quality else None,
            'candidates': [candidate.to_payload() for candidate in self.candidates],
            'imagePath': self.image_path,
            'diagnostics': self.diagnostics,
        }
