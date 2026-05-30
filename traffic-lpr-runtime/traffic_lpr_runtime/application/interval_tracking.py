from __future__ import annotations

import math
from typing import Any, Callable

from traffic_lpr_runtime.application.analysis_policy import (
    SHORT_INTERVAL_MAX_MS,
    SHORT_INTERVAL_MIN_SAMPLE_BUDGET,
    SHORT_INTERVAL_SAMPLE_STEP_MS,
)
from traffic_lpr_runtime.application.pipeline_support import AnalysisOptions
from traffic_lpr_runtime.domain.models import TargetTrack, TrackedRegion
from traffic_lpr_runtime.domain.value_objects import NormalizedRect, clamp


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _build_temporal_range_diagnostics(
    tracked_frames: list[TrackedRegion],
    tracking_times: list[int],
    trajectory_step_ms: int,
    anchor_time_ms: int,
) -> dict[str, Any]:
    if not tracking_times:
        return {
            'requestedStartMs': anchor_time_ms,
            'requestedEndMs': anchor_time_ms,
            'trackedStartMs': None,
            'trackedEndMs': None,
            'trackedSpanMs': 0,
            'coverageRatio': 0.0,
            'reachedRequestedStart': False,
            'reachedRequestedEnd': False,
            'gapCount': 0,
            'maxGapMs': 0,
            'averageGapMs': 0.0,
            'averageMotion': 0.0,
            'motionVariance': 0.0,
            'motionStdDev': 0.0,
            'maxMotion': 0.0,
            'motionHotspotThreshold': 0.0,
        }

    requested_start_ms = tracking_times[0]
    requested_end_ms = tracking_times[-1]
    tracked_start_ms = tracked_frames[0].time_ms if tracked_frames else None
    tracked_end_ms = tracked_frames[-1].time_ms if tracked_frames else None
    tracked_span_ms = max(0, (tracked_end_ms or requested_start_ms) - (tracked_start_ms or requested_start_ms))
    coverage_ratio = 0.0 if not tracking_times else max(0.0, min(1.0, len(tracked_frames) / max(len(tracking_times), 1)))

    gaps_ms: list[int] = []
    motion_samples: list[float] = []
    for previous, current in zip(tracked_frames, tracked_frames[1:]):
        gaps_ms.append(max(0, current.time_ms - previous.time_ms))
        motion_samples.append(current.box.center_distance(previous.box))

    average_gap_ms = sum(gaps_ms) / len(gaps_ms) if gaps_ms else 0.0
    gap_threshold_ms = max(int(round(trajectory_step_ms * 1.5)), trajectory_step_ms + 1)
    gap_count = sum(1 for gap_ms in gaps_ms if gap_ms > gap_threshold_ms)
    max_gap_ms = max(gaps_ms, default=0)

    average_motion = sum(motion_samples) / len(motion_samples) if motion_samples else 0.0
    motion_variance = (
        sum((motion - average_motion) ** 2 for motion in motion_samples) / len(motion_samples)
        if motion_samples
        else 0.0
    )
    motion_std_dev = math.sqrt(motion_variance)
    max_motion = max(motion_samples, default=0.0)
    motion_hotspot_threshold = max(average_motion + motion_std_dev, max_motion * 0.85)
    if motion_hotspot_threshold <= 0.0:
        motion_hotspot_threshold = 0.0

    return {
        'requestedStartMs': requested_start_ms,
        'requestedEndMs': requested_end_ms,
        'trackedStartMs': tracked_start_ms,
        'trackedEndMs': tracked_end_ms,
        'trackedSpanMs': tracked_span_ms,
        'coverageRatio': coverage_ratio,
        'reachedRequestedStart': tracked_start_ms == requested_start_ms,
        'reachedRequestedEnd': tracked_end_ms == requested_end_ms,
        'gapCount': gap_count,
        'maxGapMs': max_gap_ms,
        'averageGapMs': average_gap_ms,
        'averageMotion': average_motion,
        'motionVariance': motion_variance,
        'motionStdDev': motion_std_dev,
        'maxMotion': max_motion,
        'motionHotspotThreshold': motion_hotspot_threshold,
    }


def _resolve_evidence_sample_budget(
    sample_times: list[int],
    duration_ms: int,
    preserve_dense_schedule: bool,
    max_evidence_sample_count: int,
) -> int:
    adaptive_cap = max_evidence_sample_count
    if duration_ms >= 12000:
        adaptive_cap = min(adaptive_cap, 10)
    if duration_ms >= 20000:
        adaptive_cap = min(adaptive_cap, 8)

    if preserve_dense_schedule or len(sample_times) <= adaptive_cap:
        return len(sample_times)
    if duration_ms <= 4000:
        return min(len(sample_times), max(adaptive_cap, 8))
    return min(len(sample_times), adaptive_cap)


def _resolve_anchor_burst_count(
    duration_ms: int,
    evidence_budget: int,
    anchor_burst_count: int,
) -> int:
    resolved = max(1, anchor_burst_count)
    if duration_ms >= 12000 or evidence_budget <= 10:
        resolved = min(resolved, 3)
    if duration_ms >= 20000 or evidence_budget <= 8:
        resolved = min(resolved, 2)
    return max(1, resolved)


def _sparsify_evidence_sample_times(
    interval: dict[str, int],
    anchor_time_ms: int,
    sample_step_ms: int,
    budget: int,
    anchor_burst_count: int,
) -> list[int]:
    start_ms = int(interval['startMs'])
    end_ms = int(interval['endMs'])
    if budget <= 0:
        return []

    chosen: list[int] = []

    def choose(time_ms: int | None) -> None:
        if time_ms is None or time_ms in chosen or time_ms < start_ms or time_ms > end_ms:
            return
        chosen.append(time_ms)

    choose(anchor_time_ms)
    choose(start_ms)
    choose(end_ms)

    burst_step_ms = max(45, min(sample_step_ms, 90))
    for burst_index in range(1, max(1, anchor_burst_count) + 1):
        choose(anchor_time_ms - (burst_step_ms * burst_index))
        if len(chosen) >= budget:
            break
        choose(anchor_time_ms + (burst_step_ms * burst_index))
        if len(chosen) >= budget:
            break

    offset_ms = sample_step_ms
    while len(chosen) < budget and (anchor_time_ms - offset_ms >= start_ms or anchor_time_ms + offset_ms <= end_ms):
        choose(anchor_time_ms - offset_ms)
        if len(chosen) >= budget:
            break
        choose(anchor_time_ms + offset_ms)
        offset_ms += sample_step_ms

    return sorted(chosen)


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

        if duration_ms <= SHORT_INTERVAL_MAX_MS:
            return SHORT_INTERVAL_SAMPLE_STEP_MS

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
        if duration_ms >= 20000:
            min_step_ms, max_step_ms = 200, 320
        elif duration_ms >= 12000:
            min_step_ms, max_step_ms = 100, 180
        elif duration_ms >= 6000:
            min_step_ms, max_step_ms = 80, 140
        else:
            min_step_ms, max_step_ms = 50, 100
        return max(min_step_ms, min(max_step_ms, rounded_step_ms))

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

        if duration_ms <= SHORT_INTERVAL_MAX_MS:
            max_samples = max(max_samples, SHORT_INTERVAL_MIN_SAMPLE_BUDGET)

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
        raw_evidence_sample_times: list[int],
        anchor_burst_count: int,
    ) -> tuple[list[TrackedRegion], dict[str, Any]]:
        evidence_sample_time_set = set(evidence_sample_times)
        burst_step_ms = max(45, min(trajectory_step_ms, 90))
        temporal_burst_time_set = {
            time_ms
            for time_ms in raw_evidence_sample_times
            if abs(time_ms - anchor_time_ms) <= (burst_step_ms * max(anchor_burst_count, 1))
        }
        temporal_range = _build_temporal_range_diagnostics(
            tracked_frames,
            tracking_times,
            trajectory_step_ms,
            anchor_time_ms,
        )
        hotspot_threshold = float(temporal_range.get('motionHotspotThreshold') or 0.0)
        for index, tracked_frame in enumerate(tracked_frames):
            previous_frame = tracked_frames[index - 1] if index > 0 else None
            next_frame = tracked_frames[index + 1] if index + 1 < len(tracked_frames) else None
            incoming_gap_ms = max(0, tracked_frame.time_ms - previous_frame.time_ms) if previous_frame is not None else 0
            outgoing_gap_ms = max(0, next_frame.time_ms - tracked_frame.time_ms) if next_frame is not None else 0
            incoming_motion = tracked_frame.box.center_distance(previous_frame.box) if previous_frame is not None else 0.0
            outgoing_motion = next_frame.box.center_distance(tracked_frame.box) if next_frame is not None else 0.0
            local_motion = max(incoming_motion, outgoing_motion)
            is_motion_hotspot = hotspot_threshold > 0.0 and local_motion >= hotspot_threshold
            requested_position = 0.0
            if tracking_times and tracking_times[-1] != tracking_times[0]:
                requested_position = (tracked_frame.time_ms - tracking_times[0]) / max(tracking_times[-1] - tracking_times[0], 1)
            evidence_reasons: list[str] = []
            if index == 0:
                evidence_reasons.append('interval-start')
            if tracked_frame.time_ms == anchor_time_ms:
                evidence_reasons.append('anchor')
            if tracked_frame.time_ms in evidence_sample_time_set:
                evidence_reasons.append('scheduled-sample')
            if tracked_frame.time_ms in temporal_burst_time_set and tracked_frame.time_ms != anchor_time_ms:
                evidence_reasons.append('temporal-burst')
            if index == len(tracked_frames) - 1:
                evidence_reasons.append('interval-end')
            if is_motion_hotspot:
                evidence_reasons.append('motion-hotspot')
            if tracked_frame.confidence >= 0.85:
                evidence_reasons.append('high-confidence')
            evidence_priority = tracked_frame.confidence
            evidence_priority += local_motion * 2.0
            evidence_priority += 0.75 if tracked_frame.time_ms in evidence_sample_time_set else 0.0
            evidence_priority += 1.5 if tracked_frame.time_ms == anchor_time_ms else 0.0
            evidence_priority += 0.35 if index in {0, len(tracked_frames) - 1} else 0.0
            evidence_priority += 0.5 if is_motion_hotspot else 0.0
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
                'incomingGapMs': incoming_gap_ms,
                'outgoingGapMs': outgoing_gap_ms,
                'incomingMotion': incoming_motion,
                'outgoingMotion': outgoing_motion,
                'localMotion': local_motion,
                'isMotionHotspot': is_motion_hotspot,
                'requestedIntervalPosition': requested_position,
                'evidencePriority': evidence_priority,
                'evidenceReasons': evidence_reasons,
            }

        return tracked_frames, {
            **diagnostics,
            'matchedFrames': len(tracked_frames),
            'requestedTrackingFrameCount': len(tracking_times),
            'requestedEvidenceSampleCount': len(evidence_sample_times),
            'rawRequestedEvidenceSampleCount': len(raw_evidence_sample_times),
            'effectiveAnchorBurstCount': anchor_burst_count,
            'trajectoryFrameCount': len(tracked_frames),
            'trajectoryStepMs': trajectory_step_ms,
            'evidenceSampleTimes': evidence_sample_times,
            'rawEvidenceSampleTimes': raw_evidence_sample_times,
            'sparseEvidenceSamplingApplied': len(evidence_sample_times) < len(raw_evidence_sample_times),
            'anchorTimeMs': anchor_time_ms,
            'temporalRange': temporal_range,
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
