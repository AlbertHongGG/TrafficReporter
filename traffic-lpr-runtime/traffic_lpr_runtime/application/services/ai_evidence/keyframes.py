from __future__ import annotations

from typing import Any, Sequence
from pathlib import Path
from traffic_lpr_runtime.application.services.ai_evidence.models import (
    MIN_DISTINCT_STORYBOARD_GAP_MS,
    RenderedFrame,
    SelectedKeyframe,
    _format_time_label,
)


from traffic_lpr_runtime.domain.errors import RuntimeFailure

def _sample_times(duration_ms: int, step_ms: int, *, max_samples: int, offset_ms: int = 0) -> list[int]:
    if duration_ms <= 0:
        return [offset_ms]
    times: list[int] = []
    current = offset_ms
    end_ms = offset_ms + duration_ms
    while current <= end_ms:
        times.append(current)
        current += step_ms
    if times[-1] != end_ms:
        if end_ms - times[-1] < MIN_DISTINCT_STORYBOARD_GAP_MS:
            times[-1] = end_ms
        else:
            times.append(end_ms)
    if len(times) <= max_samples:
        return times
    indices = [round(index * (len(times) - 1) / max(1, max_samples - 1)) for index in range(max_samples)]
    return [times[index] for index in OrderedDict.fromkeys(indices)]



def _encode_image_path(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode('ascii')


def _resolve_frame_ref(value: Any, frames: list[RenderedFrame]) -> RenderedFrame:
    if isinstance(value, str):
        for frame in frames:
            if frame.frame_id == value:
                return frame
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        for frame in frames:
            if frame.sequence_index == int(value):
                return frame
    raise RuntimeFailure('LLM returned an unknown frame reference.')


def _normalize_keyframes(value: Any, frames: list[RenderedFrame], *, desired_count: int) -> list[SelectedKeyframe]:
    ordered_frames = sorted(frames, key=lambda item: item.time_ms)
    by_id = {frame.frame_id: frame for frame in ordered_frames}
    selected: list[SelectedKeyframe] = []
    for item in value if isinstance(value, list) else []:
        frame_id = item.get('frameId') if isinstance(item, dict) else item if isinstance(item, str) else None
        if isinstance(frame_id, str) and frame_id in by_id:
            frame = by_id[frame_id]
            description = ''
            if isinstance(item, dict):
                description = str(item.get('description') or '').strip()
            if description:
                selected.append(SelectedKeyframe(
                    frame=frame,
                    description=description,
                ))
                continue
            selected.append(SelectedKeyframe(
                frame=frame,
                description=_fallback_keyframe_description(frame=frame, frames=ordered_frames),
                description_source='fallback',
                supplement_reason='missing-description',
            ))
    deduped: list[SelectedKeyframe] = []
    seen_frame_ids: set[str] = set()
    for entry in selected:
        if entry.frame.frame_id in seen_frame_ids:
            continue
        seen_frame_ids.add(entry.frame.frame_id)
        deduped.append(entry)
    deduped = _collapse_temporally_dense_keyframes(deduped)
    deduped = _rebalance_keyframes_for_temporal_coverage(
        deduped,
        ordered_frames,
        desired_count=desired_count,
    )
    seen_frame_ids = {entry.frame.frame_id for entry in deduped}
    if len(deduped) < desired_count:
        for frame in ordered_frames:
            if frame.frame_id in seen_frame_ids:
                continue
            seen_frame_ids.add(frame.frame_id)
            deduped.append(_build_runtime_supplemented_keyframe(
                frame=frame,
                frames=ordered_frames,
                supplement_reason='under-target-backfill',
            ))
            if len(deduped) >= desired_count:
                break
    return sorted(deduped, key=lambda entry: entry.frame.time_ms)[:desired_count]


def _build_runtime_supplemented_keyframe(
    *,
    frame: RenderedFrame,
    frames: list[RenderedFrame],
    supplement_reason: str,
) -> SelectedKeyframe:
    return SelectedKeyframe(
        frame=frame,
        description=_fallback_keyframe_description(frame=frame, frames=frames),
        keyframe_source='runtime-supplemented',
        description_source='fallback',
        supplement_reason=supplement_reason,
    )


def _collapse_temporally_dense_keyframes(
    keyframes: list[SelectedKeyframe],
    *,
    minimum_gap_ms: int = MIN_DISTINCT_STORYBOARD_GAP_MS,
) -> list[SelectedKeyframe]:
    collapsed: list[SelectedKeyframe] = []
    for entry in sorted(keyframes, key=lambda item: item.frame.time_ms):
        if not collapsed:
            collapsed.append(entry)
            continue
        previous = collapsed[-1]
        if entry.frame.time_ms - previous.frame.time_ms >= minimum_gap_ms:
            collapsed.append(entry)
            continue
        if _selected_keyframe_priority(entry) >= _selected_keyframe_priority(previous):
            collapsed[-1] = entry
    return collapsed


def _selected_keyframe_priority(entry: SelectedKeyframe) -> tuple[int, int, int]:
    return (
        1 if entry.description_source == 'llm' else 0,
        1 if entry.keyframe_source == 'llm-selected' else 0,
        entry.frame.time_ms,
    )


def _rebalance_keyframes_for_temporal_coverage(
    keyframes: list[SelectedKeyframe],
    frames: list[RenderedFrame],
    *,
    desired_count: int,
) -> list[SelectedKeyframe]:
    if not keyframes or not frames or desired_count <= 0:
        return sorted(keyframes, key=lambda item: item.frame.time_ms)

    bucket_count = _temporal_bucket_count(len(frames), desired_count)
    if bucket_count <= 1:
        return sorted(keyframes, key=lambda item: item.frame.time_ms)

    buckets = _split_frames_into_temporal_buckets(frames, bucket_count)
    frame_bucket_indices = {
        frame.frame_id: bucket_index
        for bucket_index, bucket in enumerate(buckets)
        for frame in bucket
    }
    per_bucket_cap = max(1, (desired_count + bucket_count - 1) // bucket_count)
    selected_by_id = {
        entry.frame.frame_id: entry
        for entry in sorted(keyframes, key=lambda item: item.frame.time_ms)
    }
    result: list[SelectedKeyframe] = []
    seen_frame_ids: set[str] = set()
    bucket_counts = [0] * len(buckets)

    def add_entry(entry: SelectedKeyframe, *, respect_cap: bool) -> bool:
        frame_id = entry.frame.frame_id
        if frame_id in seen_frame_ids:
            return False
        bucket_index = frame_bucket_indices.get(frame_id)
        if bucket_index is None:
            return False
        if respect_cap and bucket_counts[bucket_index] >= per_bucket_cap:
            return False
        seen_frame_ids.add(frame_id)
        bucket_counts[bucket_index] += 1
        result.append(entry)
        return True

    for bucket in buckets:
        bucket_selected = [selected_by_id[frame.frame_id] for frame in bucket if frame.frame_id in selected_by_id]
        if bucket_selected:
            add_entry(bucket_selected[0], respect_cap=False)
            continue
        fallback_frame = _pick_bucket_frame(bucket, seen_frame_ids)
        if fallback_frame is None:
            continue
        add_entry(_build_runtime_supplemented_keyframe(
            frame=fallback_frame,
            frames=frames,
            supplement_reason='temporal-coverage',
        ), respect_cap=False)

    for entry in sorted(keyframes, key=lambda item: item.frame.time_ms):
        if len(result) >= desired_count:
            break
        add_entry(entry, respect_cap=True)

    while len(result) < desired_count:
        progress = False
        for bucket_index in _bucket_fill_order(bucket_counts):
            if len(result) >= desired_count:
                break
            if bucket_counts[bucket_index] >= per_bucket_cap:
                continue
            fallback_frame = _pick_bucket_frame(buckets[bucket_index], seen_frame_ids)
            if fallback_frame is None:
                continue
            if add_entry(_build_runtime_supplemented_keyframe(
                frame=fallback_frame,
                frames=frames,
                supplement_reason='temporal-coverage',
            ), respect_cap=True):
                progress = True
        if not progress:
            break

    return sorted(result, key=lambda item: item.frame.time_ms)


def _temporal_bucket_count(frame_count: int, desired_count: int) -> int:
    if frame_count <= 0 or desired_count <= 0:
        return 0
    if desired_count >= 8 and frame_count >= 5:
        return 5
    if desired_count >= 6 and frame_count >= 4:
        return 4
    return min(frame_count, desired_count)


def _split_frames_into_temporal_buckets(frames: list[RenderedFrame], bucket_count: int) -> list[list[RenderedFrame]]:
    buckets: list[list[RenderedFrame]] = []
    for bucket_index in range(bucket_count):
        start = (bucket_index * len(frames)) // bucket_count
        end = max(start + 1, ((bucket_index + 1) * len(frames)) // bucket_count)
        bucket = frames[start:end]
        if bucket:
            buckets.append(bucket)
    return buckets


def _pick_bucket_frame(bucket: list[RenderedFrame], seen_frame_ids: set[str]) -> RenderedFrame | None:
    candidates = [frame for frame in bucket if frame.frame_id not in seen_frame_ids]
    if not candidates:
        return None
    center_frame = bucket[len(bucket) // 2]
    return min(candidates, key=lambda frame: (abs(frame.time_ms - center_frame.time_ms), frame.time_ms))


def _bucket_fill_order(bucket_counts: list[int]) -> list[int]:
    if not bucket_counts:
        return []
    center_index = (len(bucket_counts) - 1) / 2
    return sorted(
        range(len(bucket_counts)),
        key=lambda index: (bucket_counts[index], abs(index - center_index), index),
    )


def _resolve_keyframe_count_reason(
    *,
    rendered_count: int,
    desired_count: int,
    available_frame_count: int,
    provider_reason: str | None,
) -> str | None:
    if rendered_count >= 8:
        return None
    if available_frame_count < 8:
        return f'Only {available_frame_count} distinct fine storyboard frame(s) were available, so 8 keyframes could not be produced.'
    if rendered_count < desired_count and provider_reason:
        return provider_reason
    return f'Only {rendered_count} user-facing keyframe(s) survived runtime rendering after validation.'


def _fallback_keyframe_description(*, frame: RenderedFrame, frames: list[RenderedFrame]) -> str:
    ordered_frames = sorted(frames, key=lambda item: item.time_ms)
    if not ordered_frames:
        return '這是事件中的關鍵畫面，請重點查看主要目標與周邊情境。'

    position = ordered_frames.index(frame) if frame in ordered_frames else 0
    if position == 0:
        stage_description = '這是事件開始附近的關鍵畫面，請重點確認目標最初出現的位置與周邊情境。'
    elif position == len(ordered_frames) - 1:
        stage_description = '這是事件尾段的關鍵畫面，請重點確認目標最後的位置、動作與結果。'
    else:
        stage_description = '這是事件進行中的關鍵畫面，請重點查看目標的動作變化與周邊互動。'

    return f'{stage_description} 畫面時間約為 T+{_format_time_label(frame.time_ms)}。'


def _find_closest_track_box(track: dict[str, Any] | None, time_ms: int) -> tuple[dict[str, Any] | None, str | None, int | None]:
    if not isinstance(track, dict):
        return None, None, None
    frames = [frame for frame in (track.get('frames') or []) if isinstance(frame, dict) and isinstance(frame.get('box'), dict)]
    if not frames:
        return None, None, None
    closest = min(frames, key=lambda frame: abs(int(frame.get('timeMs') or 0) - time_ms))
    closest_time_ms = int(closest.get('timeMs') or 0)
    time_delta_ms = abs(closest_time_ms - time_ms)
    if time_delta_ms > _keyframe_track_box_tolerance_ms(frames):
        return None, None, time_delta_ms
    return closest.get('box') if isinstance(closest.get('box'), dict) else None, 'analysis-track', time_delta_ms


def _keyframe_track_box_tolerance_ms(track_frames: Sequence[dict[str, Any]]) -> int:
    ordered_times = sorted(
        int(frame.get('timeMs') or 0)
        for frame in track_frames
        if isinstance(frame, dict)
    )
    if len(ordered_times) < 2:
        return 240
    deltas = [
        current - previous
        for previous, current in zip(ordered_times, ordered_times[1:])
        if current > previous
    ]
    if not deltas:
        return 240
    deltas.sort()
    median_delta = deltas[len(deltas) // 2]
    return max(180, min(600, median_delta * 2))


