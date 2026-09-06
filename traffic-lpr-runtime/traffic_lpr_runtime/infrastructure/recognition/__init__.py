from __future__ import annotations

from .fast_alpr_recognizer import FastAlprPlateRecognizer
from .plate_priors import TaiwanPlatePrior
from .prediction_mapper import AlprPredictionMapper

__all__ = [
    'AlprPredictionMapper',
    'FastAlprPlateRecognizer',
    'TaiwanPlatePrior',
]
