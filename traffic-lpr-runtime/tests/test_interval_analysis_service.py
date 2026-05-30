from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.application.interval_analysis_service import IntervalAnalysisDependencies, IntervalAnalysisService
from traffic_lpr_runtime.application.pipeline_support import AnalysisOptions
from traffic_lpr_runtime.domain.models import FrameSample, PlateCandidate, QualityMetrics, TargetTrack, TrackedRegion
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


def make_candidate(text: str, confidence: float = 0.88) -> PlateCandidate:
    return PlateCandidate(
        id=f'candidate-{text}',
        text=text,
        confidence=confidence,
        source='fused',
        frame_time_ms=150,
        country_code='TW',
        box=NormalizedRect(x=0.2, y=0.3, width=0.18, height=0.08),
        quality=make_quality(),
        diagnostics={'supportFrameCount': 2},
    )


class FrameReaderStub:
    def read_frame(self, source_path: str, time_ms: int):
        return {'sourcePath': source_path, 'timeMs': time_ms}


class IntervalAnalysisServiceTests(unittest.TestCase):
    def test_service_resolves_policy_and_returns_typed_diagnostics_payload(self) -> None:
        calls: dict[str, object] = {}
        candidate = make_candidate('RJE5752')

        def track_target_across_interval(source_path, interval, anchor_time_ms, vehicle_kind, selected_target_box, sample_every_ms, max_samples, options, preserve_dense):
            del source_path, interval, vehicle_kind, selected_target_box, options, preserve_dense
            calls['sampleEveryMs'] = sample_every_ms
            calls['maxSamples'] = max_samples
            return [
                TrackedRegion(
                    id='track-150',
                    time_ms=150,
                    box=NormalizedRect(x=0.1, y=0.2, width=0.3, height=0.2),
                    confidence=0.9,
                    class_name='car',
                    diagnostics={'isAnchorFrame': anchor_time_ms == 150, 'isEvidenceSample': True, 'evidenceReasons': ['anchor']},
                )
            ], {'trackerMode': 'stub', 'requestedTrackingFrameCount': 1}

        def analyze_plate_candidates(frame, time_ms, marker_rect, target_box, country_hints, options, artifact_root, support_observations=None):
            del frame, marker_rect, country_hints, options, artifact_root, support_observations
            sample = FrameSample(
                id=f'sample-{time_ms}',
                time_ms=time_ms,
                target_box=target_box,
                plate_box=candidate.box,
                quality=make_quality(),
                candidates=[candidate],
                image_path=None,
                diagnostics={},
            )
            return [candidate], sample, None

        service = IntervalAnalysisService(
            IntervalAnalysisDependencies(
                ensure_ready=lambda: None,
                status=lambda: {'ready': True, 'detail': 'ok'},
                runtime_root=lambda: Path('.runtime'),
                frame_reader=FrameReaderStub(),
                track_target_across_interval=track_target_across_interval,
                calibrate_interval_target_boxes=lambda tracked_frames, anchor_time_ms, selected_target_box: {},
                analyze_plate_candidates=analyze_plate_candidates,
                aggregate_candidates=lambda samples, observations, country_hints, options, artifact_root: ([candidate], {'sequence': {'sequenceTier': 'stable', 'supportFrameCount': 3, 'persistenceRatio': 1.0, 'supportFrameGapCount': 0}}),
                apply_reliability_selection=lambda candidates, samples, country_hints, options, interval_mode: (candidates, candidate.id, {'suggestedCandidateId': candidate.id, 'acceptedMargin': 0.4, 'reasons': []}),
                build_track_payload=lambda tracked_frames, diagnostics: [
                    TargetTrack(id='track', class_name='car', label='car 1', confidence=0.9, frames=tracked_frames, diagnostics=diagnostics)
                ],
            )
        )

        response = service.run({
            'sourcePath': 'demo.mp4',
            'interval': {'startMs': 0, 'endMs': 3000},
            'anchorTimeMs': 150,
            'targetVehicleKind': 'car',
            'selectedTargetBox': {'x': 0.1, 'y': 0.2, 'width': 0.3, 'height': 0.2},
            'countryHints': ['TW'],
            'analysisIntent': 'interactive-range',
            'sampleEveryMs': 214,
            'maxSamples': 14,
            'analysisOptions': AnalysisOptions().to_payload(),
        })

        self.assertEqual(calls['sampleEveryMs'], 150)
        self.assertEqual(calls['maxSamples'], 16)
        self.assertEqual(response['candidates'][0]['text'], 'RJE5752')
        self.assertEqual(response['diagnostics']['analysisPolicy']['intent'], 'interactive-short-range')
        self.assertEqual(response['diagnostics']['timing']['temporalSupportBudget'], 0)
        self.assertEqual(response['review']['status'], 'accepted')


if __name__ == '__main__':
    unittest.main()