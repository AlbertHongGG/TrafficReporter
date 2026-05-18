from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.application.ai_evidence_workflow import AiEvidenceWorkflow, RenderedFrame, SelectedKeyframe, StoryboardSelection, _normalize_keyframes


class AiEvidenceWorkflowTests(unittest.TestCase):
    def test_normalize_keyframes_returns_selected_keyframe_objects(self) -> None:
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
            desired_count=2,
        )

        self.assertEqual(len(result), 2)
        self.assertTrue(all(isinstance(item, SelectedKeyframe) for item in result))
        self.assertEqual(result[0].frame.frame_id, 'fine-001')
        self.assertEqual(result[0].description, '關鍵幀')
        self.assertEqual(result[1].frame.frame_id, 'fine-002')
        self.assertEqual(result[1].description, 'fine-002')

    def test_run_accepts_typed_storyboard_selections(self) -> None:
        frame = RenderedFrame('fine-001', 1500, 1, 'fine-001', 'fine-001.jpg', 1280, 720)
        keyframe = SelectedKeyframe(frame=frame, description='關鍵幀')

        class ProviderStub:
            kind = 'stub'

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            workflow = AiEvidenceWorkflow(
                ensure_ready=lambda: None,
                status=lambda: {'available': True, 'detail': 'ok'},
                runtime_root=lambda: runtime_root,
                dependencies=object(),
                frame_reader=object(),
                detect_targets=lambda *args, **kwargs: [],
                analyze_frame=lambda payload: payload,
                analyze_interval=lambda payload: {
                    'targetTracks': [],
                    'samples': [],
                    'candidates': [],
                    'acceptedCandidateId': None,
                    'review': None,
                    'provenance': None,
                },
                provider=ProviderStub(),
            )

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


if __name__ == '__main__':
    unittest.main()