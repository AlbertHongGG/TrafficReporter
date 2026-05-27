from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.application.workflows import FrameAnalysisWorkflow
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


class FrameWorkflowTests(unittest.TestCase):
    def test_frame_analysis_uses_interactive_fast_path_options(self) -> None:
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
        observed_options = {}

        def analyze_plate_candidates(frame, time_ms, marker_rect, target_box, country_hints, options, artifact_root):
            del frame, time_ms, marker_rect, target_box, country_hints, artifact_root
            observed_options.update(options.to_payload())
            sample = FrameSample(
                id='sample-11000',
                time_ms=11000,
                target_box=None,
                plate_box=None,
                quality=make_quality(),
                candidates=[candidate],
                image_path=None,
                diagnostics={},
            )
            return [candidate], sample, None

        workflow = FrameAnalysisWorkflow(
            ensure_ready=lambda: None,
            status=lambda: {'available': True, 'detail': 'ok'},
            runtime_root=lambda: Path('runtime-root'),
            frame_reader=type('FrameReaderStub', (), {'read_frame': staticmethod(lambda source_path, time_ms: object())})(),
            detect_targets=lambda *args, **kwargs: [],
            match_anchor_target=lambda detections, selected_target_box: None,
            analyze_plate_candidates=analyze_plate_candidates,
            apply_reliability_selection=lambda candidates, samples, country_hints, options, interval_mode: (
                candidates,
                candidate.id,
                {'suggestedCandidateId': candidate.id, 'acceptedCandidateId': candidate.id, 'reviewRequired': False, 'reasons': []},
            ),
        )

        result = workflow.run({
            'sourcePath': 'demo.mp4',
            'timeMs': 11000,
            'markerRect': None,
            'selectedTargetBox': NormalizedRect(x=0.1, y=0.2, width=0.2, height=0.2).to_payload(),
            'targetVehicleKind': 'motorcycle',
            'countryHints': ['tw'],
        })

        self.assertEqual(result['jobStatus'], 'completed')
        self.assertEqual(observed_options['restorationMode'], 'classical')
        self.assertFalse(observed_options['enableRecognizerComparison'])


if __name__ == '__main__':
    unittest.main()