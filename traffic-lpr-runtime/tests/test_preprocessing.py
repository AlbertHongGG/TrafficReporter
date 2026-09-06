from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.application.contracts.options_factory import build_analysis_options_from_payload
from traffic_lpr_runtime.application.services.preprocessing import PlatePreprocessor
from traffic_lpr_runtime.domain.analysis_options import AnalysisOptions
from traffic_lpr_runtime.domain.models import QualityMetrics
from traffic_lpr_runtime.domain.value_objects import NormalizedRect
from traffic_lpr_runtime.infrastructure.image_processing import QualityScorer

try:
    import cv2
    import numpy as np
except Exception:  # pragma: no cover - dependency-gated test environment
    cv2 = None
    np = None


@unittest.skipIf(cv2 is None or np is None, 'OpenCV and NumPy are required for preprocessing tests.')
class PreprocessingTests(unittest.TestCase):
    def test_prepare_prefers_best_stage_over_restored_output(self) -> None:
        def quality(overall: float, *, angle_score: float = 0.8) -> QualityMetrics:
            return QualityMetrics(
                sharpness=overall,
                contrast=overall,
                plate_area=0.08,
                angle_score=angle_score,
                occlusion_score=0.9,
                glare_score=0.9,
                legibility_score=overall,
                overall_score=overall,
                legibility_level='good' if overall >= 0.62 else 'poor',
            )

        source_frame = np.full((90, 220, 3), 200, dtype=np.uint8)
        original_image = np.full((40, 120, 3), 180, dtype=np.uint8)
        rectified_image = np.full((40, 120, 3), 181, dtype=np.uint8)
        enhanced_image = np.full((40, 120, 3), 182, dtype=np.uint8)
        restored_image = np.full((40, 120, 3), 183, dtype=np.uint8)

        quality_by_signature = {
            (90, 220, 200): quality(0.58),
            (14, 66, 200): quality(0.61),
            (40, 120, 181): quality(0.63, angle_score=0.82),
            (40, 120, 182): quality(0.86),
            (40, 120, 183): quality(0.71),
        }

        class StubQualityScorer:
            def score(self, image, plate_box):
                signature = (int(image.shape[0]), int(image.shape[1]), int(image.mean()))
                return quality_by_signature[signature]

        dependencies = types.SimpleNamespace(
            cv2=cv2,
            numpy=np,
            einops=None,
            timm=None,
            torch=None,
        )
        preprocessor = PlatePreprocessor(dependencies=dependencies, quality_scorer=StubQualityScorer())
        preprocessor._expand_plate_crop_box = lambda frame, plate_box: plate_box
        preprocessor._rectify_plate = lambda plate_image: (rectified_image, {'applied': True, 'method': 'stub'})
        preprocessor._enhance_plate = lambda plate_image: enhanced_image
        preprocessor._should_restore = lambda plate_image, quality_metrics, options, quality_route: True
        preprocessor._restore_plate = lambda plate_image, options: (
            restored_image,
            {'applied': True, 'backend': 'stub', 'mode': options.restoration_mode},
        )

        observation = preprocessor.prepare(
            source_frame,
            1000,
            None,
            NormalizedRect(x=0.2, y=0.3, width=0.3, height=0.16),
            AnalysisOptions(restoration_mode='classical'),
            None,
        )

        assert observation is not None
        self.assertIs(observation.working_image, enhanced_image)
        self.assertEqual(observation.diagnostics['workingStage'], 'enhanced')
        self.assertGreater(
            observation.diagnostics['stageScores']['enhanced'],
            observation.diagnostics['stageScores']['restored'],
        )

    def test_interval_sample_disables_restoration_for_interactive_fast_path(self) -> None:
        options = AnalysisOptions(restoration_mode='mambairv2', enable_recognizer_comparison=True)

        sample_options = options.for_interval_sample(sample_count_hint=12)

        self.assertFalse(sample_options.enable_recognizer_comparison)
        self.assertFalse(sample_options.enable_secondary_subcrop_ocr)
        self.assertEqual(sample_options.restoration_mode, 'off')
        self.assertFalse(sample_options.persist_artifacts)
        self.assertIsNone(sample_options.debug_tag)

    def test_interval_sample_disables_temporal_support_for_dense_ranges(self) -> None:
        options = AnalysisOptions(temporal_window_ms=260, temporal_neighbor_count=5)

        sample_options = options.for_interval_sample(sample_count_hint=64)

        self.assertEqual(sample_options.temporal_window_ms, 0)
        self.assertEqual(sample_options.temporal_neighbor_count, 1)

    def test_interactive_frame_enables_secondary_subcrop_ocr(self) -> None:
        options = AnalysisOptions(restoration_mode='mambairv2', enable_recognizer_comparison=True)

        frame_options = options.for_interactive_frame()

        self.assertTrue(frame_options.enable_secondary_subcrop_ocr)
        self.assertFalse(frame_options.enable_recognizer_comparison)

    def test_persist_artifacts_requires_developer_diagnostics(self) -> None:
        options = build_analysis_options_from_payload({
            'analysisOptions': {
                'persistArtifacts': True,
                'debugTag': 'smoke-case',
            },
        })

        self.assertFalse(options.enable_developer_diagnostics)
        self.assertFalse(options.persist_artifacts)

        developer_options = build_analysis_options_from_payload({
            'enableDeveloperDiagnostics': True,
            'analysisOptions': {
                'persistArtifacts': True,
                'debugTag': 'smoke-case',
            },
        })

        self.assertTrue(developer_options.enable_developer_diagnostics)
        self.assertTrue(developer_options.persist_artifacts)

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