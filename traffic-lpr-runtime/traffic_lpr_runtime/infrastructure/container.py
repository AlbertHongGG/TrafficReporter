from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from traffic_lpr_runtime.domain.interfaces import (
    FrameReader,
    PlateRecognizer,
    PlateRestorer,
    QualityScorer,
    TargetDetector,
)
from traffic_lpr_runtime.infrastructure.dependencies import DependencyRegistry
from traffic_lpr_runtime.infrastructure.detection import Yolo26TargetDetector
from traffic_lpr_runtime.infrastructure.models import ModelHub
from traffic_lpr_runtime.infrastructure.recognition import FastAlprPlateRecognizer
from traffic_lpr_runtime.infrastructure.restoration import MambaIrV2PlateRestorer
from traffic_lpr_runtime.infrastructure.vision import OpenCvFrameReader
from traffic_lpr_runtime.infrastructure.vision import QualityScorer as VisionQualityScorer


@dataclass(frozen=True, slots=True)
class RuntimeServiceContainer:
    dependencies: DependencyRegistry
    frame_reader: FrameReader
    target_detector: TargetDetector
    primary_recognizer: PlateRecognizer
    quality_scorer: QualityScorer
    restorer: PlateRestorer


def build_default_runtime_service_container(runtime_script: Path) -> RuntimeServiceContainer:
    dependencies = DependencyRegistry.load(runtime_script)
    frame_reader = OpenCvFrameReader(dependencies)
    quality_scorer = VisionQualityScorer(dependencies)
    models = ModelHub(dependencies)
    target_detector = Yolo26TargetDetector(models)
    # Preload the baseline detector and recognizer so the first interactive frame request
    # does not pay the full cold-start cost while the UI is waiting for a result.
    target_detector.load_model()
    models.load_alpr_model()
    primary_recognizer = FastAlprPlateRecognizer(models, quality_scorer)
    restorer = MambaIrV2PlateRestorer(dependencies)
    return RuntimeServiceContainer(
        dependencies=dependencies,
        frame_reader=frame_reader,
        target_detector=target_detector,
        primary_recognizer=primary_recognizer,
        quality_scorer=quality_scorer,
        restorer=restorer,
    )
