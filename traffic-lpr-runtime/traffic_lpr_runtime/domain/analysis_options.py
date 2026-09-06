from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from traffic_lpr_runtime.application.analysis_profiles import resolve_analysis_profile_options
from traffic_lpr_runtime.infrastructure.runtime_layout import build_run_id, run_child


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
    def from_payload(cls, payload: dict[str, Any] | None) -> 'AnalysisOptions':
        request_payload = payload or {}
        developer_diagnostics_enabled = request_payload.get('enableDeveloperDiagnostics') is True
        analysis_profile_id, profile_options = resolve_analysis_profile_options(
            _to_optional_str(request_payload.get('analysisProfileId')),
            developer_diagnostics_enabled,
        )
        raw = {
            **profile_options,
            **dict(request_payload.get('analysisOptions') or {}),
        }
        persist_artifacts = bool(raw.get('persistArtifacts') or False) and developer_diagnostics_enabled
        return cls(
            analysis_profile_id=analysis_profile_id,
            enable_developer_diagnostics=developer_diagnostics_enabled,
            persist_artifacts=persist_artifacts,
            artifact_dir=_to_optional_str(raw.get('artifactDir')),
            tracker_mode=_to_optional_str(raw.get('trackerMode')) or 'botsort',
            fusion_mode=_to_optional_str(raw.get('fusionMode')) or 'aligned-char',
            restoration_mode=_to_optional_str(raw.get('restorationMode')) or 'mambairv2',
            recognizer_backend=_to_optional_str(raw.get('recognizerBackend')) or 'hybrid',
            temporal_evidence_mode=_to_optional_str(raw.get('temporalEvidenceMode')) or 'motion-aware',
            sequence_review_mode=_to_optional_str(raw.get('sequenceReviewMode')) or 'balanced',
            enable_rectification=raw.get('enableRectification', True) is not False,
            enable_enhancement=raw.get('enableEnhancement', True) is not False,
            enable_recognizer_comparison=raw.get('enableRecognizerComparison', True) is not False,
            debug_tag=_to_optional_str(raw.get('debugTag')),
            ocr_model_names=[str(name) for name in (raw.get('ocrModelNames') or DEFAULT_OCR_MODEL_NAMES)],
            max_plate_candidates=max(1, min(int(raw.get('maxPlateCandidates') or 3), 6)),
            tracker_high_confidence=float(raw.get('trackerHighConfidence') or 0.35),
            tracker_low_confidence=float(raw.get('trackerLowConfidence') or 0.15),
            max_tracking_gap=max(1, min(int(raw.get('maxTrackingGap') or 3), 8)),
            min_alignment_score=float(raw.get('minAlignmentScore') or 0.05),
            enable_reliability_gates=raw.get('enableReliabilityGates', True) is not False,
            min_accepted_confidence=float(raw.get('minAcceptedConfidence') or 0.62),
            min_candidate_margin=float(raw.get('minCandidateMargin') or 0.08),
            min_interval_support_frames=max(1, min(int(raw.get('minIntervalSupportFrames') or 2), 8)),
            min_sequence_persistence=max(
                0.0,
                min(
                    float(0.55 if raw.get('minSequencePersistence') is None else raw.get('minSequencePersistence')),
                    1.0,
                ),
            ),
            max_sequence_gap_count=max(
                0,
                min(
                    int(1 if raw.get('maxSequenceGapCount') is None else raw.get('maxSequenceGapCount')),
                    8,
                ),
            ),
            temporal_window_ms=max(80, min(int(raw.get('temporalWindowMs') or 240), 1200)),
            temporal_neighbor_count=max(1, min(int(raw.get('temporalNeighborCount') or 5), 9)),
            max_evidence_sample_count=max(4, min(int(raw.get('maxEvidenceSampleCount') or 12), 24)),
            anchor_burst_count=max(1, min(int(raw.get('anchorBurstCount') or 4), 8)),
        )

    def resolve_artifact_root(self, runtime_root: Path, suffix: str | None = None, run_id: str | None = None) -> Path | None:
        if not self.persist_artifacts:
            return None
        if self.artifact_dir:
            root = Path(self.artifact_dir)
        else:
            resolved_run_id = run_id or build_run_id()
            root = run_child(runtime_root, resolved_run_id, 'analysis')
            if self.debug_tag:
                root = root / self.debug_tag
        if suffix:
            root = root / suffix
        root.mkdir(parents=True, exist_ok=True)
        return root

    def ocr_models(self) -> list[str]:
        return self.ocr_model_names if self.enable_recognizer_comparison else self.ocr_model_names[:1]

    def for_interactive_frame(self) -> 'AnalysisOptions':
        return replace(
            self,
            enable_recognizer_comparison=False,
            enable_secondary_subcrop_ocr=True,
            restoration_mode='off',
            persist_artifacts=False,
            temporal_window_ms=0,
            temporal_neighbor_count=1,
        )

    def for_interval_sample(self, sample_count_hint: int | None = None) -> 'AnalysisOptions':
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
