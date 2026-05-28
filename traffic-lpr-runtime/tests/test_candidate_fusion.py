from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.application.candidate_fusion import CandidateFusionService
from traffic_lpr_runtime.application.pipeline_support import AnalysisOptions
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


if __name__ == '__main__':
    unittest.main()