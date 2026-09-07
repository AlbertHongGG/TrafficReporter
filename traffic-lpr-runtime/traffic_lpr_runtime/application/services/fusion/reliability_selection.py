from __future__ import annotations

from typing import Any

from traffic_lpr_runtime.application.services.fusion.candidate_scoring import (
    _candidate_reliability_score,
    _candidate_support_frame_count,
)
from traffic_lpr_runtime.application.services.fusion.plate_format import (
    _plate_format_score,
    _uses_taiwan_hint,
)
from traffic_lpr_runtime.domain.analysis_options import AnalysisOptions
from traffic_lpr_runtime.domain.models import FrameSample, PlateCandidate
from traffic_lpr_runtime.domain.text import normalize_plate_text


def apply_reliability_selection(
    candidates: list[PlateCandidate],
    samples: list[FrameSample],
    country_hints: list[str],
    options: AnalysisOptions,
    interval_mode: bool,
) -> tuple[list[PlateCandidate], str | None, dict[str, Any]]:
    if not candidates:
        return [], None, {
            'acceptedCandidateId': None,
            'suggestedCandidateId': None,
            'fallbackCandidateId': None,
            'reviewRequired': True,
            'usedFallback': False,
            'reasons': ['no-candidate'],
        }

    ordered_candidates = list(candidates)
    top_candidate = ordered_candidates[0]
    runner_up_candidate = ordered_candidates[1] if len(ordered_candidates) > 1 else None
    fallback_candidate = _best_sample_candidate(samples, country_hints)
    accepted_margin = max(0.0, top_candidate.confidence - (runner_up_candidate.confidence if runner_up_candidate is not None else 0.0))

    review_reasons = [] if not options.enable_reliability_gates else _review_reasons(
        top_candidate,
        accepted_margin,
        country_hints,
        options,
        interval_mode,
    )
    suggested_candidate = top_candidate
    used_fallback = False
    if interval_mode and review_reasons and _plate_format_score(top_candidate.text, country_hints) < 0.65:
        interval_candidate = _best_interval_review_candidate(ordered_candidates, country_hints, options)
        if interval_candidate is not None and interval_candidate.id != suggested_candidate.id:
            suggested_candidate = interval_candidate
            review_reasons = [] if not options.enable_reliability_gates else _review_reasons(
                suggested_candidate,
                max(0.0, suggested_candidate.confidence - (runner_up_candidate.confidence if runner_up_candidate is not None else 0.0)),
                country_hints,
                options,
                interval_mode,
            )
    if review_reasons and fallback_candidate is not None and fallback_candidate.id != top_candidate.id:
        top_score = _candidate_reliability_score(top_candidate, country_hints)
        fallback_score = _candidate_reliability_score(fallback_candidate, country_hints)
        fallback_format_score = _plate_format_score(fallback_candidate.text, country_hints)
        format_advantage = fallback_format_score - _plate_format_score(top_candidate.text, country_hints)
        top_support_count = _candidate_support_frame_count(top_candidate)
        fallback_support_count = _candidate_support_frame_count(fallback_candidate)
        required_score_advantage = 0.05
        fallback_text = normalize_plate_text(fallback_candidate.text)
        suggested_text = normalize_plate_text(suggested_candidate.text)
        fallback_allowed = True
        if interval_mode and (fallback_format_score < 0.65 or fallback_text == suggested_text):
            fallback_allowed = False
        if interval_mode and fallback_support_count < top_support_count and format_advantage < 0.2:
            required_score_advantage = 0.18
        if fallback_allowed and (fallback_score >= top_score + required_score_advantage or format_advantage >= 0.2):
            suggested_candidate = fallback_candidate
            used_fallback = True
            review_reasons = [] if not options.enable_reliability_gates else _review_reasons(
                suggested_candidate,
                max(0.0, suggested_candidate.confidence - top_candidate.confidence),
                country_hints,
                options,
                interval_mode,
            )

    if all(candidate.id != suggested_candidate.id for candidate in ordered_candidates):
        ordered_candidates.insert(0, suggested_candidate)
    else:
        ordered_candidates.sort(key=lambda candidate: 0 if candidate.id == suggested_candidate.id else 1)

    review_required = bool(review_reasons)
    accepted_candidate_id = None if review_required else suggested_candidate.id
    selection_diagnostics = {
        'acceptedCandidateId': accepted_candidate_id,
        'suggestedCandidateId': suggested_candidate.id,
        'fallbackCandidateId': fallback_candidate.id if fallback_candidate is not None else None,
        'topCandidateId': top_candidate.id,
        'topCandidateText': top_candidate.text,
        'runnerUpCandidateId': runner_up_candidate.id if runner_up_candidate is not None else None,
        'runnerUpText': runner_up_candidate.text if runner_up_candidate is not None else None,
        'runnerUpConfidence': runner_up_candidate.confidence if runner_up_candidate is not None else None,
        'reviewRequired': review_required,
        'usedFallback': used_fallback,
        'reasons': review_reasons,
        'acceptedMargin': accepted_margin,
        'suggestedConfidence': suggested_candidate.confidence,
        'suggestedText': suggested_candidate.text,
        'supportFrameCount': _candidate_support_frame_count(suggested_candidate),
        'formatScore': _plate_format_score(suggested_candidate.text, country_hints),
    }

    for candidate in ordered_candidates:
        candidate.diagnostics = {
            **(candidate.diagnostics or {}),
            'selection': {
                'isAccepted': candidate.id == accepted_candidate_id,
                'isSuggested': candidate.id == suggested_candidate.id,
                'reviewRequired': review_required,
                'usedFallback': used_fallback and candidate.id == suggested_candidate.id,
                'reasons': review_reasons if candidate.id == suggested_candidate.id else [],
            },
        }
    return ordered_candidates[:8], accepted_candidate_id, selection_diagnostics


def _review_reasons(
    candidate: PlateCandidate,
    accepted_margin: float,
    country_hints: list[str],
    options: AnalysisOptions,
    interval_mode: bool,
) -> list[str]:
    reasons: list[str] = []
    if candidate.confidence < options.min_accepted_confidence:
        reasons.append('low-confidence')
    if accepted_margin < options.min_candidate_margin:
        reasons.append('low-margin')
    if interval_mode and _candidate_support_frame_count(candidate) < options.min_interval_support_frames:
        reasons.append('insufficient-support')
    diagnostics = candidate.diagnostics or {}
    sequence_tier = str(diagnostics.get('sequenceTier') or '')
    sequence_support_ratio = float(diagnostics.get('sequenceSupportRatio') or 0.0)
    sequence_consistency = float(diagnostics.get('sequenceCharacterConsistencyMean') or 0.0)
    if interval_mode and sequence_tier in {'fragmented', 'gapped'}:
        reasons.append('unstable-sequence')
    if interval_mode and sequence_support_ratio < max(0.34, options.min_sequence_persistence * 0.5):
        reasons.append('weak-sequence-support')
    if interval_mode and sequence_consistency < 0.55:
        reasons.append('weak-character-consensus')
    if _uses_taiwan_hint(country_hints) and _plate_format_score(candidate.text, country_hints) < 0.65:
        reasons.append('format-mismatch')
    return reasons


def _best_sample_candidate(samples: list[FrameSample], country_hints: list[str]) -> PlateCandidate | None:
    best_candidate: PlateCandidate | None = None
    best_score = 0.0
    for sample in samples:
        for candidate in sample.candidates:
            score = _candidate_reliability_score(candidate, country_hints)
            if best_candidate is None or score > best_score:
                best_candidate = candidate
                best_score = score
    return best_candidate


def _best_interval_review_candidate(
    candidates: list[PlateCandidate],
    country_hints: list[str],
    options: AnalysisOptions,
) -> PlateCandidate | None:
    plate_like_candidates = [
        candidate
        for candidate in candidates
        if _plate_format_score(candidate.text, country_hints) >= 0.65
    ]
    if not plate_like_candidates:
        return None

    return max(
        plate_like_candidates,
        key=lambda candidate: (
            _candidate_support_frame_count(candidate) >= options.min_interval_support_frames,
            _plate_format_score(candidate.text, country_hints),
            _candidate_support_frame_count(candidate),
            candidate.confidence,
            len(normalize_plate_text(candidate.text)),
        ),
    )
