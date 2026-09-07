from __future__ import annotations

from typing import Any

from traffic_lpr_runtime.domain.analysis_options import AnalysisOptions
from traffic_lpr_runtime.domain.models import FrameSample, PlateCandidate
from traffic_lpr_runtime.domain.text import normalize_plate_text


def _ordered_top_sample_candidates(samples: list[FrameSample]) -> list[tuple[int, PlateCandidate | None, str]]:
    ordered: list[tuple[int, PlateCandidate | None, str]] = []
    for sample in sorted(samples, key=lambda item: item.time_ms):
        candidate = sample.candidates[0] if sample.candidates else None
        text = normalize_plate_text(candidate.text) if candidate is not None else ''
        ordered.append((sample.time_ms, candidate, text))
    return ordered


def _support_gap_count(support_frames: list[int], ordered_sample_times: list[int]) -> int:
    if not support_frames or not ordered_sample_times:
        return 0
    sample_index_by_time = {time_ms: index for index, time_ms in enumerate(ordered_sample_times)}
    sorted_indexes = sorted(
        sample_index_by_time[time_ms]
        for time_ms in support_frames
        if time_ms in sample_index_by_time
    )
    gap_count = 0
    for previous, current in zip(sorted_indexes, sorted_indexes[1:]):
        if current - previous > 1:
            gap_count += 1
    return gap_count


def _sequence_tier(
    persistence_ratio: float,
    gap_count: int,
    prediction_switch_count: int,
    support_frame_count: int,
    character_consistency_mean: float,
) -> str:
    if support_frame_count <= 1 or persistence_ratio < 0.4:
        return 'fragmented'
    if gap_count > 1:
        return 'gapped'
    if prediction_switch_count > 0 or persistence_ratio < 0.72 or character_consistency_mean < 0.68:
        return 'drifting'
    return 'stable'


def _sequence_confidence_cap(candidate: PlateCandidate, sequence_summary: dict[str, Any], options: AnalysisOptions) -> float:
    diagnostics = candidate.diagnostics or {}
    sequence_tier = str(diagnostics.get('sequenceTier') or sequence_summary.get('sequenceTier') or 'fragmented')
    support_ratio = float(diagnostics.get('sequenceSupportRatio') or 0.0)
    support_frame_count = int(diagnostics.get('supportFrameCount') or 0)
    character_consistency_mean = float(sequence_summary.get('characterConsistencyMean') or 0.0)
    dominant_text = normalize_plate_text(sequence_summary.get('dominantText'))
    candidate_text = normalize_plate_text(candidate.text)

    if sequence_tier == 'stable':
        return 1.0
    if sequence_tier == 'drifting':
        return min(0.86, max(options.min_accepted_confidence - 0.02, 0.62 + (support_ratio * 0.20)))
    if sequence_tier == 'gapped':
        return min(0.78, max(0.52, 0.56 + (support_ratio * 0.18)))

    fragmented_cap = min(0.66, max(0.42, 0.45 + (support_ratio * 0.18) + (character_consistency_mean * 0.10)))
    if support_frame_count <= 1:
        fragmented_cap = min(fragmented_cap, 0.54)
    if candidate_text and candidate_text != dominant_text:
        fragmented_cap = min(fragmented_cap, 0.58)
    return fragmented_cap
