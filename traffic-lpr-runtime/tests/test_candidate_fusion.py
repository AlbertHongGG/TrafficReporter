from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.application.candidate_fusion import CandidateFusionService
from traffic_lpr_runtime.application.candidate_fusion import MAX_INTERVAL_FUSION_OBSERVATIONS
from traffic_lpr_runtime.application.pipeline_support import AnalysisOptions
from traffic_lpr_runtime.application.preprocessing import PlateObservation
from traffic_lpr_runtime.domain.models import FrameSample, PlateCandidate, QualityMetrics


def make_quality(overall_score: float) -> QualityMetrics:
    return QualityMetrics(
        sharpness=overall_score,
        contrast=overall_score,
        plate_area=0.08,
        angle_score=0.86,
        occlusion_score=0.9,
        glare_score=0.86,
        legibility_score=overall_score,
        overall_score=overall_score,
        legibility_level='good' if overall_score >= 0.62 else 'poor',
    )


def make_candidate(candidate_id: str, text: str, confidence: float, quality_score: float, time_ms: int) -> PlateCandidate:
    return PlateCandidate(
        id=candidate_id,
        text=text,
        confidence=confidence,
        source='baseline',
        frame_time_ms=time_ms,
        country_code=None,
        box=None,
        quality=make_quality(quality_score),
        diagnostics=None,
    )


def make_sample(sample_id: str, time_ms: int, candidate: PlateCandidate) -> FrameSample:
    return FrameSample(
        id=sample_id,
        time_ms=time_ms,
        target_box=None,
        plate_box=None,
        quality=candidate.quality,
        candidates=[candidate],
        image_path=None,
        diagnostics=None,
    )


class _RecognizerStub:
    def recognize_plate_crop(self, *args, **kwargs):  # pragma: no cover - unused in this regression test
        raise AssertionError('recognizer should not be used when there are no aligned observations')


class _FusionRecognizerStub:
    def recognize_plate_crop(self, image, time_ms, plate_box, country_hints, model_names):
        del image, plate_box, country_hints, model_names
        return [
            PlateCandidate(
                id=f'fused-{time_ms}',
                text='ABC1234',
                confidence=0.94,
                source='ocr:stub',
                frame_time_ms=time_ms,
                country_code='TW',
                box=None,
                quality=make_quality(0.91),
                diagnostics=None,
            ),
        ]


class CandidateFusionTests(unittest.TestCase):
    def test_best_frame_carry_through_preserves_strong_single_frame_text(self) -> None:
        service = CandidateFusionService(
            dependencies=SimpleNamespace(cv2=None, numpy=None),
            primary_recognizer=_RecognizerStub(),
        )

        samples = [
            make_sample('sample-1', 1000, make_candidate('candidate-1', 'ABC1234', 0.96, 0.95, 1000)),
            make_sample('sample-2', 1120, make_candidate('candidate-2', 'A8C1234', 0.55, 0.42, 1120)),
            make_sample('sample-3', 1240, make_candidate('candidate-3', 'A8C1234', 0.57, 0.44, 1240)),
            make_sample('sample-4', 1360, make_candidate('candidate-4', 'A8C1234', 0.54, 0.43, 1360)),
        ]

        fused_candidates, diagnostics = service.aggregate_candidates(
            samples,
            observations=[],
            country_hints=['tw'],
            options=AnalysisOptions(),
            artifact_root=None,
        )

        self.assertGreaterEqual(len(fused_candidates), 2)
        self.assertEqual(fused_candidates[0].text, 'ABC1234')
        self.assertTrue(fused_candidates[0].diagnostics['bestFrameCarryThrough'])
        self.assertEqual(fused_candidates[0].diagnostics['bestFrameTimeMs'], 1000)
        self.assertEqual(diagnostics['sequence']['sequenceTier'], 'drifting')

    def test_aligned_fusion_caps_observations(self) -> None:
        class _Cv2Stub:
            INTER_LANCZOS4 = 1

            @staticmethod
            def resize(image, size, interpolation=None):
                del size, interpolation
                return image

            @staticmethod
            def imwrite(path, image):
                del path, image
                return True

        class _ImageStub:
            def __init__(self, mean_value: int) -> None:
                self.shape = (20, 60, 3)
                self.size = 20 * 60 * 3
                self._mean_value = mean_value

            def astype(self, dtype):
                del dtype
                return self

            def clip(self, low, high):
                del low, high
                return self

            def mean(self):
                return self._mean_value

            def __mul__(self, value):
                del value
                return self

            def __rmul__(self, value):
                del value
                return self

            def __add__(self, other):
                del other
                return self

            def __iadd__(self, other):
                del other
                return self

            def __truediv__(self, other):
                del other
                return self

        class _NumpyStub:
            @staticmethod
            def zeros(shape, dtype=None):
                del shape, dtype
                return _ImageStub(0)

        service = CandidateFusionService(
            dependencies=SimpleNamespace(cv2=_Cv2Stub(), numpy=_NumpyStub()),
            primary_recognizer=_FusionRecognizerStub(),
        )
        align_calls: list[int] = []

        def align(reference_image, candidate_image):
            del reference_image
            align_calls.append(int(candidate_image.mean()))
            return candidate_image, 0.92

        service._align_plate_to_reference = align
        observations = [
            PlateObservation(
                time_ms=1000 + index,
                target_box=None,
                plate_box=None,
                original_image=_ImageStub(100 + index),
                rectified_image=_ImageStub(100 + index),
                enhanced_image=_ImageStub(100 + index),
                restored_image=None,
                working_image=_ImageStub(100 + index),
                quality=make_quality(0.95 - (index * 0.01)),
                artifact_paths={},
                diagnostics={'selectionScore': 0.9 - (index * 0.01)},
            )
            for index in range(MAX_INTERVAL_FUSION_OBSERVATIONS + 3)
        ]

        fused_candidates, diagnostics = service._fuse_aligned_plate_images(
            observations,
            country_hints=['tw'],
            options=AnalysisOptions(),
            artifact_root=None,
        )

        self.assertEqual(len(fused_candidates), 1)
        self.assertEqual(diagnostics['requestedObservationCount'], MAX_INTERVAL_FUSION_OBSERVATIONS + 3)
        self.assertEqual(diagnostics['fusedObservationCount'], MAX_INTERVAL_FUSION_OBSERVATIONS)
        self.assertEqual(len(align_calls), MAX_INTERVAL_FUSION_OBSERVATIONS - 1)


if __name__ == '__main__':
    unittest.main()