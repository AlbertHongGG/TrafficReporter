from __future__ import annotations

from enum import Enum
from typing import Any


class AnalysisProfileId(str, Enum):
    BALANCED = 'balanced'
    PRECISION = 'precision'
    RECOVERY = 'recovery'


DEFAULT_ANALYSIS_PROFILE_ID = AnalysisProfileId.PRECISION.value


class AnalysisProfileCatalog:
    """Pure domain in-memory registry of standardized LPR analysis profile options."""

    _PROFILE_OPTIONS: dict[str, dict[str, Any]] = {
        AnalysisProfileId.BALANCED.value: {
            'trackerMode': 'botsort',
            'fusionMode': 'aligned-char',
            'restorationMode': 'mambairv2',
            'recognizerBackend': 'hybrid',
            'temporalEvidenceMode': 'scheduled',
            'sequenceReviewMode': 'balanced',
            'temporalWindowMs': 220,
            'temporalNeighborCount': 5,
            'maxEvidenceSampleCount': 12,
            'anchorBurstCount': 4,
            'enableRectification': True,
            'enableEnhancement': True,
            'enableRecognizerComparison': True,
            'maxPlateCandidates': 3,
            'trackerHighConfidence': 0.35,
            'trackerLowConfidence': 0.15,
            'maxTrackingGap': 3,
            'minAlignmentScore': 0.05,
            'enableReliabilityGates': True,
            'minAcceptedConfidence': 0.62,
            'minCandidateMargin': 0.08,
            'minIntervalSupportFrames': 2,
            'minSequencePersistence': 0.55,
            'maxSequenceGapCount': 1,
        },
        AnalysisProfileId.PRECISION.value: {
            'recognizerBackend': 'hybrid',
            'temporalEvidenceMode': 'motion-aware',
            'sequenceReviewMode': 'strict',
            'temporalWindowMs': 260,
            'temporalNeighborCount': 5,
            'maxEvidenceSampleCount': 14,
            'anchorBurstCount': 5,
            'maxPlateCandidates': 3,
            'trackerHighConfidence': 0.4,
            'trackerLowConfidence': 0.18,
            'minAcceptedConfidence': 0.72,
            'minCandidateMargin': 0.12,
            'minIntervalSupportFrames': 3,
            'minSequencePersistence': 0.72,
            'maxSequenceGapCount': 0,
        },
        AnalysisProfileId.RECOVERY.value: {
            'recognizerBackend': 'hybrid',
            'temporalEvidenceMode': 'motion-aware',
            'sequenceReviewMode': 'relaxed',
            'temporalWindowMs': 340,
            'temporalNeighborCount': 7,
            'maxEvidenceSampleCount': 18,
            'anchorBurstCount': 6,
            'maxPlateCandidates': 4,
            'trackerLowConfidence': 0.12,
            'maxTrackingGap': 4,
            'minAcceptedConfidence': 0.52,
            'minCandidateMargin': 0.03,
            'minIntervalSupportFrames': 1,
            'minSequencePersistence': 0.4,
            'maxSequenceGapCount': 2,
        },
    }

    _DEVELOPER_DIAGNOSTICS_OPTIONS: dict[str, Any] = {
        'persistArtifacts': True,
        'debugTag': 'developer-diagnostics',
        'maxPlateCandidates': 5,
    }

    @classmethod
    def available_profile_ids(cls) -> list[str]:
        return list(cls._PROFILE_OPTIONS.keys())

    @classmethod
    def resolve_profile_options(
        cls,
        profile_id: str | None,
        enable_developer_diagnostics: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        resolved_id = (
            profile_id
            if profile_id and profile_id in cls._PROFILE_OPTIONS
            else DEFAULT_ANALYSIS_PROFILE_ID
        )
        options = dict(cls._PROFILE_OPTIONS[resolved_id])
        if enable_developer_diagnostics:
            options.update(cls._DEVELOPER_DIAGNOSTICS_OPTIONS)
        return resolved_id, options
