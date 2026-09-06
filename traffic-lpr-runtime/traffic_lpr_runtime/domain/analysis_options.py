from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

DEFAULT_OCR_MODEL_NAMES = [
    'cct-xs-v2-global-model',
    'cct-s-v2-global-model',
    'global-plates-mobile-vit-v2-model',
]


def _to_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized if normalized else None


@dataclass(slots=True)
class AnalysisOptions:
    """Pure domain entity representing license plate recognition analysis configuration."""

    analysis_profile_id: str = 'precision'
    enable_developer_diagnostics: bool = False
    persist_artifacts: bool = False
    artifact_dir: str | None = None
    tracker_mode: str = 'botsort'
    fusion_mode: str = 'aligned-char'
    restoration_mode: str = 'mambairv2'
    recognizer_backend: str = 'hybrid'
    temporal_evidence_mode: str = 'motion-aware'
    sequence_review_mode: str = 'balanced'
    enable_rectification: bool = True
    enable_enhancement: bool = True
    enable_recognizer_comparison: bool = True
    enable_secondary_subcrop_ocr: bool = False
    debug_tag: str | None = None
    ocr_model_names: list[str] = field(default_factory=lambda: list(DEFAULT_OCR_MODEL_NAMES))
    max_plate_candidates: int = 3
    tracker_high_confidence: float = 0.35
    tracker_low_confidence: float = 0.15
    max_tracking_gap: int = 3
    min_alignment_score: float = 0.05
    enable_reliability_gates: bool = True
    min_accepted_confidence: float = 0.62
    min_candidate_margin: float = 0.08
    min_interval_support_frames: int = 2
    min_sequence_persistence: float = 0.55
    max_sequence_gap_count: int = 1
    temporal_window_ms: int = 240
    temporal_neighbor_count: int = 5
    max_evidence_sample_count: int = 12
    anchor_burst_count: int = 4

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> AnalysisOptions:
        data = raw or {}
        persist_artifacts = bool(data.get('persistArtifacts') or False)
        return cls(
            analysis_profile_id=_to_optional_str(data.get('analysisProfileId')) or 'precision',
            enable_developer_diagnostics=bool(data.get('enableDeveloperDiagnostics')),
            persist_artifacts=persist_artifacts,
            artifact_dir=_to_optional_str(data.get('artifactDir')),
            tracker_mode=_to_optional_str(data.get('trackerMode')) or 'botsort',
            fusion_mode=_to_optional_str(data.get('fusionMode')) or 'aligned-char',
            restoration_mode=_to_optional_str(data.get('restorationMode')) or 'mambairv2',
            recognizer_backend=_to_optional_str(data.get('recognizerBackend')) or 'hybrid',
            temporal_evidence_mode=_to_optional_str(data.get('temporalEvidenceMode')) or 'motion-aware',
            sequence_review_mode=_to_optional_str(data.get('sequenceReviewMode')) or 'balanced',
            enable_rectification=data.get('enableRectification', True) is not False,
            enable_enhancement=data.get('enableEnhancement', True) is not False,
            enable_recognizer_comparison=data.get('enableRecognizerComparison', True) is not False,
            debug_tag=_to_optional_str(data.get('debugTag')),
            ocr_model_names=[str(name) for name in (data.get('ocrModelNames') or DEFAULT_OCR_MODEL_NAMES)],
            max_plate_candidates=max(1, min(int(data.get('maxPlateCandidates') or 3), 6)),
            tracker_high_confidence=float(data.get('trackerHighConfidence') or 0.35),
            tracker_low_confidence=float(data.get('trackerLowConfidence') or 0.15),
            max_tracking_gap=max(1, min(int(data.get('maxTrackingGap') or 3), 8)),
            min_alignment_score=float(data.get('minAlignmentScore') or 0.05),
            enable_reliability_gates=data.get('enableReliabilityGates', True) is not False,
            min_accepted_confidence=float(data.get('minAcceptedConfidence') or 0.62),
            min_candidate_margin=float(data.get('minCandidateMargin') or 0.08),
            min_interval_support_frames=max(1, min(int(data.get('minIntervalSupportFrames') or 2), 8)),
            min_sequence_persistence=max(
                0.0,
                min(
                    float(0.55 if data.get('minSequencePersistence') is None else data.get('minSequencePersistence')),
                    1.0,
                ),
            ),
            max_sequence_gap_count=max(
                0,
                min(
                    int(1 if data.get('maxSequenceGapCount') is None else data.get('maxSequenceGapCount')),
                    8,
                ),
            ),
            temporal_window_ms=max(80, min(int(data.get('temporalWindowMs') or 240), 1200)),
            temporal_neighbor_count=max(1, min(int(data.get('temporalNeighborCount') or 5), 9)),
            max_evidence_sample_count=max(4, min(int(data.get('maxEvidenceSampleCount') or 12), 24)),
            anchor_burst_count=max(1, min(int(data.get('anchorBurstCount') or 4), 8)),
        )

    def ocr_models(self) -> list[str]:
        return self.ocr_model_names if self.enable_recognizer_comparison else self.ocr_model_names[:1]

    def for_interactive_frame(self) -> AnalysisOptions:
        return replace(
            self,
            enable_recognizer_comparison=False,
            enable_secondary_subcrop_ocr=True,
            restoration_mode='off',
            persist_artifacts=False,
            temporal_window_ms=0,
            temporal_neighbor_count=1,
        )

    def for_interval_sample(self, sample_count_hint: int | None = None) -> AnalysisOptions:
        return replace(
            self,
            enable_recognizer_comparison=False,
            enable_secondary_subcrop_ocr=False,
            persist_artifacts=False,
            artifact_dir=None,
            debug_tag=None,
            restoration_mode='off',
            temporal_window_ms=0,
            temporal_neighbor_count=1,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            'analysisProfileId': self.analysis_profile_id,
            'enableDeveloperDiagnostics': self.enable_developer_diagnostics,
            'persistArtifacts': self.persist_artifacts,
            'artifactDir': self.artifact_dir,
            'trackerMode': self.tracker_mode,
            'fusionMode': self.fusion_mode,
            'restorationMode': self.restoration_mode,
            'recognizerBackend': self.recognizer_backend,
            'temporalEvidenceMode': self.temporal_evidence_mode,
            'sequenceReviewMode': self.sequence_review_mode,
            'enableRectification': self.enable_rectification,
            'enableEnhancement': self.enable_enhancement,
            'enableRecognizerComparison': self.enable_recognizer_comparison,
            'debugTag': self.debug_tag,
            'ocrModelNames': self.ocr_model_names,
            'maxPlateCandidates': self.max_plate_candidates,
            'trackerHighConfidence': self.tracker_high_confidence,
            'trackerLowConfidence': self.tracker_low_confidence,
            'maxTrackingGap': self.max_tracking_gap,
            'minAlignmentScore': self.min_alignment_score,
            'enableReliabilityGates': self.enable_reliability_gates,
            'minAcceptedConfidence': self.min_accepted_confidence,
            'minCandidateMargin': self.min_candidate_margin,
            'minIntervalSupportFrames': self.min_interval_support_frames,
            'minSequencePersistence': self.min_sequence_persistence,
            'maxSequenceGapCount': self.max_sequence_gap_count,
            'temporalWindowMs': self.temporal_window_ms,
            'temporalNeighborCount': self.temporal_neighbor_count,
            'maxEvidenceSampleCount': self.max_evidence_sample_count,
            'anchorBurstCount': self.anchor_burst_count,
        }
