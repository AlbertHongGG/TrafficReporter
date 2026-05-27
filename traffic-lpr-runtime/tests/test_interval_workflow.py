from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.application.workflows import IntervalAnalysisWorkflow
from traffic_lpr_runtime.domain.errors import RuntimeFailure
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
    def test_interval_analysis_rejects_anchor_outside_interval(self) -> None:
        workflow = IntervalAnalysisWorkflow(
            ensure_ready=lambda: None,
            status=lambda: {'available': True, 'detail': 'ok'},
            runtime_root=lambda: Path('runtime-root'),
            frame_reader=type('FrameReaderStub', (), {'read_frame': staticmethod(lambda source_path, time_ms: object())})(),
            track_target_across_interval=lambda *args, **kwargs: ([], {'trackerMode': 'botsort'}),
            calibrate_interval_target_boxes=lambda *args, **kwargs: {},
            analyze_plate_candidates=lambda *args, **kwargs: ([], None, None),
            aggregate_candidates=lambda samples, observations, country_hints, options, artifact_root: ([], {'mode': 'stub'}),
            apply_reliability_selection=lambda candidates, samples, country_hints, options, interval_mode: (candidates, None, {'suggestedCandidateId': None, 'acceptedCandidateId': None, 'reviewRequired': False, 'reasons': []}),
            build_track_payload=lambda tracked_frames, diagnostics: [],
        )

        with self.assertRaises(RuntimeFailure):
            workflow.run({
                'sourcePath': 'demo.mp4',
                'interval': {'startMs': 10000, 'endMs': 12000},
                'anchorTimeMs': 9000,
                'targetVehicleKind': 'motorcycle',
                'selectedTargetBox': {'x': 0.2, 'y': 0.3, 'width': 0.18, 'height': 0.1},
                'countryHints': ['tw'],
            })

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

    def test_interval_analysis_returns_degraded_result_when_anchor_mismatch_still_has_samples(self) -> None:
        selected_target_box = NormalizedRect(x=0.12, y=0.22, width=0.12, height=0.26)
        tracked_region = TrackedRegion(
            id='track-1',
            time_ms=11000,
            box=NormalizedRect(x=0.56, y=0.18, width=0.18, height=0.24),
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

        workflow = IntervalAnalysisWorkflow(
            ensure_ready=lambda: None,
            status=lambda: {'available': True, 'detail': 'ok'},
            runtime_root=lambda: Path('runtime-root'),
            frame_reader=type('FrameReaderStub', (), {'read_frame': staticmethod(lambda source_path, time_ms: object())})(),
            track_target_across_interval=lambda *args, **kwargs: ([tracked_region], {'trackerMode': 'botsort'}),
            calibrate_interval_target_boxes=lambda *args, **kwargs: {},
            analyze_plate_candidates=lambda frame, time_ms, marker_rect, target_box, country_hints, options, artifact_root: (
                [candidate],
                FrameSample(
                    id=f'sample-{time_ms}',
                    time_ms=time_ms,
                    target_box=target_box,
                    plate_box=None,
                    quality=make_quality(),
                    candidates=[candidate],
                    image_path=None,
                    diagnostics={},
                ),
                None,
            ),
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
            'selectedTargetBox': selected_target_box.to_payload(),
            'countryHints': ['tw'],
            'maxSamples': 4,
        })

        self.assertEqual(result['jobStatus'], 'degraded')
        self.assertEqual(result['tracking']['trackingTier'], 'anchor-invalid')
        self.assertEqual(result['tracking']['anchorStatus'], 'mismatched')
        self.assertGreater(result['tracking']['coverageRatio'], 0.0)
        self.assertEqual(result['review']['status'], 'review-required')

    def test_interval_analysis_forces_review_when_tracking_identity_breaks(self) -> None:
        selected_target_box = NormalizedRect(x=0.32, y=0.2, width=0.18, height=0.24)
        tracked_region = TrackedRegion(
            id='track-1',
            time_ms=11000,
            box=selected_target_box,
            confidence=0.92,
            class_name='motorcycle',
            diagnostics={
                'trackingSource': 'detection-fallback',
                'selectionScore': 0.41,
            },
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

        workflow = IntervalAnalysisWorkflow(
            ensure_ready=lambda: None,
            status=lambda: {'available': True, 'detail': 'ok'},
            runtime_root=lambda: Path('runtime-root'),
            frame_reader=type('FrameReaderStub', (), {'read_frame': staticmethod(lambda source_path, time_ms: object())})(),
            track_target_across_interval=lambda *args, **kwargs: ([tracked_region], {
                'trackerMode': 'botsort',
                'canonicalTargetId': 'target-11000-0',
                'identityBreaks': 1,
                'reassociatedFrames': 1,
                'detectionFallbackFrames': 1,
                'terminatedEarly': True,
            }),
            calibrate_interval_target_boxes=lambda *args, **kwargs: {},
            analyze_plate_candidates=lambda frame, time_ms, marker_rect, target_box, country_hints, options, artifact_root: (
                [candidate],
                FrameSample(
                    id=f'sample-{time_ms}',
                    time_ms=time_ms,
                    target_box=target_box,
                    plate_box=None,
                    quality=make_quality(),
                    candidates=[candidate],
                    image_path=None,
                    diagnostics={},
                ),
                None,
            ),
            aggregate_candidates=lambda samples, observations, country_hints, options, artifact_root: ([candidate], {'mode': 'stub'}),
            apply_reliability_selection=lambda candidates, samples, country_hints, options, interval_mode: (candidates, candidate.id, {'suggestedCandidateId': candidate.id, 'acceptedCandidateId': candidate.id, 'reviewRequired': False, 'reasons': []}),
            build_track_payload=lambda tracked_frames, diagnostics: [
                TargetTrack(
                    id=diagnostics['canonicalTargetId'],
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
            'selectedTargetBox': selected_target_box.to_payload(),
            'selectedTargetTrackId': 'target-11000-0',
            'countryHints': ['tw'],
            'maxSamples': 4,
        })

        self.assertIsNone(result['acceptedCandidateId'])
        self.assertEqual(result['jobStatus'], 'degraded')
        self.assertEqual(result['tracking']['trackingTier'], 'detection-fallback')
        self.assertEqual(result['review']['status'], 'review-required')
        self.assertIn('tracking identity became ambiguous across the interval', result['review']['reasons'])
        self.assertEqual(result['targetTracks'][0]['id'], 'target-11000-0')


if __name__ == '__main__':
    unittest.main()