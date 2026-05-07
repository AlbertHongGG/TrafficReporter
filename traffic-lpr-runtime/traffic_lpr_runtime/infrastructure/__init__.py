from .dependencies import DependencyRegistry
from .frame_reader import OpenCvFrameReader
from .image_processing import QualityScorer
from .model_runtime import (
    FastAlprPlateRecognizer,
    ModelRegistry,
    UltralyticsTargetDetector,
)

__all__ = [
    'DependencyRegistry',
    'FastAlprPlateRecognizer',
    'ModelRegistry',
    'OpenCvFrameReader',
    'QualityScorer',
    'UltralyticsTargetDetector',
]
