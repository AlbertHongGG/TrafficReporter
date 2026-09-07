from __future__ import annotations

from typing import Any

from traffic_lpr_runtime.domain.enums import EvidenceReason
from traffic_lpr_runtime.domain.models import TargetTrack, TrackedRegion

from .temporal_range import _build_temporal_range_diagnostics


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


class IntervalEvidenceMixin:
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
                evidence_reasons.append(EvidenceReason.INTERVAL_START.value)
            if tracked_frame.time_ms == anchor_time_ms:
                evidence_reasons.append(EvidenceReason.ANCHOR.value)
            if tracked_frame.time_ms in evidence_sample_time_set:
                evidence_reasons.append(EvidenceReason.SCHEDULED_SAMPLE.value)
            if tracked_frame.time_ms in temporal_burst_time_set and tracked_frame.time_ms != anchor_time_ms:
                evidence_reasons.append(EvidenceReason.TEMPORAL_BURST.value)
            if index == len(tracked_frames) - 1:
                evidence_reasons.append(EvidenceReason.INTERVAL_END.value)
            if is_motion_hotspot:
                evidence_reasons.append(EvidenceReason.MOTION_HOTSPOT.value)
            if tracked_frame.confidence >= 0.85:
                evidence_reasons.append(EvidenceReason.HIGH_CONFIDENCE.value)
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
