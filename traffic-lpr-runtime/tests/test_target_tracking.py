from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.application.interval_tracking import IntervalTrackingService
from traffic_lpr_runtime.application.pipeline_support import AnalysisOptions, TargetCentricTracker
from traffic_lpr_runtime.domain.models import TrackedRegion
from traffic_lpr_runtime.domain.value_objects import NormalizedRect


def make_region(
    region_id: str,
    time_ms: int,
    x: float,
    y: float,
    width: float,
    height: float,
    confidence: float = 0.9,
    class_name: str = 'motorcycle',
) -> TrackedRegion:
    return TrackedRegion(
        id=region_id,
        time_ms=time_ms,
        box=NormalizedRect(x=x, y=y, width=width, height=height),
        confidence=confidence,
        class_name=class_name,
        diagnostics={},
    )


def clone_region(region: TrackedRegion) -> TrackedRegion:
    return TrackedRegion(
        id=region.id,
        time_ms=region.time_ms,
        box=NormalizedRect(
            x=region.box.x,
            y=region.box.y,
            width=region.box.width,
            height=region.box.height,
        ),
        confidence=region.confidence,
        class_name=region.class_name,
        diagnostics=dict(region.diagnostics or {}),
    )


class FrameReaderStub:
    def read_frame(self, source_path: str, time_ms: int) -> object:
        del source_path, time_ms
        return object()


class DetectorStub:
    def __init__(self, detections_by_time: dict[int, list[TrackedRegion]]) -> None:
        self._detections_by_time = detections_by_time

    def detect_targets(self, frame, time_ms: int, vehicle_kind: str, marker_rect) -> list[TrackedRegion]:
        del frame, vehicle_kind, marker_rect
        return [clone_region(region) for region in self._detections_by_time.get(time_ms, [])]


class ScriptedTargetCentricTracker(TargetCentricTracker):
    def __init__(
        self,
        detections_by_time: dict[int, list[TrackedRegion]],
        tracked_by_time: dict[int, list[TrackedRegion]],
        motion_hints_by_time: dict[int, dict[str, float]] | None = None,
    ) -> None:
        super().__init__(dependencies=object(), frame_reader=FrameReaderStub(), target_detector=DetectorStub(detections_by_time))
        self._tracked_by_time = tracked_by_time
        self._motion_hints_by_time = motion_hints_by_time or {}

    def _build_ultralytics_tracker(self, options: AnalysisOptions, frame_rate: int) -> object:
        del options, frame_rate
        return object()

    def _update_ultralytics_tracker(self, tracker: object, frame, detections: list[TrackedRegion], time_ms: int) -> list[TrackedRegion]:
        del tracker, frame, detections
        return [clone_region(region) for region in self._tracked_by_time.get(time_ms, [])]

    def _estimate_tracker_scene_motion(self, previous_frame, frame, previous_time_ms: int, time_ms: int) -> dict[str, float]:
        del previous_frame, frame, previous_time_ms
        return dict(self._motion_hints_by_time.get(time_ms, {}))


class TargetTrackingTests(unittest.TestCase):
    def test_anchor_uses_selected_detection_when_tracker_anchor_points_to_other_vehicle(self) -> None:
        selected_target_box = NormalizedRect(x=0.12, y=0.22, width=0.12, height=0.26)
        detections_by_time = {
            2000: [
                make_region('target-2000-0', 2000, 0.12, 0.22, 0.12, 0.26),
                make_region('target-2000-1', 2000, 0.52, 0.18, 0.11, 0.24),
            ],
            3000: [
                make_region('target-3000-0', 3000, 0.14, 0.23, 0.12, 0.26),
                make_region('target-3000-1', 3000, 0.50, 0.18, 0.11, 0.24),
            ],
        }
        tracked_by_time = {
            2000: [
                make_region('track-88', 2000, 0.52, 0.18, 0.11, 0.24),
            ],
            3000: [
                make_region('track-9', 3000, 0.14, 0.23, 0.12, 0.26),
                make_region('track-88', 3000, 0.50, 0.18, 0.11, 0.24),
            ],
        }
        tracker = ScriptedTargetCentricTracker(detections_by_time, tracked_by_time)

        tracked_frames, diagnostics = tracker.track(
            source_path='demo.mp4',
            interval={'startMs': 2000, 'endMs': 3000},
            anchor_time_ms=2000,
            vehicle_kind='motorcycle',
            selected_target_box=selected_target_box,
            sample_times=[2000, 3000],
            options=AnalysisOptions(tracker_mode='botsort'),
        )

        self.assertEqual([frame.id for frame in tracked_frames], ['target-2000-0', 'track-9'])
        self.assertIsNone(diagnostics['anchorTrackId'])
        self.assertLess(tracked_frames[0].box.x, 0.2)
        self.assertLess(tracked_frames[1].box.x, 0.2)

    def test_ultralytics_tracking_reassociates_when_tracker_id_drifts(self) -> None:
        selected_target_box = NormalizedRect(x=0.12, y=0.22, width=0.12, height=0.26)
        detections_by_time = {
            1000: [
                make_region('target-1000-0', 1000, 0.10, 0.21, 0.13, 0.27),
                make_region('target-1000-1', 1000, 0.55, 0.20, 0.18, 0.24, class_name='car'),
            ],
            2000: [
                make_region('target-2000-0', 2000, 0.12, 0.22, 0.12, 0.26),
                make_region('target-2000-1', 2000, 0.53, 0.20, 0.18, 0.24, class_name='car'),
            ],
            3000: [
                make_region('target-3000-0', 3000, 0.14, 0.23, 0.12, 0.26),
                make_region('target-3000-1', 3000, 0.48, 0.20, 0.18, 0.24, class_name='car'),
            ],
        }
        tracked_by_time = {
            1000: [
                make_region('track-77', 1000, 0.55, 0.20, 0.18, 0.24, class_name='car'),
            ],
            2000: [
                make_region('track-1', 2000, 0.12, 0.22, 0.12, 0.26),
                make_region('track-77', 2000, 0.53, 0.20, 0.18, 0.24, class_name='car'),
            ],
            3000: [
                make_region('track-1', 3000, 0.48, 0.20, 0.18, 0.24, class_name='car'),
                make_region('track-9', 3000, 0.14, 0.23, 0.12, 0.26),
            ],
        }
        tracker = ScriptedTargetCentricTracker(detections_by_time, tracked_by_time)

        tracked_frames, diagnostics = tracker.track(
            source_path='demo.mp4',
            interval={'startMs': 1000, 'endMs': 3000},
            anchor_time_ms=2000,
            vehicle_kind='motorcycle',
            selected_target_box=selected_target_box,
            sample_times=[1000, 2000, 3000],
            options=AnalysisOptions(tracker_mode='botsort'),
        )

        self.assertEqual([frame.time_ms for frame in tracked_frames], [1000, 2000, 3000])
        self.assertEqual(tracked_frames[0].id, 'target-1000-0')
        self.assertEqual(tracked_frames[1].id, 'track-1')
        self.assertEqual(tracked_frames[2].id, 'track-9')
        self.assertLess(tracked_frames[2].box.x, 0.2)
        self.assertEqual(diagnostics['anchorTrackId'], 'track-1')
        self.assertEqual(diagnostics['detectionFallbackFrames'], 1)
        self.assertEqual(diagnostics['reassociatedFrames'], 1)

    def test_ultralytics_tracking_rejects_same_class_lateral_takeover(self) -> None:
        selected_target_box = NormalizedRect(x=0.18, y=0.29, width=0.14, height=0.26)
        detections_by_time = {
            6210: [
                make_region('target-6210-0', 6210, 0.18, 0.29, 0.14, 0.26, confidence=0.86),
                make_region('target-6210-1', 6210, 0.39, 0.28, 0.16, 0.27, confidence=0.93),
            ],
            7030: [
                make_region('target-7030-0', 7030, 0.24, 0.31, 0.09, 0.21, confidence=0.48),
                make_region('target-7030-1', 7030, 0.39, 0.29, 0.17, 0.27, confidence=0.95),
            ],
        }
        tracked_by_time = {
            6210: [
                make_region('track-1', 6210, 0.18, 0.29, 0.14, 0.26, confidence=0.86),
                make_region('track-7', 6210, 0.39, 0.28, 0.16, 0.27, confidence=0.93),
            ],
            7030: [
                make_region('track-1', 7030, 0.39, 0.29, 0.17, 0.27, confidence=0.95),
            ],
        }
        tracker = ScriptedTargetCentricTracker(detections_by_time, tracked_by_time)

        tracked_frames, diagnostics = tracker.track(
            source_path='demo.mp4',
            interval={'startMs': 6210, 'endMs': 7030},
            anchor_time_ms=6210,
            vehicle_kind='motorcycle',
            selected_target_box=selected_target_box,
            sample_times=[6210, 7030],
            options=AnalysisOptions(tracker_mode='botsort'),
        )

        self.assertEqual([frame.id for frame in tracked_frames], ['track-1', 'target-7030-0'])
        self.assertLess(tracked_frames[1].box.x, 0.3)
        self.assertEqual(tracked_frames[1].diagnostics['trackingSource'], 'detection-fallback')

    def test_ultralytics_tracking_keeps_dashcam_target_alive_through_camera_motion(self) -> None:
        selected_target_box = NormalizedRect(x=0.18, y=0.29, width=0.14, height=0.26)
        detections_by_time = {
            2000: [
                make_region('target-2000-0', 2000, 0.18, 0.29, 0.14, 0.26, confidence=0.88, class_name='car'),
                make_region('target-2000-1', 2000, 0.54, 0.28, 0.15, 0.27, confidence=0.93, class_name='car'),
            ],
            3000: [
                make_region('target-3000-0', 3000, 0.27, 0.30, 0.14, 0.26, confidence=0.62, class_name='car'),
                make_region('target-3000-1', 3000, 0.54, 0.28, 0.15, 0.27, confidence=0.95, class_name='car'),
            ],
            4000: [
                make_region('target-4000-0', 4000, 0.31, 0.31, 0.14, 0.26, confidence=0.78, class_name='car'),
                make_region('target-4000-1', 4000, 0.56, 0.28, 0.15, 0.27, confidence=0.91, class_name='car'),
            ],
        }
        tracked_by_time = {
            2000: [
                make_region('track-1', 2000, 0.18, 0.29, 0.14, 0.26, confidence=0.88, class_name='car'),
                make_region('track-7', 2000, 0.54, 0.28, 0.15, 0.27, confidence=0.93, class_name='car'),
            ],
            3000: [
                make_region('track-1', 3000, 0.40, 0.29, 0.15, 0.27, confidence=0.93, class_name='car'),
            ],
            4000: [
                make_region('track-8', 4000, 0.31, 0.31, 0.14, 0.26, confidence=0.81, class_name='car'),
                make_region('track-1', 4000, 0.49, 0.29, 0.15, 0.27, confidence=0.91, class_name='car'),
            ],
        }
        motion_hints_by_time = {
            3000: {'dx': 0.085, 'dy': 0.01, 'magnitude': 0.0856, 'score': 0.72},
            4000: {'dx': 0.04, 'dy': 0.01, 'magnitude': 0.0412, 'score': 0.64},
        }
        tracker = ScriptedTargetCentricTracker(detections_by_time, tracked_by_time, motion_hints_by_time)

        tracked_frames, diagnostics = tracker.track(
            source_path='dashcam.mp4',
            interval={'startMs': 2000, 'endMs': 4000},
            anchor_time_ms=2000,
            vehicle_kind='car',
            selected_target_box=selected_target_box,
            sample_times=[2000, 3000, 4000],
            options=AnalysisOptions(tracker_mode='botsort'),
        )

        self.assertEqual([frame.id for frame in tracked_frames], ['track-1', 'target-3000-0', 'track-8'])
        self.assertFalse(diagnostics['terminatedEarly'])
        self.assertEqual(diagnostics['detectionFallbackFrames'], 1)
        self.assertGreaterEqual(diagnostics.get('uncertainFrames', 0), 1)
        self.assertEqual(tracked_frames[1].diagnostics['trackingSource'], 'detection-fallback')
        self.assertEqual(tracked_frames[1].diagnostics.get('trackingState'), 'uncertain')
        self.assertEqual(tracked_frames[2].diagnostics.get('trackingState'), 'confirmed')

    def test_ultralytics_tracking_extends_uncertain_grace_for_strong_dashcam_fallbacks(self) -> None:
        selected_target_box = NormalizedRect(x=0.18, y=0.29, width=0.14, height=0.26)
        detections_by_time = {
            2000: [
                make_region('target-2000-0', 2000, 0.18, 0.29, 0.14, 0.26, confidence=0.88, class_name='car'),
            ],
            3000: [
                make_region('target-3000-0', 3000, 0.22, 0.29, 0.14, 0.26, confidence=0.82, class_name='car'),
            ],
            4000: [
                make_region('target-4000-0', 4000, 0.26, 0.30, 0.14, 0.26, confidence=0.8, class_name='car'),
            ],
            5000: [
                make_region('target-5000-0', 5000, 0.30, 0.30, 0.14, 0.26, confidence=0.79, class_name='car'),
            ],
            6000: [
                make_region('target-6000-0', 6000, 0.33, 0.31, 0.14, 0.26, confidence=0.81, class_name='car'),
            ],
        }
        tracked_by_time = {
            2000: [
                make_region('track-1', 2000, 0.18, 0.29, 0.14, 0.26, confidence=0.88, class_name='car'),
            ],
            6000: [
                make_region('track-1', 6000, 0.33, 0.31, 0.14, 0.26, confidence=0.83, class_name='car'),
            ],
        }
        tracker = ScriptedTargetCentricTracker(detections_by_time, tracked_by_time)

        tracked_frames, diagnostics = tracker.track(
            source_path='dashcam.mp4',
            interval={'startMs': 2000, 'endMs': 6000},
            anchor_time_ms=2000,
            vehicle_kind='car',
            selected_target_box=selected_target_box,
            sample_times=[2000, 3000, 4000, 5000, 6000],
            options=AnalysisOptions(tracker_mode='botsort'),
        )

        self.assertEqual([frame.id for frame in tracked_frames], ['track-1', 'target-3000-0', 'target-4000-0', 'target-5000-0', 'track-1'])
        self.assertFalse(diagnostics['terminatedEarly'])
        self.assertEqual(diagnostics['uncertainFrames'], 3)
        self.assertEqual(diagnostics['detectionFallbackFrames'], 3)
        self.assertEqual(diagnostics['reassociatedFrames'], 0)

    def test_ultralytics_tracking_soft_skips_weak_tracker_switch(self) -> None:
        selected_target_box = NormalizedRect(x=0.18, y=0.29, width=0.14, height=0.26)
        detections_by_time = {
            2000: [
                make_region('target-2000-0', 2000, 0.18, 0.29, 0.14, 0.26, confidence=0.9, class_name='car'),
            ],
            3000: [
                make_region('target-3000-0', 3000, 0.20, 0.29, 0.14, 0.26, confidence=0.9, class_name='car'),
            ],
        }
        tracked_by_time = {
            2000: [
                make_region('track-1', 2000, 0.18, 0.29, 0.14, 0.26, confidence=0.9, class_name='car'),
            ],
            3000: [
                make_region('track-1', 3000, 0.20, 0.29, 0.14, 0.26, confidence=0.9, class_name='car'),
            ],
            4000: [
                make_region('track-9', 4000, 0.40, 0.29, 0.14, 0.26, confidence=0.95, class_name='car'),
            ],
        }
        tracker = ScriptedTargetCentricTracker(detections_by_time, tracked_by_time)

        tracked_frames, diagnostics = tracker.track(
            source_path='dashcam.mp4',
            interval={'startMs': 2000, 'endMs': 4000},
            anchor_time_ms=2000,
            vehicle_kind='car',
            selected_target_box=selected_target_box,
            sample_times=[2000, 3000, 4000],
            options=AnalysisOptions(tracker_mode='botsort'),
        )

        self.assertEqual([frame.id for frame in tracked_frames], ['track-1', 'track-1'])
        self.assertFalse(diagnostics['terminatedEarly'])
        self.assertEqual(diagnostics['missedFrames'], 1)
        self.assertEqual(diagnostics['identityBreaks'], 0)

    def test_calibration_skips_when_anchor_box_does_not_match_selected_target(self) -> None:
        service = IntervalTrackingService(
            frame_reader=FrameReaderStub(),
            detect_targets=lambda frame, time_ms, vehicle_kind, marker_rect: [],
            tracker=None,
        )
        tracked_frames = [
            make_region('track-1', 2000, 0.56, 0.18, 0.18, 0.24, class_name='car'),
            make_region('track-1', 2600, 0.58, 0.18, 0.18, 0.24, class_name='car'),
        ]
        selected_target_box = NormalizedRect(x=0.12, y=0.22, width=0.12, height=0.26)

        calibrated = service.calibrate_interval_target_boxes(tracked_frames, 2000, selected_target_box)

        self.assertEqual(calibrated, {})


if __name__ == '__main__':
    unittest.main()