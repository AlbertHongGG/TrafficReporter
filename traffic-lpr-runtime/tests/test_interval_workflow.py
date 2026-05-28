from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.application.pipeline_support import AnalysisOptions
from traffic_lpr_runtime.application.workflows import IntervalAnalysisWorkflow
from traffic_lpr_runtime.application.workflows import _resolve_analysis_target_box
from traffic_lpr_runtime.application.workflows import _select_interval_evidence_frames
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
    def test_select_interval_evidence_frames_keeps_sparse_schedule_and_anchor_frame(self) -> None:
        tracked_frames = [
            TrackedRegion(
                id=f'track-{time_ms}',
                time_ms=time_ms,
                box=NormalizedRect(x=0.1 + (index * 0.02), y=0.2, width=0.12, height=0.24),
                confidence=0.72 + (index * 0.03),
                class_name='motorcycle',
                diagnostics={
                    'isEvidenceSample': time_ms in {1000, 1200, 1400, 1600},
                    'isAnchorFrame': time_ms == 1300,
                    'isMotionHotspot': time_ms == 1500,
                    'localMotion': 0.14 if time_ms == 1500 else 0.02,
                    'evidencePriority': 3.0 if time_ms == 1500 else 1.0 + index,
                },
            )
            for index, time_ms in enumerate([1000, 1100, 1200, 1300, 1400, 1500, 1600])
        ]

        evidence_frames = _select_interval_evidence_frames(tracked_frames, AnalysisOptions(temporal_evidence_mode='motion-aware'))

        self.assertEqual([frame.time_ms for frame in evidence_frames], [1000, 1200, 1300, 1400, 1600])
        self.assertTrue(all(frame.diagnostics.get('selectedForEvidenceAnalysis') is True for frame in evidence_frames))

    def test_resolve_analysis_target_box_uses_selected_anchor_box_for_pre_anchor_neighbor(self) -> None:
        selected_box = NormalizedRect(x=0.24, y=0.18, width=0.12, height=0.18)
        raw_box = NormalizedRect(x=0.25, y=0.181, width=0.118, height=0.176)
        calibrated_box = NormalizedRect(x=0.251, y=0.181, width=0.118, height=0.176)

        analysis_box, source = _resolve_analysis_target_box(
            raw_box,
            calibrated_box,
            selected_box,
            sample_time_ms=1750,
            anchor_time_ms=1900,
        )

        self.assertEqual(source, 'selected-anchor-fallback')
        self.assertEqual(analysis_box, selected_box)

    def test_interval_analysis_forces_review_when_sequence_is_fragmented(self) -> None:
        tracked_region = TrackedRegion(
            id='track-1',
            time_ms=11000,
            box=NormalizedRect(x=0.32, y=0.2, width=0.18, height=0.24),
            confidence=0.92,
            class_name='motorcycle',
            diagnostics={'isEvidenceSample': True, 'isAnchorFrame': True},
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
            aggregate_candidates=lambda samples, observations, country_hints, options, artifact_root: (
                [candidate],
                {
                    'mode': 'stub',
                    'sequence': {
                        'sequenceTier': 'fragmented',
                        'dominantText': 'NCE9762',
                        'persistenceRatio': 0.25,
                        'supportFrameCount': 1,
                        'sampleCount': 3,
                        'supportFrameGapCount': 2,
                        'predictionSwitchCount': 1,
                        'characterConsistency': [0.55, 0.52, 0.58],
                        'characterConsistencyMean': 0.55,
                    },
                },
            ),
            apply_reliability_selection=lambda candidates, samples, country_hints, options, interval_mode: (
                candidates,
                candidate.id,
                {'suggestedCandidateId': candidate.id, 'acceptedCandidateId': candidate.id, 'reviewRequired': False, 'reasons': []},
            ),
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
            'selectedTargetBox': tracked_region.box.to_payload(),
            'countryHints': ['tw'],
            'analysisOptions': {
                'sequenceReviewMode': 'strict',
                'minSequencePersistence': 0.7,
                'maxSequenceGapCount': 0,
            },
        })

        self.assertEqual(result['sequence']['sequenceTier'], 'fragmented')
        self.assertEqual(result['acceptedCandidateId'], candidate.id)
        self.assertEqual(result['review']['status'], 'review-required')
        self.assertIn('plate text did not remain stable across interval samples', result['review']['reasons'])

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
        calibrated_box = NormalizedRect(x=0.42, y=0.31, width=0.18, height=0.22)
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
        self.assertEqual(result['analysisTrack']['frames'][0]['box'], calibrated_box.to_payload())
        self.assertEqual(result['analysisTrack']['frames'][0]['diagnostics']['analysisBoxSource'], 'calibrated')
        self.assertEqual(result['analysisTrack']['frames'][0]['diagnostics']['rawTrackingBox'], raw_box.to_payload())
        self.assertEqual(result['targetTracks'][0]['frames'][0]['box'], calibrated_box.to_payload())
        self.assertEqual(result['targetTracks'][0]['frames'][0]['diagnostics']['rawTrackingBox'], raw_box.to_payload())

    def test_interval_analysis_rejects_drifted_calibrated_box_and_keeps_raw_tracking_box(self) -> None:
        raw_box = NormalizedRect(x=0.18, y=0.24, width=0.2, height=0.22)
        drifted_box = NormalizedRect(x=0.62, y=0.08, width=0.16, height=0.16)
        tracked_region = TrackedRegion(
            id='track-1',
            time_ms=11000,
            box=raw_box,
            confidence=0.94,
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
        calls: list[NormalizedRect] = []

        def analyze_plate_candidates(frame, time_ms, plate_box, target_box, country_hints, options, artifact_root):
            calls.append(target_box)
            sample = FrameSample(
                id='sample-11000',
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
            calibrate_interval_target_boxes=lambda *args, **kwargs: {11000: drifted_box},
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
            'selectedTargetBox': raw_box.to_payload(),
            'countryHints': ['tw'],
        })

        self.assertEqual(calls, [raw_box])
        self.assertEqual(result['samples'][0]['targetBox'], raw_box.to_payload())
        self.assertEqual(result['analysisTrack']['frames'][0]['box'], raw_box.to_payload())
        self.assertEqual(result['analysisTrack']['frames'][0]['diagnostics']['analysisBoxSource'], 'raw-tracking-fallback')
        self.assertEqual(result['analysisTrack']['frames'][0]['diagnostics']['calibratedBox'], drifted_box.to_payload())

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

        self.assertEqual(result['acceptedCandidateId'], candidate.id)
        self.assertEqual(result['jobStatus'], 'degraded')
        self.assertEqual(result['tracking']['trackingTier'], 'detection-fallback')
        self.assertEqual(result['review']['status'], 'review-required')
        self.assertIn('tracking identity became ambiguous across the interval', result['review']['reasons'])
        self.assertEqual(result['analysisTrack']['id'], 'target-11000-0')
        self.assertEqual(result['targetTracks'][0]['id'], 'target-11000-0')

    def test_interval_analysis_keeps_accepted_result_when_tracking_only_degraded(self) -> None:
        selected_target_box = NormalizedRect(x=0.32, y=0.2, width=0.18, height=0.24)
        tracked_region = TrackedRegion(
            id='track-1',
            time_ms=11000,
            box=selected_target_box,
            confidence=0.92,
            class_name='motorcycle',
            diagnostics={
                'trackingSource': 'detection-fallback',
                'selectionScore': 0.53,
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
                'identityBreaks': 0,
                'reassociatedFrames': 2,
                'detectionFallbackFrames': 2,
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
            aggregate_candidates=lambda samples, observations, country_hints, options, artifact_root: ([candidate], {'mode': 'stub', 'sequence': {'sequenceTier': 'stable', 'persistenceRatio': 1.0, 'supportFrameCount': 3, 'supportFrameGapCount': 0}}),
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

        self.assertEqual(result['acceptedCandidateId'], candidate.id)
        self.assertEqual(result['tracking']['trackingTier'], 'detection-fallback')
        self.assertEqual(result['review']['status'], 'accepted')
        self.assertIn('tracker had to reacquire the target from fresh detections', result['review']['reasons'])
        self.assertIn('tracking required fresh detection fallback to keep the target alive', result['review']['reasons'])

    def test_interval_analysis_keeps_accepted_result_when_sequence_only_drifting(self) -> None:
        selected_target_box = NormalizedRect(x=0.32, y=0.2, width=0.18, height=0.24)
        tracked_region = TrackedRegion(
            id='track-1',
            time_ms=11000,
            box=selected_target_box,
            confidence=0.92,
            class_name='motorcycle',
            diagnostics={
                'trackingSource': 'detection-fallback',
                'selectionScore': 0.53,
            },
        )
        candidate = PlateCandidate(
            id='candidate-1',
            text='NCE9762',
            confidence=0.98,
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
                'identityBreaks': 0,
                'reassociatedFrames': 0,
                'detectionFallbackFrames': 1,
                'terminatedEarly': False,
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
            aggregate_candidates=lambda samples, observations, country_hints, options, artifact_root: (
                [candidate],
                {
                    'mode': 'stub',
                    'sequence': {
                        'sequenceTier': 'drifting',
                        'dominantText': 'NCE9762',
                        'persistenceRatio': 0.4,
                        'supportFrameCount': 10,
                        'sampleCount': 10,
                        'supportFrameGapCount': 0,
                        'predictionSwitchCount': 8,
                        'characterConsistency': [0.92, 0.87, 0.96],
                        'characterConsistencyMean': 0.916,
                    },
                },
            ),
            apply_reliability_selection=lambda candidates, samples, country_hints, options, interval_mode: (
                candidates,
                candidate.id,
                {'suggestedCandidateId': candidate.id, 'acceptedCandidateId': candidate.id, 'reviewRequired': False, 'reasons': []},
            ),
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
            'analysisOptions': {
                'sequenceReviewMode': 'strict',
                'minSequencePersistence': 0.72,
                'maxSequenceGapCount': 0,
            },
        })

        self.assertEqual(result['acceptedCandidateId'], candidate.id)
        self.assertEqual(result['review']['status'], 'accepted')
        self.assertIn('plate text did not remain stable across interval samples', result['review']['reasons'])
        self.assertIn('sequence evidence drifted during the interval review path', result['review']['reasons'])


if __name__ == '__main__':
    unittest.main()