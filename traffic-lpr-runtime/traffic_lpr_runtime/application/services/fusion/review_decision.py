from __future__ import annotations

from typing import Any
from traffic_lpr_runtime.domain.analysis_options import AnalysisOptions
from traffic_lpr_runtime.domain.enums import DecisionSource, EvidenceReason
from traffic_lpr_runtime.domain.models import FrameSample, PlateCandidate

def _request_run_id(payload: dict[str, Any]) -> str | None:
    value = payload.get('requestId')
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _build_sample_selection_payload(sample: FrameSample, tracked_frame: TrackedRegion) -> dict[str, Any]:
    reasons = [
        reason
        for reason in ((tracked_frame.diagnostics or {}).get('evidenceReasons') or [])
        if isinstance(reason, str)
    ]
    if sample.quality is not None and sample.quality.sharpness >= 0.72 and EvidenceReason.SHARPNESS_PEAK.value not in reasons:
        reasons.append(EvidenceReason.SHARPNESS_PEAK.value)
    return {
        'selected': True,
        'priority': float((tracked_frame.diagnostics or {}).get('evidencePriority') or sample.quality.overall_score if sample.quality is not None else 0.0),
        'reasons': reasons,
    }


def _decision_source_for_candidate(candidate: PlateCandidate, sample: FrameSample | None) -> str:
    if candidate.source.startswith('fused-image:'):
        return DecisionSource.FUSED_IMAGE.value
    if candidate.source == 'fused-char':
        return DecisionSource.FUSED_CHAR.value
    if candidate.source == 'legacy-vote':
        return DecisionSource.LEGACY_VOTE.value
    if sample is not None and sample.ocr_input is not None and sample.ocr_input.get('stage') == 'temporal-restored':
        return DecisionSource.TEMPORAL_RESTORED.value
    if (candidate.diagnostics or {}).get('bestFrameCarryThrough') is True:
        return DecisionSource.SUPPORT_CARRY.value
    return DecisionSource.SINGLE_FRAME.value


def _build_decision_trace(
    candidates: list[PlateCandidate],
    accepted_candidate_id: str | None,
    selection_diagnostics: dict[str, Any],
    samples: list[FrameSample],
    sequence_summary: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    candidate_id = accepted_candidate_id or selection_diagnostics.get('suggestedCandidateId')
    chosen_candidate = next((candidate for candidate in candidates if candidate.id == candidate_id), candidates[0] if candidates else None)
    if chosen_candidate is None:
        return None

    chosen_sample = None
    if chosen_candidate.frame_time_ms is not None:
        chosen_sample = next((sample for sample in samples if sample.time_ms == chosen_candidate.frame_time_ms), None)
    if chosen_sample is None:
        chosen_sample = next(
            (
                sample
                for sample in samples
                if any(candidate.id == chosen_candidate.id or candidate.text == chosen_candidate.text for candidate in sample.candidates)
            ),
            None,
        )

    support_frame_count = 1
    if chosen_sample is not None and chosen_sample.temporal_support is not None:
        support_frame_count = int(chosen_sample.temporal_support.get('supportFrameCount') or support_frame_count)
    else:
        support_frame_count = int((chosen_candidate.diagnostics or {}).get('supportFrameCount') or support_frame_count)

    agreement_ratio = (chosen_candidate.diagnostics or {}).get('sequenceSupportRatio')
    if agreement_ratio is None and sequence_summary:
        agreement_ratio = sequence_summary.get('persistenceRatio')

    stage = None
    if chosen_sample is not None and chosen_sample.ocr_input is not None:
        stage = chosen_sample.ocr_input.get('stage')

    return {
        'source': _decision_source_for_candidate(chosen_candidate, chosen_sample),
        'candidateId': chosen_candidate.id,
        'sampleId': chosen_sample.id if chosen_sample is not None else None,
        'frameTimeMs': chosen_candidate.frame_time_ms,
        'stage': stage,
        'supportFrameCount': support_frame_count,
        'agreementRatio': float(agreement_ratio) if isinstance(agreement_ratio, (int, float)) else None,
        'margin': float(selection_diagnostics.get('acceptedMargin')) if isinstance(selection_diagnostics.get('acceptedMargin'), (int, float)) else None,
    }


def _sequence_hard_review_reasons(sequence_summary: dict[str, Any], options: AnalysisOptions) -> list[str]:
    if not sequence_summary or options.sequence_review_mode == 'off':
        return []

    support_frame_count = _safe_int(sequence_summary.get('supportFrameCount'))
    reasons: list[str] = []

    if support_frame_count < options.min_interval_support_frames:
        reasons.append('too few interval samples produced readable plate support')

    return _merge_reasons([], reasons)


def _sequence_advisory_reasons(sequence_summary: dict[str, Any], options: AnalysisOptions) -> list[str]:
    if not sequence_summary or options.sequence_review_mode == 'off':
        return []

    sequence_tier = str(sequence_summary.get('sequenceTier') or 'fragmented')
    persistence_ratio = float(sequence_summary.get('persistenceRatio') or 0.0)
    gap_count = _safe_int(sequence_summary.get('supportFrameGapCount'))
    reasons: list[str] = []

    if sequence_tier == 'fragmented':
        reasons.append('sequence evidence stayed fragmented across the interval')
    if persistence_ratio < options.min_sequence_persistence:
        reasons.append('plate text did not remain stable across interval samples')
    if gap_count > options.max_sequence_gap_count:
        reasons.append('readable OCR evidence had large gaps across the interval')
    if options.sequence_review_mode == 'strict' and sequence_tier in {'drifting', 'gapped'}:
        reasons.append('sequence evidence drifted during the interval review path')
    elif options.sequence_review_mode == 'balanced' and sequence_tier == 'gapped':
        reasons.append('sequence evidence lost continuity across the interval')

    return _merge_reasons([], reasons)


def _merge_reasons(existing: list[str], additions: list[str]) -> list[str]:
    merged: list[str] = []
    for reason in [*existing, *additions]:
        if reason and reason not in merged:
            merged.append(reason)
    return merged


