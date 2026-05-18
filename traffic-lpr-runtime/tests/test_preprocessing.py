from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.application.pipeline_support import AnalysisOptions
from traffic_lpr_runtime.application.preprocessing import PlatePreprocessor
from traffic_lpr_runtime.infrastructure.image_processing import QualityScorer

try:
    import cv2
    import numpy as np
except Exception:  # pragma: no cover - dependency-gated test environment
    cv2 = None
    np = None


@unittest.skipIf(cv2 is None or np is None, 'OpenCV and NumPy are required for preprocessing tests.')
class PreprocessingTests(unittest.TestCase):
    def test_interval_sample_keeps_restoration_in_classical_mode(self) -> None:
        options = AnalysisOptions(restoration_mode='mambairv2', enable_recognizer_comparison=True)

        sample_options = options.for_interval_sample(sample_count_hint=12)

        self.assertFalse(sample_options.enable_recognizer_comparison)
        self.assertEqual(sample_options.restoration_mode, 'classical')

    def test_rectification_falls_back_to_deskew_when_no_plate_quad_is_found(self) -> None:
        dependencies = types.SimpleNamespace(
            cv2=cv2,
            numpy=np,
            einops=None,
            timm=None,
            torch=None,
        )
        preprocessor = PlatePreprocessor(dependencies=dependencies, quality_scorer=QualityScorer(dependencies))
        plate_image = np.full((72, 180, 3), 220, dtype=np.uint8)
        cv2.line(plate_image, (18, 40), (164, 18), (18, 18, 18), 3)
        cv2.line(plate_image, (24, 54), (170, 32), (28, 28, 28), 3)
        cv2.line(plate_image, (30, 62), (176, 40), (40, 40, 40), 2)

        rectified, diagnostics = preprocessor._rectify_plate(plate_image)

        self.assertTrue(diagnostics['applied'])
        self.assertEqual(diagnostics['method'], 'hough-deskew')
        self.assertGreater(abs(float(diagnostics['angle'])), 2.0)
        self.assertNotEqual(rectified.shape[:2], plate_image.shape[:2])


if __name__ == '__main__':
    unittest.main()