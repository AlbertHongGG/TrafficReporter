from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .value_objects import NormalizedRect


@dataclass(slots=True)
class RuntimeStatus:
    available: bool
    python_executable: str | None
    runtime_script: str | None
    version: str | None
    missing_packages: list[str]
    installed_packages: list[str]
    detail: str

    def to_payload(self) -> dict[str, Any]:
        return {
            'available': self.available,
            'pythonExecutable': self.python_executable,
            'runtimeScript': self.runtime_script,
            'version': self.version,
            'missingPackages': self.missing_packages,
            'installedPackages': self.installed_packages,
            'detail': self.detail,
        }


@dataclass(slots=True)
class QualityMetrics:
    sharpness: float
    contrast: float
    plate_area: float
    angle_score: float
    occlusion_score: float
    glare_score: float
    legibility_score: float
    overall_score: float
    legibility_level: str

    def to_payload(self) -> dict[str, Any]:
        return {
            'sharpness': self.sharpness,
            'contrast': self.contrast,
            'plateArea': self.plate_area,
            'angleScore': self.angle_score,
            'occlusionScore': self.occlusion_score,
            'glareScore': self.glare_score,
            'legibilityScore': self.legibility_score,
            'overallScore': self.overall_score,
            'legibilityLevel': self.legibility_level,
        }


@dataclass(slots=True)
class TrackedRegion:
    id: str
    time_ms: int
    box: NormalizedRect
    confidence: float
    class_name: str
    diagnostics: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'timeMs': self.time_ms,
            'box': self.box.to_payload(),
            'confidence': self.confidence,
            'className': self.class_name,
            'diagnostics': self.diagnostics,
        }


@dataclass(slots=True)
class TargetTrack:
    id: str
    class_name: str
    label: str
    confidence: float
    frames: list[TrackedRegion]
    diagnostics: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'className': self.class_name,
            'label': self.label,
            'confidence': self.confidence,
            'frames': [frame.to_payload() for frame in self.frames],
            'diagnostics': self.diagnostics,
        }


@dataclass(slots=True)
class PlateCandidate:
    id: str
    text: str
    confidence: float
    source: str
    frame_time_ms: int | None
    country_code: str | None
    box: NormalizedRect | None
    quality: QualityMetrics | None
    diagnostics: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'text': self.text,
            'confidence': self.confidence,
            'source': self.source,
            'frameTimeMs': self.frame_time_ms,
            'countryCode': self.country_code,
            'box': self.box.to_payload() if self.box else None,
            'quality': self.quality.to_payload() if self.quality else None,
            'diagnostics': self.diagnostics,
        }


@dataclass(slots=True)
class FrameSample:
    id: str
    time_ms: int
    target_box: NormalizedRect | None
    plate_box: NormalizedRect | None
    quality: QualityMetrics | None
    candidates: list[PlateCandidate]
    image_path: str | None
    selection: dict[str, Any] | None = None
    ocr_input: dict[str, Any] | None = None
    temporal_support: dict[str, Any] | None = None
    diagnostics: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'timeMs': self.time_ms,
            'targetBox': self.target_box.to_payload() if self.target_box else None,
            'plateBox': self.plate_box.to_payload() if self.plate_box else None,
            'quality': self.quality.to_payload() if self.quality else None,
            'candidates': [candidate.to_payload() for candidate in self.candidates],
            'imagePath': self.image_path,
            'selection': self.selection,
            'ocrInput': self.ocr_input,
            'temporalSupport': self.temporal_support,
            'diagnostics': self.diagnostics,
        }


@dataclass(slots=True)
class AnalysisProvenance:
    command: str
    request_id: str | None = None
    analysis_profile_id: str | None = None
    developer_diagnostics_enabled: bool = False
    runtime_version: str | None = None
    restoration_mode: str | None = None
    recognizer_backend: str | None = None
    temporal_evidence_mode: str | None = None
    sequence_review_mode: str | None = None
    emitted_at_ms: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {
            'requestId': self.request_id,
            'command': self.command,
            'analysisProfileId': self.analysis_profile_id,
            'developerDiagnosticsEnabled': self.developer_diagnostics_enabled,
            'runtimeVersion': self.runtime_version,
            'restorationMode': self.restoration_mode,
            'recognizerBackend': self.recognizer_backend,
            'temporalEvidenceMode': self.temporal_evidence_mode,
            'sequenceReviewMode': self.sequence_review_mode,
            'emittedAtMs': self.emitted_at_ms,
        }

    @classmethod
    def create(
        cls,
        command: str,
        payload: dict[str, Any],
        runtime_status: dict[str, Any],
        analysis_options: dict[str, Any] | None = None,
    ) -> AnalysisProvenance:
        resolved_options = dict(analysis_options or payload.get('analysisOptions') or {})

        def _str(val: Any) -> str | None:
            return val if isinstance(val, str) and val else None

        return cls(
            command=command,
            request_id=_str(payload.get('requestId')),
            analysis_profile_id=_str(payload.get('analysisProfileId')),
            developer_diagnostics_enabled=bool(payload.get('enableDeveloperDiagnostics')),
            runtime_version=_str(runtime_status.get('version')),
            restoration_mode=_str(resolved_options.get('restorationMode')),
            recognizer_backend=_str(resolved_options.get('recognizerBackend')),
            temporal_evidence_mode=_str(resolved_options.get('temporalEvidenceMode')),
            sequence_review_mode=_str(resolved_options.get('sequenceReviewMode')),
            emitted_at_ms=time.time_ns() // 1_000_000,
        )


@dataclass(slots=True)
class ReviewState:
    status: str
    accepted_candidate_id: str | None = None
    suggested_candidate_id: str | None = None
    reasons: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            'status': self.status,
            'acceptedCandidateId': self.accepted_candidate_id,
            'suggestedCandidateId': self.suggested_candidate_id,
            'reasons': self.reasons,
        }

    @classmethod
    def evaluate(
        cls,
        candidates: list[PlateCandidate],
        accepted_candidate_id: str | None = None,
        selection_diagnostics: dict[str, Any] | None = None,
    ) -> ReviewState:
        selection = selection_diagnostics or {}

        def _str(val: Any) -> str | None:
            return val if isinstance(val, str) and val else None

        suggested_candidate_id = _str(selection.get('suggestedCandidateId')) or (
            candidates[0].id if candidates else None
        )
        reasons = [value for value in selection.get('reasons') or [] if isinstance(value, str)]
        resolved_accepted_id = accepted_candidate_id or _str(selection.get('acceptedCandidateId'))
        review_required = bool(selection.get('reviewRequired'))

        if not candidates:
            if not reasons:
                reasons = ['no-candidate']
            status = 'no-candidate'
        elif review_required:
            status = 'review-required'
        else:
            status = 'accepted'

        return cls(
            status=status,
            accepted_candidate_id=resolved_accepted_id,
            suggested_candidate_id=suggested_candidate_id,
            reasons=reasons,
        )


@dataclass(frozen=True, slots=True)
class StageTiming:
    tracking_ms: float
    sample_analysis_ms: float
    temporal_support_ms: float
    fusion_ms: float
    total_ms: float
    temporal_support_budget: int
    temporal_support_samples_used: int

    def to_payload(self) -> dict[str, float | int]:
        return {
            'trackingMs': self.tracking_ms,
            'sampleAnalysisMs': self.sample_analysis_ms,
            'temporalSupportMs': self.temporal_support_ms,
            'fusionMs': self.fusion_ms,
            'totalMs': self.total_ms,
            'temporalSupportBudget': self.temporal_support_budget,
            'temporalSupportSamplesUsed': self.temporal_support_samples_used,
        }


RuntimeStageTiming = StageTiming


@dataclass(frozen=True, slots=True)
class AnalysisDiagnostics:
    analysis_options: dict[str, Any]
    analysis_policy: Any
    artifact_root: str | None
    tracker: dict[str, Any]
    tracking_summary: dict[str, Any]
    sequence: dict[str, Any]
    fusion: dict[str, Any]
    selection: dict[str, Any]
    timing: StageTiming

    def to_payload(self) -> dict[str, Any]:
        policy_payload = (
            self.analysis_policy.to_payload()
            if hasattr(self.analysis_policy, 'to_payload')
            else self.analysis_policy
        )
        return {
            'analysisOptions': self.analysis_options,
            'analysisPolicy': policy_payload,
            'artifactRoot': self.artifact_root,
            'tracker': self.tracker,
            'trackingSummary': self.tracking_summary,
            'sequence': self.sequence,
            'fusion': self.fusion,
            'selection': self.selection,
            'timing': self.timing.to_payload(),
        }


IntervalAnalysisDiagnostics = AnalysisDiagnostics

