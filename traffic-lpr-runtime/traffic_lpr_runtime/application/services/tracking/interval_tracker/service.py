from __future__ import annotations

from typing import Any, Callable

from traffic_lpr_runtime.domain.analysis_options import AnalysisOptions
from traffic_lpr_runtime.domain.models import TrackedRegion
from traffic_lpr_runtime.domain.value_objects import NormalizedRect

from .anchor import IntervalAnchorMixin
from .evidence import IntervalEvidenceMixin
from .sampling import (
    IntervalSamplingMixin,
    _resolve_anchor_burst_count,
    _resolve_evidence_sample_budget,
    _sparsify_evidence_sample_times,
)


class IntervalTrackingService(IntervalAnchorMixin, IntervalSamplingMixin, IntervalEvidenceMixin):
    def __init__(
        self,
        frame_reader: Any,
        detect_targets: Callable[[Any, int, str, NormalizedRect | None], list[TrackedRegion]],
        tracker: Any,
    ) -> None:
        self._frame_reader = frame_reader
        self._detect_targets = detect_targets
        self._tracker = tracker

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
        preserve_dense_evidence_samples: bool = False,
    ) -> tuple[list[TrackedRegion], dict[str, Any]]:
        start_ms = int(interval['startMs'])
        end_ms = int(interval['endMs'])
        duration_ms = max(0, end_ms - start_ms)
        raw_evidence_sample_times = sorted(set(self.sample_times(interval, sample_every_ms, max_samples)))
        sample_step_ms = self.resolve_sample_step_ms(interval, sample_every_ms, max_samples)
        evidence_budget = _resolve_evidence_sample_budget(
            raw_evidence_sample_times,
            duration_ms,
            preserve_dense_evidence_samples or options.temporal_evidence_mode == 'scheduled',
            options.max_evidence_sample_count,
        )
        resolved_anchor_burst_count = _resolve_anchor_burst_count(
            duration_ms,
            evidence_budget,
            options.anchor_burst_count,
        )
        evidence_sample_times = raw_evidence_sample_times
        if evidence_budget < len(raw_evidence_sample_times):
            evidence_sample_times = _sparsify_evidence_sample_times(
                interval,
                anchor_time_ms,
                sample_step_ms,
                evidence_budget,
                resolved_anchor_burst_count,
            )
        evidence_sample_time_set = set(evidence_sample_times)
        trajectory_step_ms = sample_step_ms if preserve_dense_evidence_samples else self.resolve_tracking_step_ms(interval, sample_step_ms)
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
                raw_evidence_sample_times,
                resolved_anchor_burst_count,
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
            raw_evidence_sample_times,
            resolved_anchor_burst_count,
        )
