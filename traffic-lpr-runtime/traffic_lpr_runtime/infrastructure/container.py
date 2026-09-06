from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from traffic_lpr_runtime.domain.interfaces import FrameReader, PlateRecognizer, TargetDetector
from traffic_lpr_runtime.infrastructure.ai_provider_factory import build_ai_provider
from traffic_lpr_runtime.infrastructure.dependencies import DependencyRegistry
from traffic_lpr_runtime.infrastructure.frame_reader import OpenCvFrameReader
from traffic_lpr_runtime.infrastructure.image_processing import QualityScorer
from traffic_lpr_runtime.infrastructure.model_runtime import (
    FastAlprPlateRecognizer,
    ModelRegistry,
    UltralyticsTargetDetector,
)


@dataclass(frozen=True, slots=True)
class RuntimeServiceContainer:
    dependencies: DependencyRegistry
    frame_reader: FrameReader
    target_detector: TargetDetector
    primary_recognizer: PlateRecognizer
    quality_scorer: QualityScorer


def build_default_runtime_service_container(runtime_script: Path) -> RuntimeServiceContainer:
    dependencies = DependencyRegistry.load(runtime_script)
    frame_reader = OpenCvFrameReader(dependencies)
    quality_scorer = QualityScorer(dependencies)
    model_registry = ModelRegistry(dependencies)
    # Preload the baseline detector and recognizer so the first interactive frame request
    # does not pay the full cold-start cost while the UI is waiting for a result.
    model_registry.load_vehicle_model()
    model_registry.load_alpr_model()
    target_detector = UltralyticsTargetDetector(model_registry)
    primary_recognizer = FastAlprPlateRecognizer(model_registry, quality_scorer)
    return RuntimeServiceContainer(
        dependencies=dependencies,
        frame_reader=frame_reader,
        target_detector=target_detector,
        primary_recognizer=primary_recognizer,
        quality_scorer=quality_scorer,
    )
