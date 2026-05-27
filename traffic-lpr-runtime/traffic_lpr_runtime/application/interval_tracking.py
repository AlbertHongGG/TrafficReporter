from __future__ import annotations

from typing import Any, Callable

from traffic_lpr_runtime.application.pipeline_support import AnalysisOptions
from traffic_lpr_runtime.domain.models import TargetTrack, TrackedRegion
from traffic_lpr_runtime.domain.value_objects import NormalizedRect, clamp


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


class IntervalTrackingService:
    def __init__(
        self,
        frame_reader: Any,
        detect_targets: Callable[[Any, int, str, NormalizedRect | None], list[TrackedRegion]],
        tracker: Any,
    ) -> None:
        self._frame_reader = frame_reader
        self._detect_targets = detect_targets
        self._tracker = tracker

    def match_anchor_target(
        self,
        detections: list[TrackedRegion],
        selected_target_box: NormalizedRect | None,
    ) -> TrackedRegion | None:
        if not detections:
            return None
        if not selected_target_box:
            return detections[0]

        ranked = sorted(
            detections,
            key=lambda candidate: (
                candidate.box.intersection_over_union(selected_target_box),
                -candidate.box.center_distance(selected_target_box),
                candidate.confidence,
            ),
            reverse=True,
        )
        return ranked[0]

    def track_target_across_interval(
        self,
        source_path: str,
        interval: dict[str, int],
        anchor_time_ms: int,
        vehicle_kind: str,
        selected_target_box: NormalizedRect | None,
        sample_every_ms: int | None,
        max_samples: int | None,
        options: AnalysisOptions,
    ) -> tuple[list[TrackedRegion], dict[str, Any]]:
        start_ms = int(interval['startMs'])
        end_ms = int(interval['endMs'])
        evidence_sample_times = sorted(set(self.sample_times(interval, sample_every_ms, max_samples)))
        evidence_sample_time_set = set(evidence_sample_times)
        sample_step_ms = self.resolve_sample_step_ms(interval, sample_every_ms, max_samples)
        trajectory_step_ms = self.resolve_tracking_step_ms(interval, sample_step_ms)
        tracking_times = sorted(set(self.trajectory_times(interval, trajectory_step_ms)) | evidence_sample_time_set)
        tracking_time_set = set(tracking_times)

        if start_ms <= anchor_time_ms <= end_ms and anchor_time_ms not in tracking_time_set:
            tracking_times.append(anchor_time_ms)
            tracking_times.sort()
            tracking_time_set.add(anchor_time_ms)

        if options.tracker_mode != 'legacy':
            tracked_frames, diagnostics = self._tracker.track(
                source_path,
                interval,
                anchor_time_ms,
                vehicle_kind,
                selected_target_box,
                tracking_times,
                options,
            )
            return self._finalize_tracked_frames(
                tracked_frames,
                diagnostics,
                tracking_times,
                evidence_sample_times,
                trajectory_step_ms,
                anchor_time_ms,
            )

        anchor_frame = self._frame_reader.read_frame(source_path, anchor_time_ms)
        anchor_detections = self._detect_targets(anchor_frame, anchor_time_ms, vehicle_kind, None)
        anchor_region = self.match_anchor_target(anchor_detections, selected_target_box)
        seed_box = anchor_region.box if anchor_region else selected_target_box

        bridge_times: set[int] = set()
        if anchor_time_ms < start_ms:
            bridge_times.update(range(anchor_time_ms + trajectory_step_ms, start_ms, trajectory_step_ms))
        elif anchor_time_ms > end_ms:
            bridge_times.update(range(anchor_time_ms - trajectory_step_ms, end_ms, -trajectory_step_ms))

        traversal_times = tracking_time_set | bridge_times
        backward_times = sorted((time_ms for time_ms in traversal_times if time_ms < anchor_time_ms), reverse=True)
        forward_times = sorted(time_ms for time_ms in traversal_times if time_ms > anchor_time_ms)

        tracked_before: list[TrackedRegion] = []
        previous_box = seed_box
        for time_ms in backward_times:
            frame = self._frame_reader.read_frame(source_path, time_ms)
            detections = self._detect_targets(frame, time_ms, vehicle_kind, None)
            chosen = self._match_tracked_target(detections, previous_box)
            if chosen is None:
                continue

            previous_box = chosen.box
            if time_ms in tracking_time_set:
                tracked_before.append(chosen)

        tracked_after: list[TrackedRegion] = []
        previous_box = seed_box
        for time_ms in forward_times:
            frame = self._frame_reader.read_frame(source_path, time_ms)
            detections = self._detect_targets(frame, time_ms, vehicle_kind, None)
            chosen = self._match_tracked_target(detections, previous_box)
            if chosen is None:
                continue

            previous_box = chosen.box
            if time_ms in tracking_time_set:
                tracked_after.append(chosen)

        tracked_frames: list[TrackedRegion] = list(reversed(tracked_before))
        if anchor_time_ms in tracking_time_set and anchor_region is not None:
            tracked_frames.append(anchor_region)
        tracked_frames.extend(tracked_after)
        diagnostics = {
            'trackerMode': 'legacy',
            'matchedFrames': len(tracked_frames),
            'missedFrames': max(0, len(tracking_times) - len(tracked_frames)),
            'averageMatchScore': 0.0,
            'anchorDetected': anchor_region is not None,
            'anchorDetectionId': anchor_region.id if anchor_region is not None else None,
        }
        return self._finalize_tracked_frames(
            tracked_frames,
            diagnostics,
            tracking_times,
            evidence_sample_times,
            trajectory_step_ms,
            anchor_time_ms,
        )

    def calibrate_interval_target_boxes(
        self,
        tracked_frames: list[TrackedRegion],
        anchor_time_ms: int,
        selected_target_box: NormalizedRect | None,
    ) -> dict[int, NormalizedRect]:
        if selected_target_box is None or not tracked_frames:
            return {}

        anchor_frame = next((frame for frame in tracked_frames if frame.time_ms == anchor_time_ms), None)
        if anchor_frame is None:
            anchor_frame = min(tracked_frames, key=lambda frame: abs(frame.time_ms - anchor_time_ms))

        anchor_box = anchor_frame.box if anchor_frame is not None else None
        if anchor_box is None or anchor_box.width <= 0.0 or anchor_box.height <= 0.0:
            return {}
        if anchor_box.intersection_over_union(selected_target_box) < 0.1 and anchor_box.center_distance(selected_target_box) > 0.12:
            return {}

        anchor_width = max(anchor_box.width, 1e-6)
        anchor_height = max(anchor_box.height, 1e-6)
        left_ratio = (anchor_box.x - selected_target_box.x) / anchor_width
        top_ratio = (anchor_box.y - selected_target_box.y) / anchor_height
        right_ratio = ((selected_target_box.x + selected_target_box.width) - (anchor_box.x + anchor_box.width)) / anchor_width
        bottom_ratio = ((selected_target_box.y + selected_target_box.height) - (anchor_box.y + anchor_box.height)) / anchor_height

        calibrated: dict[int, NormalizedRect] = {}
        for tracked_frame in tracked_frames:
            raw_box = tracked_frame.box
            x1 = clamp(raw_box.x - (left_ratio * raw_box.width), 0.0, 1.0)
            y1 = clamp(raw_box.y - (top_ratio * raw_box.height), 0.0, 1.0)
            x2 = clamp(raw_box.x + raw_box.width + (right_ratio * raw_box.width), min(1.0, x1 + 0.01), 1.0)
            y2 = clamp(raw_box.y + raw_box.height + (bottom_ratio * raw_box.height), min(1.0, y1 + 0.01), 1.0)
            calibrated[tracked_frame.time_ms] = NormalizedRect(
                x=x1,
                y=y1,
                width=x2 - x1,
                height=y2 - y1,
            )

        return calibrated

    def build_track_payload(self, tracked_frames: list[TrackedRegion], diagnostics: dict[str, Any]) -> list[TargetTrack]:
        if not tracked_frames:
            return []
        track_id = (
            _optional_string(diagnostics.get('canonicalTargetId'))
            or _optional_string(diagnostics.get('anchorDetectionId'))
            or tracked_frames[0].id
            or 'tracked-target-0'
        )
        for tracked_frame in tracked_frames:
            tracked_frame.diagnostics = {
                **(tracked_frame.diagnostics or {}),
                'canonicalTargetId': track_id,
            }
        average_confidence = sum(frame.confidence for frame in tracked_frames) / len(tracked_frames)
        return [
            TargetTrack(
                id=track_id,
                class_name=tracked_frames[0].class_name,
                label=f'{tracked_frames[0].class_name} {tracked_frames[0].time_ms}ms',
                confidence=average_confidence,
                frames=tracked_frames,
                diagnostics={
                    **diagnostics,
                    'canonicalTargetId': track_id,
                },
            )
        ]

    def resolve_sample_step_ms(
        self,
        interval: dict[str, int],
        requested_every_ms: int | None,
        requested_max_samples: int | None,
    ) -> int:
        start_ms = int(interval['startMs'])
        end_ms = int(interval['endMs'])
        duration_ms = max(0, end_ms - start_ms)
        max_samples = max(4, min(int(requested_max_samples or 18), 48))

        if duration_ms == 0:
            return max(120, int(requested_every_ms or 120))

        return requested_every_ms or max(120, int(duration_ms / max_samples))

    def resolve_tracking_step_ms(
        self,
        interval: dict[str, int],
        evidence_step_ms: int,
    ) -> int:
        start_ms = int(interval['startMs'])
        end_ms = int(interval['endMs'])
        duration_ms = max(0, end_ms - start_ms)

        if duration_ms == 0:
            return max(50, min(evidence_step_ms, 100))

        base_step_ms = max(1, int(round(evidence_step_ms / 2)))
        rounded_step_ms = int(round(base_step_ms / 10.0) * 10) if base_step_ms >= 10 else base_step_ms
        return max(50, min(100, rounded_step_ms))

    def trajectory_times(
        self,
        interval: dict[str, int],
        trajectory_step_ms: int,
    ) -> list[int]:
        start_ms = int(interval['startMs'])
        end_ms = int(interval['endMs'])
        if start_ms >= end_ms:
            return [start_ms]

        times = list(range(start_ms, end_ms + 1, max(1, trajectory_step_ms)))
        if times[-1] != end_ms:
            times.append(end_ms)
        return times

    def sample_times(
        self,
        interval: dict[str, int],
        requested_every_ms: int | None,
        requested_max_samples: int | None,
    ) -> list[int]:
        start_ms = int(interval['startMs'])
        end_ms = int(interval['endMs'])
        duration_ms = max(0, end_ms - start_ms)
        max_samples = max(4, min(int(requested_max_samples or 18), 48))

        if duration_ms == 0:
            return [start_ms]

        sample_every_ms = self.resolve_sample_step_ms(interval, requested_every_ms, requested_max_samples)
        times = list(range(start_ms, end_ms + 1, sample_every_ms))
        if times[-1] != end_ms:
            times.append(end_ms)
        return times[:max_samples]

    def _finalize_tracked_frames(
        self,
        tracked_frames: list[TrackedRegion],
        diagnostics: dict[str, Any],
        tracking_times: list[int],
        evidence_sample_times: list[int],
        trajectory_step_ms: int,
        anchor_time_ms: int,
    ) -> tuple[list[TrackedRegion], dict[str, Any]]:
        evidence_sample_time_set = set(evidence_sample_times)
        for index, tracked_frame in enumerate(tracked_frames):
            tracked_frame.diagnostics = {
                **(tracked_frame.diagnostics or {}),
                'trajectoryIndex': index,
                'trajectoryRole': (
                    'anchor'
                    if tracked_frame.time_ms == anchor_time_ms
                    else ('evidence-sample' if tracked_frame.time_ms in evidence_sample_time_set else 'trajectory')
                ),
                'isAnchorFrame': tracked_frame.time_ms == anchor_time_ms,
                'isEvidenceSample': tracked_frame.time_ms in evidence_sample_time_set,
                'visibilityState': 'visible',
            }

        return tracked_frames, {
            **diagnostics,
            'matchedFrames': len(tracked_frames),
            'requestedTrackingFrameCount': len(tracking_times),
            'requestedEvidenceSampleCount': len(evidence_sample_times),
            'trajectoryFrameCount': len(tracked_frames),
            'trajectoryStepMs': trajectory_step_ms,
            'evidenceSampleTimes': evidence_sample_times,
            'anchorTimeMs': anchor_time_ms,
        }

    def _match_tracked_target(
        self,
        detections: list[TrackedRegion],
        previous_box: NormalizedRect | None,
    ) -> TrackedRegion | None:
        if not detections:
            return None
        if previous_box is None:
            return detections[0]

        ranked = sorted(
            detections,
            key=lambda candidate: (
                candidate.box.intersection_over_union(previous_box),
                -candidate.box.center_distance(previous_box),
                candidate.confidence,
            ),
            reverse=True,
        )
        return ranked[0]
