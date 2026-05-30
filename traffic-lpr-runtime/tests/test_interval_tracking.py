from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.application.interval_tracking import IntervalTrackingService
from traffic_lpr_runtime.application.pipeline_support import AnalysisOptions
from traffic_lpr_runtime.domain.models import TrackedRegion
from traffic_lpr_runtime.domain.value_objects import NormalizedRect


class IntervalTrackingTests(unittest.TestCase):
    def test_long_intervals_trim_evidence_budget_and_anchor_burst_count(self) -> None:
        selected_target_box = NormalizedRect(x=0.32, y=0.2, width=0.18, height=0.24)

        class TrackerStub:
            @staticmethod
            def track(source_path, interval, anchor_time_ms, vehicle_kind, selected_target_box, tracking_times, options):
                del source_path, interval, anchor_time_ms, vehicle_kind, selected_target_box, options
                tracked_frames = [
                    TrackedRegion(
                        id=f'track-{time_ms}',
                        time_ms=time_ms,
                        box=NormalizedRect(x=0.32, y=0.2, width=0.18, height=0.24),
                        confidence=0.93,
                        class_name='motorcycle',
                    )
                    for time_ms in tracking_times
                ]
                return tracked_frames, {'trackerMode': 'botsort'}

        service = IntervalTrackingService(
            frame_reader=object(),
            detect_targets=lambda *args, **kwargs: [],
            tracker=TrackerStub(),
        )

        tracked_frames, diagnostics = service.track_target_across_interval(
            'demo.mp4',
            {'startMs': 0, 'endMs': 15_600},
            7_800,
            'motorcycle',
            selected_target_box,
            None,
            14,
            AnalysisOptions(max_evidence_sample_count=14, anchor_burst_count=5),
        )

        self.assertEqual(diagnostics['requestedEvidenceSampleCount'], 10)
        self.assertGreater(diagnostics['rawRequestedEvidenceSampleCount'], diagnostics['requestedEvidenceSampleCount'])
        self.assertEqual(diagnostics['effectiveAnchorBurstCount'], 3)
        self.assertTrue(diagnostics['sparseEvidenceSamplingApplied'])
        self.assertEqual(len(tracked_frames), diagnostics['requestedTrackingFrameCount'])


if __name__ == '__main__':
    unittest.main()