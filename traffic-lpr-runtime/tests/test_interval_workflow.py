from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.application.workflows import IntervalAnalysisWorkflow
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


class IntervalWorkflowTests(unittest.TestCase):
    def test_interval_analysis_uses_calibrated_target_box_for_sample_analysis(self) -> None:
        raw_box = NormalizedRect(x=0.4, y=0.3, width=0.2, height=0.24)
        calibrated_box = NormalizedRect(x=0.47, y=0.53, width=0.08, height=0.07)
        tracked_region = TrackedRegion(
            id='track-1',
            time_ms=11000,
            box=raw_box,
            confidence=0.92,
            class_name='motorcycle',
        )
        candidate = PlateCandidate(
            id='candidate-1',
            text='NCE9762',
            confidence=0.93,
            source='ocr:fastplate',
            frame_time_ms=11000,
            country_code='TW',
            box=None,
            quality=make_quality(),
        )
        calls: list[NormalizedRect | None] = []

        def analyze_plate_candidates(frame, time_ms, marker_rect, target_box, country_hints, options, artifact_root):
            del frame, marker_rect, country_hints, options, artifact_root
            calls.append(target_box)
            sample = FrameSample(
                id=f'sample-{time_ms}',
                time_ms=time_ms,
                target_box=target_box,
                plate_box=None,
                quality=make_quality(),
                candidates=[candidate],
                image_path=None,
                diagnostics={},
            )
            return [candidate], sample, None

        workflow = IntervalAnalysisWorkflow(
            ensure_ready=lambda: None,
            status=lambda: {'available': True, 'detail': 'ok'},
            runtime_root=lambda: Path('runtime-root'),
            frame_reader=type('FrameReaderStub', (), {'read_frame': staticmethod(lambda source_path, time_ms: object())})(),
            track_target_across_interval=lambda *args, **kwargs: ([tracked_region], {'trackerMode': 'botsort'}),
            calibrate_interval_target_boxes=lambda *args, **kwargs: {11000: calibrated_box},
            analyze_plate_candidates=analyze_plate_candidates,
            aggregate_candidates=lambda samples, observations, country_hints, options, artifact_root: ([candidate], {'mode': 'stub'}),
            apply_reliability_selection=lambda candidates, samples, country_hints, options, interval_mode: (candidates, candidate.id, {'suggestedCandidateId': candidate.id, 'acceptedCandidateId': candidate.id, 'reviewRequired': False, 'reasons': []}),
            build_track_payload=lambda tracked_frames, diagnostics: [
                TargetTrack(
                    id='track-1',
                    class_name='motorcycle',
                    label='motorcycle 11000ms',
                    confidence=0.92,
                    frames=tracked_frames,
                    diagnostics=diagnostics,
                ),
            ],
        )

        result = workflow.run({
            'sourcePath': 'demo.mp4',
            'interval': {'startMs': 10000, 'endMs': 12000},
            'anchorTimeMs': 11000,
            'targetVehicleKind': 'motorcycle',
            'selectedTargetBox': calibrated_box.to_payload(),
            'countryHints': ['tw'],
        })

        self.assertEqual(calls, [calibrated_box])
        self.assertEqual(result['samples'][0]['targetBox'], calibrated_box.to_payload())
        self.assertEqual(result['targetTracks'][0]['frames'][0]['box'], calibrated_box.to_payload())
        self.assertEqual(result['targetTracks'][0]['frames'][0]['diagnostics']['rawTrackingBox'], raw_box.to_payload())


if __name__ == '__main__':
    unittest.main()