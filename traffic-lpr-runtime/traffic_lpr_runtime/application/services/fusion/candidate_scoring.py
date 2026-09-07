from __future__ import annotations

from traffic_lpr_runtime.application.services.fusion.plate_format import _plate_format_score
from traffic_lpr_runtime.domain.models import FrameSample, PlateCandidate
from traffic_lpr_runtime.domain.text import normalize_plate_text


def _candidate_support_frames_payload(candidate: PlateCandidate) -> set[int]:
    diagnostics = candidate.diagnostics or {}
    support_frames = diagnostics.get('supportFrames')
    frames: set[int] = set()
    if isinstance(support_frames, list):
        frames.update(int(frame) for frame in support_frames if isinstance(frame, (int, float)))
    elif isinstance(support_frames, (int, float)):
        frames.add(int(support_frames))
    if candidate.frame_time_ms is not None:
        frames.add(int(candidate.frame_time_ms))
    return frames


def _candidate_weight(candidate: PlateCandidate, source_weights: dict[str, float]) -> float:
    source_key = candidate.source.split(':', 1)[0]
    quality_weight = candidate.quality.overall_score if candidate.quality else 0.55
    diagnostics = candidate.diagnostics or {}
    taiwan_prior = float(diagnostics.get('taiwanPrior') or 1.0)
    weight = candidate.confidence * quality_weight * source_weights.get(source_key, 1.0) * taiwan_prior

    if source_key == 'fused-char':
        character_consistency_mean = float(diagnostics.get('characterConsistencyMean') or candidate.confidence or 0.0)
        char_fusion_reliability = max(0.25, min(1.0, character_consistency_mean))
        if diagnostics.get('matchesDominantSequence') is not True:
            char_fusion_reliability *= 0.6
        weight *= char_fusion_reliability

    return weight


def _best_frame_candidate(samples: list[FrameSample], source_weights: dict[str, float]) -> tuple[PlateCandidate | None, float]:
    best_candidate: PlateCandidate | None = None
    best_weight = 0.0
    for sample in samples:
        for rank, candidate in enumerate(sample.candidates):
            text = normalize_plate_text(candidate.text)
            if not text:
                continue
            rank_penalty = max(0.7, 1.0 - (rank * 0.12))
            weighted_score = _candidate_weight(candidate, source_weights) * rank_penalty
            if weighted_score > best_weight:
                best_candidate = candidate
                best_weight = weighted_score
    return best_candidate, best_weight


def _source_family(source: str) -> str:
    return source.split(':', 1)[0]


def _consensus_signal_names(
    text: str,
    dominant_text: str,
    char_fused_text: str,
    best_frame_text: str,
) -> list[str]:
    signals: list[str] = []
    if text and text == dominant_text:
        signals.append('dominant-sequence')
    if text and text == char_fused_text:
        signals.append('char-fused')
    if text and text == best_frame_text:
        signals.append('best-frame')
    return signals


def _consensus_weight_multiplier(
    consensus_signals: list[str],
    support_frame_count: int,
    source_count: int,
) -> float:
    if len(consensus_signals) < 2:
        return 1.0
    if support_frame_count < 2:
        return 1.0

    multiplier = 1.06 + (max(0, len(consensus_signals) - 2) * 0.04)
    if support_frame_count >= 2:
        multiplier += min(0.03, (support_frame_count - 1) * 0.008)
    if source_count >= 2:
        multiplier += min(0.03, (source_count - 1) * 0.008)
    return multiplier


def _candidate_reliability_score(candidate: PlateCandidate, country_hints: list[str]) -> float:
    quality_score = candidate.quality.overall_score if candidate.quality is not None else 0.0
    support_score = min(_candidate_support_frame_count(candidate), 4) / 4.0
    format_score = _plate_format_score(candidate.text, country_hints)
    return (
        (candidate.confidence * 0.58)
        + (quality_score * 0.20)
        + (support_score * 0.12)
        + (format_score * 0.10)
    )


def _candidate_support_frame_count(candidate: PlateCandidate) -> int:
    diagnostics = candidate.diagnostics or {}
    support_frames = diagnostics.get('supportFrames')
    if isinstance(support_frames, list):
        return len({int(frame) for frame in support_frames if isinstance(frame, (int, float))})
    if isinstance(support_frames, (int, float)):
        return max(1, int(support_frames))
    return 1 if candidate.frame_time_ms is not None else 0
