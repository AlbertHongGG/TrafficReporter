from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.application.services.fusion.candidate_fusion import (
    CandidateFusionService,
    MAX_INTERVAL_FUSION_OBSERVATIONS,
    apply_reliability_selection,
    _candidate_weight,
)
from traffic_lpr_runtime.domain.analysis_options import AnalysisOptions
from traffic_lpr_runtime.application.services.preprocessing import PlateObservation
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


def make_sample_with_candidates(sample_id: str, time_ms: int, candidates: list[PlateCandidate]) -> FrameSample:
    return FrameSample(
        id=sample_id,
        time_ms=time_ms,
        target_box=None,
        plate_box=None,
        quality=candidates[0].quality if candidates else make_quality(0.6),
        candidates=candidates,
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
    def test_interval_review_prefers_taiwan_long_format_over_mixed_noise(self) -> None:
        mixed_noise = make_candidate('mixed-noise', 'AJFM40', 0.48, 0.74, 2700)
        mixed_noise.diagnostics = {'supportFrames': [2700]}
        taiwan_long = make_candidate('taiwan-long', 'XJE5752', 0.46, 0.76, 2700)
        taiwan_long.diagnostics = {'supportFrames': [2550, 2700, 2850]}

        ordered, accepted_id, diagnostics = apply_reliability_selection(
            [mixed_noise, taiwan_long],
            [make_sample_with_candidates('sample-1', 2700, [mixed_noise, taiwan_long])],
            ['tw'],
            AnalysisOptions(min_accepted_confidence=0.72, min_candidate_margin=0.12),
            interval_mode=True,
        )

        self.assertIsNone(accepted_id)
        self.assertEqual(ordered[0].id, 'taiwan-long')
        self.assertEqual(diagnostics['suggestedCandidateId'], 'taiwan-long')
        self.assertGreater(diagnostics['formatScore'], 0.95)

    def test_best_frame_carry_through_does_not_promote_isolated_text(self) -> None:
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
        self.assertLess(fused_candidates[0].confidence, 1.0)
        self.assertEqual(diagnostics['sequence']['sequenceTier'], 'drifting')

    def test_long_taiwan_candidate_can_win_from_top_three_character_evidence(self) -> None:
        service = CandidateFusionService(
            dependencies=SimpleNamespace(cv2=None, numpy=None),
            primary_recognizer=_RecognizerStub(),
        )

        samples = [
            make_sample_with_candidates(
                'sample-1',
                1600,
                [
                    make_candidate('ra-1', 'RA5557', 0.91, 0.84, 1600),
                    make_candidate('rje-1', 'RJE5752', 0.74, 0.9, 1600),
                ],
            ),
            make_sample_with_candidates(
                'sample-2',
                1780,
                [
                    make_candidate('pj-2', 'PJ5557', 0.9, 0.84, 1780),
                    make_candidate('rje-2', 'RJE5752', 0.76, 0.9, 1780),
                ],
            ),
            make_sample_with_candidates(
                'sample-3',
                1900,
                [
                    make_candidate('ra-3', 'RA5557', 0.88, 0.82, 1900),
                    make_candidate('rje-3', 'RJE5752', 0.78, 0.91, 1900),
                ],
            ),
            make_sample_with_candidates(
                'sample-4',
                2080,
                [
                    make_candidate('pj-4', 'PJ5557', 0.86, 0.82, 2080),
                    make_candidate('rje-4', 'RJE5752', 0.75, 0.9, 2080),
                ],
            ),
        ]

        fused_candidates, diagnostics = service.aggregate_candidates(
            samples,
            observations=[],
            country_hints=['tw'],
            options=AnalysisOptions(),
            artifact_root=None,
        )

        self.assertEqual(fused_candidates[0].text, 'RJE5752')
        self.assertTrue(diagnostics['charFusionApplied'])
        self.assertIn('char-fused', fused_candidates[0].diagnostics['consensusSignals'])

    def test_fragmented_interval_winner_requires_review_after_confidence_cap(self) -> None:
        top_candidate = PlateCandidate(
            id='candidate-fragmented',
            text='PJ5557',
            confidence=0.58,
            source='fused',
            frame_time_ms=1900,
            country_code='TW',
            box=None,
            quality=make_quality(0.84),
            diagnostics={
                'supportFrames': [1900],
                'sequenceTier': 'fragmented',
                'sequenceSupportRatio': 0.25,
                'sequenceCharacterConsistencyMean': 0.48,
            },
        )

        ordered_candidates, accepted_candidate_id, diagnostics = apply_reliability_selection(
            [top_candidate],
            [make_sample_with_candidates('sample-1900', 1900, [top_candidate])],
            ['tw'],
            AnalysisOptions(min_accepted_confidence=0.62, min_candidate_margin=0.08),
            True,
        )

        self.assertIsNone(accepted_candidate_id)
        self.assertTrue(diagnostics['reviewRequired'])
        self.assertIn('unstable-sequence', diagnostics['reasons'])
        self.assertIn('weak-sequence-support', diagnostics['reasons'])
        self.assertEqual(ordered_candidates[0].diagnostics['selection']['isSuggested'], True)

    def test_consensus_signals_are_exposed_on_interval_winner(self) -> None:
        service = CandidateFusionService(
            dependencies=SimpleNamespace(cv2=None, numpy=None),
            primary_recognizer=_RecognizerStub(),
        )

        samples = [
            make_sample_with_candidates(
                'sample-1',
                1000,
                [
                    make_candidate('ra-1', 'RA5557', 0.95, 0.95, 1000),
                    make_candidate('pj-1', 'PJ5557', 0.88, 0.88, 1000),
                ],
            ),
            make_sample_with_candidates(
                'sample-2',
                1120,
                [
                    make_candidate('ra-2', 'RA5557', 0.86, 0.84, 1120),
                    make_candidate('pj-2', 'PJ5557', 0.9, 0.9, 1120),
                ],
            ),
            make_sample_with_candidates(
                'sample-3',
                1240,
                [
                    make_candidate('ra-3', 'RA5557', 0.84, 0.83, 1240),
                    make_candidate('pj-3', 'PJ5557', 0.89, 0.88, 1240),
                ],
            ),
            make_sample_with_candidates(
                'sample-4',
                1360,
                [
                    make_candidate('ra-4', 'RA5557', 0.83, 0.82, 1360),
                    make_candidate('pj-4', 'PJ5557', 0.87, 0.87, 1360),
                ],
            ),
        ]

        fused_candidates, diagnostics = service.aggregate_candidates(
            samples,
            observations=[],
            country_hints=['tw'],
            options=AnalysisOptions(),
            artifact_root=None,
        )

        self.assertGreaterEqual(len(fused_candidates), 2)
        self.assertEqual(fused_candidates[0].text, 'RA5557')
        self.assertEqual(
            fused_candidates[0].diagnostics['consensusSignals'],
            ['dominant-sequence', 'char-fused', 'best-frame'],
        )
        self.assertGreater(fused_candidates[0].diagnostics['consensusMultiplier'], 1.0)
        self.assertEqual(fused_candidates[0].diagnostics['runnerUpText'], 'PJ5557')
        self.assertGreater(fused_candidates[0].diagnostics['marginToRunnerUp'], 0.0)
        self.assertEqual(diagnostics['candidateRanking']['leaderText'], 'RA5557')
        self.assertEqual(diagnostics['candidateRanking']['runnerUpText'], 'PJ5557')

    def test_low_consistency_char_fusion_is_penalized_when_it_disagrees_with_dominant_sequence(self) -> None:
        mismatched_char_fusion = PlateCandidate(
            id='char-fused-mismatch',
            text='PJ5557',
            confidence=0.56,
            source='fused-char',
            frame_time_ms=1900,
            country_code='TW',
            box=None,
            quality=make_quality(0.9),
            diagnostics={
                'characterConsistencyMean': 0.56,
                'matchesDominantSequence': False,
            },
        )
        aligned_char_fusion = PlateCandidate(
            id='char-fused-match',
            text='RA5557',
            confidence=0.82,
            source='fused-char',
            frame_time_ms=1800,
            country_code='TW',
            box=None,
            quality=make_quality(0.9),
            diagnostics={
                'characterConsistencyMean': 0.82,
                'matchesDominantSequence': True,
            },
        )

        source_weights = {'fused-char': 1.12}

        self.assertLess(
            _candidate_weight(mismatched_char_fusion, source_weights),
            _candidate_weight(aligned_char_fusion, source_weights),
        )

    def test_reliability_selection_prefers_format_complete_fallback_candidate(self) -> None:
        top_candidate = PlateCandidate(
            id='gm500',
            text='GM500',
            confidence=0.68422406789603,
            source='ocr:cct-xs-v2-global-model',
            frame_time_ms=2535,
            country_code='TW',
            box=None,
            quality=make_quality(0.84),
            diagnostics={},
        )
        fallback_candidate = PlateCandidate(
            id='bjf5714',
            text='BJF5714',
            confidence=0.6417224917425172,
            source='ocr:cct-s-v2-global-model',
            frame_time_ms=2535,
            country_code='TW',
            box=None,
            quality=make_quality(0.84),
            diagnostics={},
        )

        ordered_candidates, accepted_candidate_id, diagnostics = apply_reliability_selection(
            [top_candidate, fallback_candidate],
            [make_sample_with_candidates('sample-2535', 2535, [top_candidate, fallback_candidate])],
            ['tw'],
            AnalysisOptions(min_accepted_confidence=0.72, min_candidate_margin=0.12),
            False,
        )

        self.assertIsNone(accepted_candidate_id)
        self.assertEqual(ordered_candidates[0].text, 'BJF5714')
        self.assertTrue(diagnostics['usedFallback'])
        self.assertEqual(diagnostics['topCandidateText'], 'GM500')
        self.assertEqual(diagnostics['suggestedText'], 'BJF5714')
        self.assertEqual(diagnostics['formatScore'], 1.0)
        self.assertEqual(ordered_candidates[0].diagnostics['selection']['reasons'], ['low-confidence', 'low-margin'])

    def test_interval_review_does_not_suggest_format_incomplete_sample_candidate(self) -> None:
        top_candidate = PlateCandidate(
            id='single-char',
            text='4',
            confidence=0.69,
            source='ocr:cct-xs-v2-global-model',
            frame_time_ms=2288,
            country_code='TW',
            box=None,
            quality=make_quality(0.9),
            diagnostics={'supportFrames': [2288], 'sequenceTier': 'fragmented', 'sequenceSupportRatio': 0.1, 'sequenceCharacterConsistencyMean': 0.3},
        )
        plate_like_candidate = PlateCandidate(
            id='plate-like',
            text='RJE5752',
            confidence=0.48,
            source='fused',
            frame_time_ms=1900,
            country_code='TW',
            box=None,
            quality=make_quality(0.82),
            diagnostics={'supportFrames': [1900, 2050], 'sequenceTier': 'fragmented', 'sequenceSupportRatio': 0.2, 'sequenceCharacterConsistencyMean': 0.42},
        )

        ordered_candidates, accepted_candidate_id, diagnostics = apply_reliability_selection(
            [top_candidate, plate_like_candidate],
            [make_sample_with_candidates('sample-2288', 2288, [top_candidate])],
            ['tw'],
            AnalysisOptions(min_accepted_confidence=0.72, min_candidate_margin=0.12),
            True,
        )

        self.assertIsNone(accepted_candidate_id)
        self.assertEqual(ordered_candidates[0].text, 'RJE5752')
        self.assertEqual(diagnostics['suggestedText'], 'RJE5752')
        self.assertIn('unstable-sequence', diagnostics['reasons'])
        self.assertNotIn('format-mismatch', diagnostics['reasons'])

    def test_interval_review_keeps_fused_candidate_when_sample_fallback_has_same_text(self) -> None:
        fused_candidate = PlateCandidate(
            id='fused-rte',
            text='RTE5752',
            confidence=0.50,
            source='fused',
            frame_time_ms=1995,
            country_code='TW',
            box=None,
            quality=make_quality(0.84),
            diagnostics={'supportFrames': [1845, 1995], 'sequenceTier': 'fragmented', 'sequenceSupportRatio': 0.18, 'sequenceCharacterConsistencyMean': 0.4},
        )
        sample_candidate = PlateCandidate(
            id='baseline-rte',
            text='RTE5752',
            confidence=0.71,
            source='baseline',
            frame_time_ms=1995,
            country_code='TW',
            box=None,
            quality=make_quality(0.9),
            diagnostics=None,
        )

        ordered_candidates, accepted_candidate_id, diagnostics = apply_reliability_selection(
            [fused_candidate],
            [make_sample_with_candidates('sample-1995', 1995, [sample_candidate])],
            ['tw'],
            AnalysisOptions(min_accepted_confidence=0.72, min_candidate_margin=0.12),
            True,
        )

        self.assertIsNone(accepted_candidate_id)
        self.assertEqual(ordered_candidates[0].id, 'fused-rte')
        self.assertFalse(diagnostics['usedFallback'])

    def test_interval_review_keeps_format_complete_top_candidate_despite_weaker_support(self) -> None:
        top_candidate = PlateCandidate(
            id='rje',
            text='RJE5752',
            confidence=0.51,
            source='fused',
            frame_time_ms=2080,
            country_code='TW',
            box=None,
            quality=make_quality(0.82),
            diagnostics={'supportFrames': [2080, 2230], 'sequenceTier': 'fragmented', 'sequenceSupportRatio': 0.14, 'sequenceCharacterConsistencyMean': 0.32},
        )
        dominant_but_wrong = PlateCandidate(
            id='ra',
            text='RA5557',
            confidence=0.52,
            source='fused',
            frame_time_ms=1750,
            country_code='TW',
            box=None,
            quality=make_quality(0.84),
            diagnostics={'supportFrames': [1600, 1750, 1900], 'sequenceTier': 'fragmented', 'sequenceSupportRatio': 0.21, 'sequenceCharacterConsistencyMean': 0.32},
        )

        ordered_candidates, accepted_candidate_id, diagnostics = apply_reliability_selection(
            [top_candidate, dominant_but_wrong],
            [make_sample_with_candidates('sample-2080', 2080, [top_candidate])],
            ['tw'],
            AnalysisOptions(min_accepted_confidence=0.72, min_candidate_margin=0.12),
            True,
        )

        self.assertIsNone(accepted_candidate_id)
        self.assertEqual(ordered_candidates[0].text, 'RJE5752')
        self.assertEqual(diagnostics['suggestedText'], 'RJE5752')

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
                working_stage='working',
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