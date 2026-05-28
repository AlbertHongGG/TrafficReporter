from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.application.pipeline_support import AnalysisOptions
from traffic_lpr_runtime.application.runtime_application import LprRuntimeApplication
from traffic_lpr_runtime.domain.models import FrameSample, PlateCandidate, QualityMetrics
from traffic_lpr_runtime.domain.value_objects import NormalizedRect


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

    def recognize_plate_crop(self, image, time_ms: int, plate_box, country_hints, model_names):
        del image, time_ms, plate_box, country_hints, model_names
        self.crop_calls += 1
        return [
            PlateCandidate(
                id='ocr-1',
                text='ABC1234',
                confidence=0.96,
                source='ocr:cct-xs-v2-global-model',
                frame_time_ms=100,
                country_code='TW',
                box=None,
                quality=make_quality(),
                diagnostics={},
            )
        ]


class RuntimeApplicationTests(unittest.TestCase):
    def test_baseline_recognizer_backend_skips_crop_refinement(self) -> None:
        recognizer = RecognizerStub()
        app = object.__new__(LprRuntimeApplication)
        app._primary_recognizer = recognizer
        app._quality_scorer = types.SimpleNamespace(score=lambda image, box: make_quality())
        app._select_analysis_roi = lambda frame, marker_rect, target_box: (frame, target_box)
        app._plate_preprocessor = types.SimpleNamespace(
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
        app._rank_sample_candidates = lambda baseline_candidates, crop_candidates, observation: baseline_candidates + crop_candidates

        candidates, sample, observation = app._analyze_plate_candidates(
            frame=object(),
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


if __name__ == '__main__':
    unittest.main()