from __future__ import annotations

from typing import Any

from traffic_lpr_runtime.domain.models import PlateCandidate


def build_review_state(
    candidates: list[PlateCandidate],
    accepted_candidate_id: str | None,
    selection_diagnostics: dict[str, Any] | None,
) -> dict[str, Any]:
    selection = selection_diagnostics or {}
    suggested_candidate_id = _string_value(selection.get('suggestedCandidateId')) or (
        candidates[0].id if candidates else None
    )
    reasons = [value for value in selection.get('reasons') or [] if isinstance(value, str)]
    accepted_candidate_id = accepted_candidate_id or _string_value(selection.get('acceptedCandidateId'))
    review_required = bool(selection.get('reviewRequired'))

    if not candidates:
        if not reasons:
            reasons = ['no-candidate']
        status = 'no-candidate'
    elif review_required:
        status = 'review-required'
    else:
        status = 'accepted'

    return {
        'status': status,
        'acceptedCandidateId': accepted_candidate_id,
        'suggestedCandidateId': suggested_candidate_id,
        'reasons': reasons,
    }


def _string_value(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
