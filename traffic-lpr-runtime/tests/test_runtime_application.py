from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.application.services.analysis.plate_analyzer import PlateAnalysisService
from traffic_lpr_runtime.domain.analysis_options import AnalysisOptions
from traffic_lpr_runtime.domain.models import FrameSample, PlateCandidate, QualityMetrics
from traffic_lpr_runtime.domain.value_objects import NormalizedRect

try:
    import numpy as np
except Exception:  # pragma: no cover - dependency-gated test environment
    np = None


def make_quality() -> QualityMetrics:
    return QualityMetrics(
        sharpness=0.8,
        contrast=0.8,
        plate_area=0.08,
        angle_score=0.9,
        occlusion_score=0.9,
        glare_score=0.8,
        legibility_score=0.86,
        overall_score=0.84,
        legibility_level='good',
    )


class RecognizerStub:
    def __init__(self) -> None:
        self.crop_calls = 0

    def recognize(self, image, time_ms: int, crop_box: NormalizedRect | None) -> list[PlateCandidate]:
        del image, crop_box
        return [
            PlateCandidate(
                id=f'baseline-{time_ms}',
                text='ABC1234',
                confidence=0.9,
                source='baseline',
                frame_time_ms=time_ms,
                country_code='TW',
                box=NormalizedRect(x=0.2, y=0.3, width=0.18, height=0.08),
                quality=make_quality(),
                diagnostics={},
            )
        ]


class HardPlateRecognizerStub:
    def recognize(self, image, time_ms: int, crop_box: NormalizedRect | None) -> list[PlateCandidate]:
        del image, time_ms, crop_box
        return []

    def recognize_plate_crop(self, image, time_ms: int, plate_box, country_hints, model_names):
        del time_ms, plate_box, country_hints
        height, width = image.shape[:2]
        if (height, width) == (80, 83) and list(model_names) == ['cct-xs-v2-global-model']:
            return [
                PlateCandidate(
                    id='ocr-original',
                    text='GM400',
                    confidence=0.38,
                    source='ocr:cct-xs-v2-global-model',
                    frame_time_ms=2535,
                    country_code='TW',
                    box=None,
                    quality=make_quality(),
                    diagnostics={},
                )
            ]
        if (height, width) == (37, 47) and 'cct-s-v2-global-model' in model_names:
            return [
                PlateCandidate(
                    id='ocr-subcrop',
                    text='BJF5714',
                    confidence=0.64,
                    source='ocr:cct-s-v2-global-model',
                    frame_time_ms=2535,
                    country_code='TW',
                    box=None,
                    quality=make_quality(),
                    diagnostics={},
                )
            ]
        return []


class PlateAnalysisServiceTests(unittest.TestCase):
    def test_baseline_recognizer_backend_skips_crop_refinement(self) -> None:
        recognizer = RecognizerStub()
        plate_preprocessor = types.SimpleNamespace(
            prepare=lambda *args, **kwargs: types.SimpleNamespace(
                working_image=object(),
                enhanced_image=object(),
                rectified_image=object(),
                original_image=object(),
                quality=make_quality(),
                plate_box=NormalizedRect(x=0.2, y=0.3, width=0.18, height=0.08),
                artifact_paths={},
                diagnostics={},
                ocr_candidates=[],
            )
        )
        quality_scorer = types.SimpleNamespace(score=lambda image, box: make_quality())
        candidate_fusion = types.SimpleNamespace(
            fuse_candidates=lambda *args, **kwargs: [],
            aggregate_candidates=lambda *args, **kwargs: ([], {}),
            rank_sample_candidates=lambda baseline, crop, observation: baseline + crop,
        )

        service = PlateAnalysisService(
            primary_recognizer=recognizer,
            plate_preprocessor=plate_preprocessor,
            quality_scorer=quality_scorer,
            candidate_fusion=candidate_fusion,
        )

        fake_frame = np.zeros((100, 100, 3), dtype=np.uint8) if np is not None else types.SimpleNamespace(shape=(100, 100, 3))
        candidates, sample, observation = service.analyze_plate_candidates(
            frame=fake_frame,
            time_ms=100,
            marker_rect=None,
            target_box=NormalizedRect(x=0.1, y=0.2, width=0.3, height=0.3),
            country_hints=['tw'],
            options=AnalysisOptions(recognizer_backend='baseline'),
            artifact_root=None,
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(recognizer.crop_calls, 0)
        self.assertEqual(sample.diagnostics['recognizerBackend'], 'baseline')
        self.assertFalse(sample.diagnostics['allowCropRefinement'])
        self.assertIsNone(observation)

    @unittest.skipIf(np is None, 'NumPy is required for OCR crop regression tests.')
    def test_recognize_observation_crop_adds_secondary_subcrop_candidates_for_hard_plate(self) -> None:
        recognizer = HardPlateRecognizerStub()
        service = PlateAnalysisService(
            primary_recognizer=recognizer,
            plate_preprocessor=types.SimpleNamespace(),
            quality_scorer=types.SimpleNamespace(),
            candidate_fusion=types.SimpleNamespace(),
        )

        observation = types.SimpleNamespace(
            working_image=np.zeros((40, 128, 3), dtype=np.uint8),
            enhanced_image=np.zeros((40, 128, 3), dtype=np.uint8),
            rectified_image=np.zeros((40, 128, 3), dtype=np.uint8),
            original_image=np.zeros((80, 83, 3), dtype=np.uint8),
            diagnostics={
                'qualityRoute': 'high-angle',
                'ocrCropBox': {
                    'x': 0.21702389717102052,
                    'y': 0.2337021075538434,
                    'width': 0.06488330187620936,
                    'height': 0.11165465683836012,
                },
                'sourcePlateBox': {
                    'x': 0.23108639717102053,
                    'y': 0.2735787707104006,
                    'width': 0.0367583018762094,
                    'height': 0.03190133052524574,
                },
            },
        )

        candidates = service.recognize_observation_crop(
            observation,
            2535,
            NormalizedRect(x=0.23108639717102053, y=0.2735787707104006, width=0.0367583018762094, height=0.03190133052524574),
            ['tw'],
            AnalysisOptions(enable_recognizer_comparison=False, enable_secondary_subcrop_ocr=True),
        )

        texts = [candidate.text for candidate in candidates]
        self.assertIn('GM400', texts)
        self.assertIn('BJF5714', texts)
        secondary_candidate = next(candidate for candidate in candidates if candidate.text == 'BJF5714')
        self.assertEqual(secondary_candidate.diagnostics['ocrVariant'], 'secondary-subcrop')
        self.assertEqual(secondary_candidate.diagnostics['subcrop'], {'wx': 0.0, 'hy': 0.3})


if __name__ == '__main__':
    unittest.main()
