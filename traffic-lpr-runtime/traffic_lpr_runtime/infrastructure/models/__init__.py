from __future__ import annotations

from .execution_provider import OnnxExecutionProviderPolicy
from .hub import (
    DEFAULT_CROP_OCR_MODEL_NAMES,
    DEFAULT_VEHICLE_MODEL_NAME,
    ModelHub,
    ModelRegistry,
)

__all__ = [
    'DEFAULT_CROP_OCR_MODEL_NAMES',
    'DEFAULT_VEHICLE_MODEL_NAME',
    'ModelHub',
    'ModelRegistry',
    'OnnxExecutionProviderPolicy',
]
