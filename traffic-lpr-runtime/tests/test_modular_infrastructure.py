from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from traffic_lpr_runtime.domain.analysis_options import AnalysisOptions
from traffic_lpr_runtime.domain.value_objects import NormalizedRect
from traffic_lpr_runtime.infrastructure.detection import Yolo26TargetDetector
from traffic_lpr_runtime.infrastructure.models import (
    ModelHub,
    OnnxExecutionProviderPolicy,
)
from traffic_lpr_runtime.infrastructure.recognition import (
    AlprPredictionMapper,
    FastAlprPlateRecognizer,
    TaiwanPlatePrior,
)
from traffic_lpr_runtime.infrastructure.restoration import MambaIrV2PlateRestorer
from traffic_lpr_runtime.infrastructure.vision import OpenCvFrameReader, QualityScorer


class TestModularInfrastructure(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_deps = MagicMock()
        self.mock_deps.torch_cuda_available.return_value = False
        self.mock_deps.preferred_torch_device.return_value = 'cpu'
        self.mock_deps.models_root.return_value = Path('/tmp/models')
        self.mock_deps.cv2 = MagicMock()
        self.mock_deps.numpy = np

    def test_onnx_execution_provider_policy_cpu_and_cuda(self) -> None:
        policy = OnnxExecutionProviderPolicy(self.mock_deps)
        self.assertEqual(policy.device(), 'cpu')
        self.assertEqual(policy.providers(), ['CPUExecutionProvider'])

        self.mock_deps.torch_cuda_available.return_value = True
        self.assertEqual(policy.device(), 'cuda')
        self.assertIn('CUDAExecutionProvider', policy.providers())

    def test_taiwan_plate_prior_rules(self) -> None:
        self.assertTrue(TaiwanPlatePrior.is_applicable(['TW'], None))
        self.assertTrue(TaiwanPlatePrior.is_applicable(None, 'TWN'))
        self.assertTrue(TaiwanPlatePrior.is_applicable(None, 'TAIWAN'))
        self.assertFalse(TaiwanPlatePrior.is_applicable(['US'], 'USA'))

        # Standard formats
        self.assertGreater(TaiwanPlatePrior.calculate_prior('ABC1234'), 1.10)
        self.assertGreater(TaiwanPlatePrior.calculate_prior('1234AB'), 1.05)
        self.assertGreater(TaiwanPlatePrior.calculate_prior('AB123C'), 1.0)
        self.assertLess(TaiwanPlatePrior.calculate_prior(''), 0.7)

    def test_alpr_prediction_mapper_serialization_and_boxes(self) -> None:
        raw_box = {'xmin': 10, 'ymin': 20, 'xmax': 60, 'ymax': 70}
        norm_box = AlprPredictionMapper.normalize_candidate_box(raw_box, 100, 100)
        self.assertIsNotNone(norm_box)
        self.assertAlmostEqual(norm_box.x, 0.1)
        self.assertAlmostEqual(norm_box.y, 0.2)
        self.assertAlmostEqual(norm_box.width, 0.5)
        self.assertAlmostEqual(norm_box.height, 0.5)

        crop_rect = NormalizedRect(x=0.2, y=0.2, width=0.5, height=0.5)
        translated = AlprPredictionMapper.translate_rect_from_crop(norm_box, crop_rect)
        self.assertIsNotNone(translated)
        self.assertAlmostEqual(translated.x, 0.2 + (0.1 * 0.5))
        self.assertAlmostEqual(translated.y, 0.2 + (0.2 * 0.5))

    def test_mambair_plate_restorer_handles_empty_image(self) -> None:
        restorer = MambaIrV2PlateRestorer(self.mock_deps)
        self.mock_deps.cv2 = None
        self.assertFalse(restorer.available())

        restored, diags = restorer.restore_plate(None, AnalysisOptions())
        self.assertIsNone(restored)
        self.assertFalse(diags['applied'])
        self.assertEqual(diags['reason'], 'empty_image')

    def test_vision_quality_scorer_returns_valid_metrics(self) -> None:
        import cv2
        deps = MagicMock()
        deps.cv2 = cv2
        deps.numpy = np
        scorer = QualityScorer(deps)

        sample_img = np.full((50, 150, 3), 128, dtype=np.uint8)
        metrics = scorer.score(sample_img, NormalizedRect(x=0.0, y=0.0, width=1.0, height=1.0))
        self.assertIsNotNone(metrics)
        self.assertIn(metrics.legibility_level, {'perfect', 'good', 'poor', 'illegible'})


if __name__ == '__main__':
    unittest.main()
