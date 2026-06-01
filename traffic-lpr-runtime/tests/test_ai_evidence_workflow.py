from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.application.ai_evidence_workflow import (
    AiEvidenceWorkflow,
    RenderedFrame,
    SelectedKeyframe,
    StoryboardSelection,
    _normalize_keyframes,
    _resolve_keyframe_count_reason,
)
from traffic_lpr_runtime.domain.models import TrackedRegion
from traffic_lpr_runtime.domain.value_objects import NormalizedRect
from traffic_lpr_runtime.protocol import install_runtime_progress_sink, reset_runtime_progress_sink


class AiEvidenceWorkflowTests(unittest.TestCase):
    def _build_workflow(
        self,
        *,
        runtime_root: Path,
        provider=None,
        frame_reader=None,
        detect_targets=None,
        analyze_frame=None,
        analyze_interval=None,
        dependencies=None,
    ) -> AiEvidenceWorkflow:
        class ProviderStub:
            kind = 'stub'

            def generate_json(self, **kwargs):
                del kwargs
                return {'selectedTrackId': 'stub-track'}

        return AiEvidenceWorkflow(
            ensure_ready=lambda: None,
            status=lambda: {'available': True, 'detail': 'ok'},
            runtime_root=lambda: runtime_root,
            dependencies=dependencies or object(),
            frame_reader=frame_reader or object(),
            runtime_bridge=type('RuntimeBridgeStub', (), {
                'detect_targets': staticmethod(detect_targets or (lambda *args, **kwargs: [])),
                'analyze_frame': staticmethod(analyze_frame or (lambda payload: payload)),
                'analyze_interval': staticmethod(analyze_interval or (lambda payload: {
                    'targetTracks': [],
                    'samples': [],
                    'candidates': [],
                    'acceptedCandidateId': None,
                    'review': None,
                    'provenance': None,
                })),
            })(),
            provider=provider or ProviderStub(),
        )

    def test_normalize_keyframes_backfills_to_available_unique_frames(self) -> None:
        frames = [
            RenderedFrame('fine-000', 1000, 0, 'fine-000', 'fine-000.jpg', 1280, 720),
            RenderedFrame('fine-001', 1500, 1, 'fine-001', 'fine-001.jpg', 1280, 720),
            RenderedFrame('fine-002', 2000, 2, 'fine-002', 'fine-002.jpg', 1280, 720),
        ]

        result = _normalize_keyframes(
            [
                {'frameId': 'fine-001', 'description': '關鍵幀'},
                {'frameId': 'fine-001', 'description': 'duplicate should collapse'},
            ],
            frames,
            desired_count=8,
        )

        self.assertEqual(len(result), 3)
        self.assertTrue(all(isinstance(item, SelectedKeyframe) for item in result))
        selected_by_id = {item.frame.frame_id: item for item in result}
        self.assertEqual(selected_by_id['fine-001'].description, '關鍵幀')
        self.assertEqual(selected_by_id['fine-001'].description_source, 'llm')
        self.assertEqual(selected_by_id['fine-000'].keyframe_source, 'runtime-supplemented')
        self.assertEqual(selected_by_id['fine-002'].keyframe_source, 'runtime-supplemented')
        self.assertTrue(all(item.is_user_facing for item in result))

    def test_normalize_keyframes_uses_fallback_for_missing_description(self) -> None:
        frames = [
            RenderedFrame('fine-000', 1000, 0, 'fine-000', 'fine-000.jpg', 1280, 720),
            RenderedFrame('fine-001', 1500, 1, 'fine-001', 'fine-001.jpg', 1280, 720),
        ]

        result = _normalize_keyframes(
            [
                {'frameId': 'fine-000', 'description': ''},
                {'frameId': 'fine-001', 'description': '有效關鍵幀'},
            ],
            frames,
            desired_count=8,
        )

        self.assertEqual(len(result), 2)
        self.assertTrue(result[0].is_user_facing)
        self.assertEqual(result[0].description_source, 'fallback')
        self.assertEqual(result[0].supplement_reason, 'missing-description')
        self.assertTrue(result[1].is_user_facing)

    def test_keyframe_count_reason_is_only_returned_below_required_minimum(self) -> None:
        self.assertIsNone(_resolve_keyframe_count_reason(
            rendered_count=8,
            desired_count=8,
            available_frame_count=8,
            provider_reason='provider said fewer were enough',
        ))
        self.assertEqual(
            _resolve_keyframe_count_reason(
                rendered_count=5,
                desired_count=8,
                available_frame_count=5,
                provider_reason=None,
            ),
            'Only 5 distinct fine storyboard frame(s) were available, so 8 keyframes could not be produced.',
        )

    def test_encode_chat_image_upscales_tiny_vision_payloads(self) -> None:
        class Cv2Stub:
            IMWRITE_JPEG_QUALITY = 1
            INTER_AREA = 2
            INTER_CUBIC = 3

            def __init__(self) -> None:
                self.resize_sizes: list[tuple[int, int]] = []
                self.encoded_shape: tuple[int, int] | None = None

            def imread(self, path: str):
                del path
                return np.zeros((23, 36, 3), dtype=np.uint8)

            def resize(self, image, size: tuple[int, int], interpolation: int):
                del image, interpolation
                self.resize_sizes.append(size)
                return np.zeros((size[1], size[0], 3), dtype=np.uint8)

            def imencode(self, extension: str, image, params: list[int]):
                del extension, params
                height, width = image.shape[:2]
                self.encoded_shape = (height, width)
                return True, np.array([1, 2, 3], dtype=np.uint8)

        class DependenciesStub:
            def __init__(self, cv2) -> None:
                self.cv2 = cv2

        with tempfile.TemporaryDirectory() as temp_dir:
            cv2 = Cv2Stub()
            workflow = self._build_workflow(
                runtime_root=Path(temp_dir),
                dependencies=DependenciesStub(cv2),
            )
            image_path = Path(temp_dir) / 'tiny.jpg'
            image_path.write_bytes(b'not-used-by-stub')

            encoded = workflow._encode_chat_image(image_path)

        self.assertEqual(encoded, 'AQID')
        self.assertEqual(cv2.resize_sizes, [(100, 64)])
        self.assertEqual(cv2.encoded_shape, (64, 100))

    def test_render_keyframes_keeps_valid_frames_without_overlay_box(self) -> None:
        class FrameReaderStub:
            def read_frame(self, source_path: str, time_ms: int):
                del source_path, time_ms
                return np.zeros((120, 200, 3), dtype=np.uint8)

        class DependenciesStub:
            cv2 = None

        with tempfile.TemporaryDirectory() as temp_dir:
            workflow = self._build_workflow(
                runtime_root=Path(temp_dir),
                frame_reader=FrameReaderStub(),
                dependencies=DependenciesStub(),
            )
            workflow._prepare_frame_image = lambda image, title, subtitle, box=None, show_header=False: (image, 200, 120)
            workflow._write_image = lambda image_path, image: None

            rendered = workflow._render_keyframes(
                source_path='demo.mp4',
                keyframe_refs=[
                    SelectedKeyframe(
                        frame=RenderedFrame('fine-001', 1000, 1, 'fine-001', 'fine-001.jpg', 200, 120),
                        description='有效描述',
                    ),
                    SelectedKeyframe(
                        frame=RenderedFrame('fine-002', 2200, 2, 'fine-002', 'fine-002.jpg', 200, 120),
                        description='缺描述不該顯示',
                        is_user_facing=False,
                        supplement_reason='missing-description',
                    ),
                ],
                analysis_track={
                    'id': 'track-1',
                    'frames': [{
                        'id': 'track-frame-1',
                        'timeMs': 1500,
                        'box': {'x': 0.2, 'y': 0.2, 'width': 0.2, 'height': 0.2},
                    }],
                },
                output_dir=Path(temp_dir) / 'keyframes',
            )

            self.assertEqual(len(rendered), 1)
            self.assertEqual(rendered[0]['frame']['frameId'], 'fine-001')
            self.assertIsNone(rendered[0]['overlay'])
            self.assertIsNone(rendered[0]['boxSource'])

    def test_run_accepts_typed_storyboard_selections(self) -> None:
        frame = RenderedFrame('fine-001', 1500, 1, 'fine-001', 'fine-001.jpg', 1280, 720)
        keyframe = SelectedKeyframe(frame=frame, description='關鍵幀')

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            workflow = self._build_workflow(runtime_root=runtime_root)

            workflow._probe_duration_ms = lambda source_path: 5000
            workflow._render_storyboard_frames = lambda **kwargs: [frame]
            workflow._select_coarse_interval = lambda request_id, description, frames: StoryboardSelection(
                start_frame=frame,
                end_frame=frame,
                anchor_frame=frame,
                summary='coarse',
            )
            workflow._select_fine_interval = lambda request_id, description, frames, max_keyframes: StoryboardSelection(
                start_frame=frame,
                end_frame=frame,
                anchor_frame=frame,
                summary='fine',
                keyframes=(keyframe,),
            )
            workflow._resolve_target = lambda **kwargs: {'selectedBox': None}
            workflow._render_keyframes = lambda **kwargs: [{
                'frame': frame.to_payload(),
                'description': keyframe.description,
                'overlay': None,
            }]

            result = workflow.run({
                'sourcePath': 'demo.mp4',
                'description': '機車右轉',
                'markerRect': {'x': 0.0, 'y': 0.0, 'width': 1.0, 'height': 1.0},
                'requestId': 'typed-selection-test',
            })

            self.assertEqual(result['summary'], 'fine')
            self.assertEqual(result['primaryAnchor']['frameId'], 'fine-001')
            self.assertEqual(result['keyframes'][0]['description'], '關鍵幀')

    def test_run_emits_truthful_stage_progress_events(self) -> None:
        frame = RenderedFrame('fine-001', 1500, 1, 'fine-001', 'fine-001.jpg', 1280, 720)
        keyframe = SelectedKeyframe(frame=frame, description='關鍵幀')
        progress_events: list[dict[str, object]] = []

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            workflow = self._build_workflow(runtime_root=runtime_root)

            workflow._probe_duration_ms = lambda source_path: 5000
            workflow._render_storyboard_frames = lambda **kwargs: [frame]
            workflow._select_coarse_interval = lambda request_id, description, frames: StoryboardSelection(
                start_frame=frame,
                end_frame=frame,
                anchor_frame=frame,
                summary='coarse',
            )
            workflow._select_fine_interval = lambda request_id, description, frames, max_keyframes: StoryboardSelection(
                start_frame=frame,
                end_frame=frame,
                anchor_frame=frame,
                summary='fine',
                keyframes=(keyframe,),
            )
            workflow._resolve_target = lambda **kwargs: {'selectedBox': None}
            workflow._render_keyframes = lambda **kwargs: [{
                'frame': frame.to_payload(),
                'description': keyframe.description,
                'overlay': None,
            }]

            token = install_runtime_progress_sink(progress_events.append)
            try:
                workflow.run({
                    'sourcePath': 'demo.mp4',
                    'description': '機車右轉',
                    'markerRect': {'x': 0.0, 'y': 0.0, 'width': 1.0, 'height': 1.0},
                    'requestId': 'progress-test',
                })
            finally:
                reset_runtime_progress_sink(token)

        self.assertEqual(
            [(event.get('stage'), event.get('detail')) for event in progress_events],
            [
                ('localize', 'Rendering coarse storyboard.'),
                ('localize', 'Selecting coarse interval with AI.'),
                ('localize', 'Rendering fine storyboard around the candidate interval.'),
                ('localize', 'Selecting anchor and keyframes with AI.'),
                ('range-analysis', 'Running plate range analysis on the resolved interval.'),
                ('render', 'Rendering evidence keyframes.'),
            ],
        )
        self.assertEqual(progress_events[0].get('progressKind'), 'tool-call')
        self.assertEqual(progress_events[0].get('toolName'), 'build-coarse-storyboard')
        self.assertEqual(progress_events[0].get('stepIndex'), 2)
        self.assertEqual(progress_events[0].get('stepCount'), 11)

    def test_build_projection_keeps_anchor_target_candidates_and_analysis_track(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workflow = self._build_workflow(runtime_root=Path(temp_dir))

            projection = workflow._build_projection(
                {
                    'targetTracks': [{
                        'id': 'analysis-track-1',
                        'className': 'motorcycle',
                        'label': 'analysis target',
                        'confidence': 0.91,
                        'frames': [{
                            'id': 'analysis-frame-1',
                            'timeMs': 6000,
                            'box': {'x': 0.2, 'y': 0.3, 'width': 0.18, 'height': 0.22},
                            'confidence': 0.91,
                            'className': 'motorcycle',
                        }],
                    }],
                    'samples': [],
                    'candidates': [],
                    'acceptedCandidateId': None,
                    'review': None,
                    'provenance': None,
                    'decision': {
                        'source': 'fused-image',
                        'stage': 'temporal-restored',
                        'supportFrameCount': 3,
                        'agreementRatio': 0.84,
                    },
                },
                {'startMs': 5800, 'endMs': 7200},
                {
                    'selectedTrackId': 'candidate-track-2',
                    'candidateTracks': [
                        {
                            'id': 'candidate-track-1',
                            'className': 'car',
                            'label': 'car 1',
                            'confidence': 0.88,
                            'frames': [{
                                'id': 'candidate-track-1-anchor',
                                'timeMs': 6000,
                                'box': {'x': 0.12, 'y': 0.2, 'width': 0.2, 'height': 0.18},
                                'confidence': 0.88,
                                'className': 'car',
                            }],
                        },
                        {
                            'id': 'candidate-track-2',
                            'className': 'motorcycle',
                            'label': 'candidate plate',
                            'confidence': 0.92,
                            'frames': [{
                                'id': 'candidate-track-2-anchor',
                                'timeMs': 6000,
                                'box': {'x': 0.42, 'y': 0.18, 'width': 0.16, 'height': 0.2},
                                'confidence': 0.92,
                                'className': 'motorcycle',
                            }],
                        },
                    ],
                },
            )

            self.assertEqual(projection['selectedTargetTrackId'], 'candidate-track-2')
            self.assertEqual(len(projection['targetTracks']), 2)
            self.assertEqual(projection['targetTracks'][1]['label'], 'candidate plate')
            self.assertEqual(projection['analysisTrack']['id'], 'candidate-track-2')
            self.assertEqual(projection['analysisTrack']['diagnostics']['canonicalizedFromTrackId'], 'analysis-track-1')
            self.assertEqual(projection['decision']['source'], 'fused-image')
            self.assertEqual(projection['decision']['stage'], 'temporal-restored')

    def test_build_projection_prefers_explicit_interval_analysis_track(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workflow = self._build_workflow(runtime_root=Path(temp_dir))

            projection = workflow._build_projection(
                {
                    'targetTracks': [{
                        'id': 'legacy-track-1',
                        'className': 'motorcycle',
                        'label': 'legacy analysis target',
                        'confidence': 0.81,
                        'frames': [{
                            'id': 'legacy-frame-1',
                            'timeMs': 6000,
                            'box': {'x': 0.2, 'y': 0.3, 'width': 0.18, 'height': 0.22},
                            'confidence': 0.81,
                            'className': 'motorcycle',
                        }],
                    }],
                    'analysisTrack': {
                        'id': 'candidate-track-2',
                        'className': 'motorcycle',
                        'label': 'explicit analysis target',
                        'confidence': 0.93,
                        'frames': [{
                            'id': 'analysis-frame-1',
                            'timeMs': 6060,
                            'box': {'x': 0.44, 'y': 0.2, 'width': 0.16, 'height': 0.2},
                            'confidence': 0.93,
                            'className': 'motorcycle',
                        }],
                        'diagnostics': {
                            'canonicalTargetId': 'candidate-track-2',
                            'trajectoryFrameCount': 11,
                        },
                    },
                    'samples': [],
                    'candidates': [],
                    'acceptedCandidateId': None,
                    'review': None,
                    'provenance': None,
                },
                {'startMs': 5800, 'endMs': 7200},
                {
                    'selectedTrackId': 'candidate-track-2',
                    'candidateTracks': [],
                },
            )

            self.assertEqual(projection['analysisTrack']['id'], 'candidate-track-2')
            self.assertEqual(projection['analysisTrack']['label'], 'explicit analysis target')
            self.assertEqual(projection['analysisTrack']['diagnostics']['trajectoryFrameCount'], 11)

    def test_resolve_target_deduplicates_overlapping_anchor_candidates(self) -> None:
        class ProviderStub:
            kind = 'stub'

            def __init__(self) -> None:
                self.metadata: dict[str, object] | None = None

            def generate_json(self, **kwargs):
                self.metadata = kwargs.get('request_metadata')
                return {
                    'selectedTrackId': 'target-1500-0',
                    'confidence': 0.66,
                    'rationale': 'pick the strongest target',
                }

        class FrameReaderStub:
            def read_frame(self, source_path: str, time_ms: int):
                del source_path, time_ms
                return np.zeros((80, 120, 3), dtype=np.uint8)

        analyze_calls: list[dict[str, object]] = []
        provider = ProviderStub()

        with tempfile.TemporaryDirectory() as temp_dir:
            workflow = self._build_workflow(
                runtime_root=Path(temp_dir),
                provider=provider,
                frame_reader=FrameReaderStub(),
                detect_targets=lambda *args, **kwargs: [
                    TrackedRegion(
                        id='target-1500-0',
                        time_ms=1500,
                        box=NormalizedRect(x=0.22, y=0.18, width=0.28, height=0.34),
                        confidence=0.95,
                        class_name='car',
                    ),
                    TrackedRegion(
                        id='target-1500-1',
                        time_ms=1500,
                        box=NormalizedRect(x=0.24, y=0.2, width=0.26, height=0.32),
                        confidence=0.9,
                        class_name='car',
                    ),
                    TrackedRegion(
                        id='target-1500-2',
                        time_ms=1500,
                        box=NormalizedRect(x=0.62, y=0.2, width=0.18, height=0.22),
                        confidence=0.86,
                        class_name='car',
                    ),
                ],
                analyze_frame=lambda payload: analyze_calls.append(payload) or {
                    'acceptedCandidateId': None,
                    'candidates': [],
                },
            )
            workflow._render_detection_reference = lambda frame, detections, output_dir: (output_dir / 'anchor.jpg', 120, 80)
            workflow._encode_chat_image = lambda image_path: 'YWJj'
            workflow._prepare_frame_image = lambda image, title, subtitle, **kwargs: (image, 120, 80)
            workflow._write_image = lambda image_path, image: None

            result = workflow._resolve_target(
                tool_calls=[],
                request_id='ai-dedupe-test',
                description='找出這台車',
                source_path='demo.mp4',
                marker_rect=None,
                target_vehicle_kind='car',
                country_hints=[],
                analysis_profile_id=None,
                enable_developer_diagnostics=False,
                anchor_frame=RenderedFrame('fine-001', 1500, 0, 'fine-001', 'fine-001.jpg', 120, 80),
                output_dir=Path(temp_dir) / 'target-resolution',
            )

            self.assertEqual(len(analyze_calls), 2)
            self.assertEqual(provider.metadata['candidateCount'], 2)
            self.assertEqual(result['selectedTrackId'], 'target-1500-0')
            self.assertEqual(result['candidateTracks'][0]['diagnostics']['targetDetection']['suppressedDuplicateDetections'], 1)

    def test_resolve_target_still_invokes_provider_when_plate_hint_matches_exactly(self) -> None:
        class ProviderStub:
            kind = 'stub'

            def __init__(self) -> None:
                self.calls: list[dict[str, object] | None] = []

            def generate_json(self, **kwargs):
                self.calls.append(kwargs.get('request_metadata'))
                return {
                    'selectedTrackId': 'target-1500-0',
                    'confidence': 0.61,
                    'rationale': 'model selection',
                }

        class FrameReaderStub:
            def read_frame(self, source_path: str, time_ms: int):
                del source_path, time_ms
                return np.zeros((80, 120, 3), dtype=np.uint8)

        provider = ProviderStub()

        with tempfile.TemporaryDirectory() as temp_dir:
            workflow = self._build_workflow(
                runtime_root=Path(temp_dir),
                provider=provider,
                frame_reader=FrameReaderStub(),
                detect_targets=lambda *args, **kwargs: [
                    TrackedRegion(
                        id='target-1500-0',
                        time_ms=1500,
                        box=NormalizedRect(x=0.2, y=0.2, width=0.3, height=0.3),
                        confidence=0.95,
                        class_name='car',
                    ),
                ],
                analyze_frame=lambda payload: {
                    'acceptedCandidateId': 'candidate-1',
                    'candidates': [
                        {'id': 'candidate-1', 'text': 'ABC1234', 'confidence': 0.97},
                    ],
                },
            )
            workflow._render_detection_reference = lambda frame, detections, output_dir: (output_dir / 'anchor.jpg', 120, 80)
            workflow._encode_chat_image = lambda image_path: 'YWJj'
            workflow._prepare_frame_image = lambda image, title, subtitle, **kwargs: (image, 120, 80)
            workflow._write_image = lambda image_path, image: None

            result = workflow._resolve_target(
                tool_calls=[],
                request_id='ai-log-target-test',
                description='請找出車牌 ABC1234 的車輛',
                source_path='demo.mp4',
                marker_rect=None,
                target_vehicle_kind='car',
                country_hints=[],
                analysis_profile_id=None,
                enable_developer_diagnostics=False,
                anchor_frame=RenderedFrame('fine-001', 1500, 0, 'fine-001', 'fine-001.jpg', 120, 80),
                output_dir=Path(temp_dir) / 'target-resolution',
            )

            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(provider.calls[0]['stage'], 'target')
            self.assertEqual(result['selectedTrackId'], 'target-1500-0')
            self.assertEqual(result['selectedCandidateId'], 'candidate-1')
            self.assertGreaterEqual(result['confidence'], 0.99)

    def test_resolve_target_allows_provider_to_override_exact_match_when_contradicted(self) -> None:
        class ProviderStub:
            kind = 'stub'

            def generate_json(self, **kwargs):
                del kwargs
                return {
                    'selectedTrackId': 'target-1500-1',
                    'selectedCandidateId': 'candidate-2',
                    'confidence': 0.72,
                    'plateHintConsistency': 'contradicted',
                    'rationale': '畫面中的車輛外觀與車牌提示不一致。',
                }

        class FrameReaderStub:
            def read_frame(self, source_path: str, time_ms: int):
                del source_path, time_ms
                return np.zeros((80, 120, 3), dtype=np.uint8)

        def analyze_frame(payload: dict[str, object]) -> dict[str, object]:
            selected_box = payload['selectedTargetBox']
            assert isinstance(selected_box, dict)
            if float(selected_box['x']) < 0.5:
                return {
                    'acceptedCandidateId': 'candidate-1',
                    'candidates': [
                        {'id': 'candidate-1', 'text': 'ABC1234', 'confidence': 0.97},
                    ],
                }
            return {
                'acceptedCandidateId': 'candidate-2',
                'candidates': [
                    {'id': 'candidate-2', 'text': 'ZZZ8888', 'confidence': 0.91},
                ],
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            workflow = self._build_workflow(
                runtime_root=Path(temp_dir),
                provider=ProviderStub(),
                frame_reader=FrameReaderStub(),
                detect_targets=lambda *args, **kwargs: [
                    TrackedRegion(
                        id='target-1500-0',
                        time_ms=1500,
                        box=NormalizedRect(x=0.18, y=0.2, width=0.22, height=0.28),
                        confidence=0.95,
                        class_name='car',
                    ),
                    TrackedRegion(
                        id='target-1500-1',
                        time_ms=1500,
                        box=NormalizedRect(x=0.58, y=0.24, width=0.24, height=0.3),
                        confidence=0.93,
                        class_name='car',
                    ),
                ],
                analyze_frame=analyze_frame,
            )
            workflow._render_detection_reference = lambda frame, detections, output_dir: (output_dir / 'anchor.jpg', 120, 80)
            workflow._encode_chat_image = lambda image_path: 'YWJj'
            workflow._prepare_frame_image = lambda image, title, subtitle, **kwargs: (image, 120, 80)
            workflow._write_image = lambda image_path, image: None

            result = workflow._resolve_target(
                tool_calls=[],
                request_id='ai-log-target-contradicted-test',
                description='請找出車牌 ABC1234 的車輛',
                source_path='demo.mp4',
                marker_rect=None,
                target_vehicle_kind='car',
                country_hints=[],
                analysis_profile_id=None,
                enable_developer_diagnostics=False,
                anchor_frame=RenderedFrame('fine-001', 1500, 0, 'fine-001', 'fine-001.jpg', 120, 80),
                output_dir=Path(temp_dir) / 'target-resolution',
            )

            self.assertEqual(result['selectedTrackId'], 'target-1500-1')
            self.assertEqual(result['selectedCandidateId'], 'candidate-2')
            self.assertEqual(result['plateHintConsistency'], 'contradicted')
            self.assertAlmostEqual(result['confidence'], 0.72)


if __name__ == '__main__':
    unittest.main()