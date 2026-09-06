from __future__ import annotations

import re
from typing import Any, Sequence
from traffic_lpr_runtime.domain.models import TrackedRegion
from traffic_lpr_runtime.domain.value_objects import NormalizedRect
from traffic_lpr_runtime.domain.text import normalize_plate_text

def _dedupe_anchor_target_detections(detections: Sequence[TrackedRegion]) -> list[TrackedRegion]:
    deduped: list[TrackedRegion] = []
    suppressed_counts: dict[str, int] = {}

    for detection in sorted(detections, key=lambda candidate: candidate.confidence, reverse=True):
        duplicate_owner = next(
            (candidate for candidate in deduped if _anchor_target_detections_overlap(candidate, detection)),
            None,
        )
        if duplicate_owner is not None:
            suppressed_counts[duplicate_owner.id] = suppressed_counts.get(duplicate_owner.id, 0) + 1
            continue
        deduped.append(detection)

    for detection in deduped:
        suppressed = suppressed_counts.get(detection.id, 0)
        if suppressed <= 0:
            continue
        detection.diagnostics = {
            **(detection.diagnostics or {}),
            'suppressedDuplicateDetections': suppressed,
        }

    return deduped


def _anchor_target_detections_overlap(left: TrackedRegion, right: TrackedRegion) -> bool:
    if left.class_name != right.class_name:
        return False

    iou = left.box.intersection_over_union(right.box)
    overlap_over_smaller = _overlap_over_smaller(left.box, right.box)
    center_distance = left.box.center_distance(right.box)
    area_similarity = min(left.box.area(), right.box.area()) / max(left.box.area(), right.box.area(), 1e-6)
    return (
        iou >= 0.58
        or overlap_over_smaller >= 0.78
        or (
            overlap_over_smaller >= 0.52
            and center_distance <= 0.055
            and area_similarity >= 0.34
        )
    )


def _overlap_over_smaller(left: NormalizedRect, right: NormalizedRect) -> float:
    left_x2 = left.x + left.width
    left_y2 = left.y + left.height
    right_x2 = right.x + right.width
    right_y2 = right.y + right.height
    inter_x1 = max(left.x, right.x)
    inter_y1 = max(left.y, right.y)
    inter_x2 = min(left_x2, right_x2)
    inter_y2 = min(left_y2, right_y2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    return inter_area / max(min(left.area(), right.area()), 1e-6)


def _canonicalize_track_id(track: dict[str, Any], canonical_track_id: str) -> dict[str, Any]:
    original_track_id = _optional_string(track.get('id'))
    if original_track_id == canonical_track_id:
        return track
    return {
        **track,
        'id': canonical_track_id,
        'diagnostics': {
            **(track.get('diagnostics') or {}),
            'canonicalizedFromTrackId': original_track_id,
        },
    }


def _resolve_fine_step_ms(
    *,
    start_ms: int,
    end_ms: int,
    requested_step_ms: int,
    preferred_samples: int,
    max_samples: int,
) -> int:
    duration_ms = max(1, end_ms - start_ms)
    minimum_step = max(80, duration_ms // max(1, max_samples - 1))
    preferred_step = max(80, duration_ms // max(1, preferred_samples - 1))
    return max(minimum_step, min(max(80, requested_step_ms), preferred_step))



def _resolve_plate_candidate(candidates: Sequence[dict[str, Any]], accepted_candidate_id: Any) -> dict[str, Any] | None:
    accepted_id = _optional_string(accepted_candidate_id)
    if accepted_id:
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get('id') == accepted_id:
                return candidate
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return None


def _format_time_label(time_ms: int) -> str:
    total_ms = max(0, int(time_ms))
    total_seconds, milliseconds = divmod(total_ms, 1000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f'{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}'
    return f'{minutes:02d}:{seconds:02d}.{milliseconds:03d}'


def _normalize_plate(value: str) -> str:
    return ''.join(character for character in value.upper() if character.isalnum())


def _candidate_evidence_payload(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return None
    text = _optional_string(candidate.get('text'))
    return {
        'candidateId': _optional_string(candidate.get('id')),
        'text': text,
        'normalizedText': _normalize_plate(text) if text else None,
        'confidence': _float_value(candidate.get('confidence')) or 0.0,
        'source': _optional_string(candidate.get('source')),
    }


def _normalize_plate_hint_consistency(value: Any) -> str | None:
    normalized = _optional_string(value.lower()) if isinstance(value, str) else None
    if normalized in {'supporting', 'neutral', 'contradicted', 'not-applicable'}:
        return normalized
    return None


def _extract_plate_hint(description: str) -> str | None:
    match = re.search(r'([A-Z0-9]{2,4}-?[A-Z0-9]{2,4})', description.upper())
    if not match:
        return None
    return _normalize_plate(match.group(1))


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _float_value(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _build_summary(description: str, interval: dict[str, Any], plate_candidate: dict[str, Any] | None) -> str:
    plate_text = plate_candidate.get('text') if isinstance(plate_candidate, dict) else None
    plate_label = f'，車牌 {plate_text}' if isinstance(plate_text, str) and plate_text else ''
    return (
        f'根據描述「{description}」，完整事件區段為影片 T+{_format_time_label(int(interval["startMs"]))} '
        f'到 T+{_format_time_label(int(interval["endMs"]))}{plate_label}。'
    )


def _summarize_result(result: Any) -> str:
    if isinstance(result, list):
        return f'items={len(result)}'
    if isinstance(result, dict):
        if 'summary' in result:
            return str(result.get('summary') or '')[:160]
        return f'keys={len(result)}'
    return str(result)[:160]