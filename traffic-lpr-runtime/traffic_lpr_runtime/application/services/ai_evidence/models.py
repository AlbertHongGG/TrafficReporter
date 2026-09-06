from __future__ import annotations

import base64
import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from traffic_lpr_runtime.application.ai_provider import VisionChatImage, VisionLlmProvider
from traffic_lpr_runtime.application.prompt_catalog import load_ai_evidence_prompt_catalog
from traffic_lpr_runtime.domain.errors import RuntimeFailure
from traffic_lpr_runtime.domain.models import TrackedRegion
from traffic_lpr_runtime.domain.value_objects import NormalizedRect, crop_image
from traffic_lpr_runtime.infrastructure.runtime_layout import build_run_id, run_child
from traffic_lpr_runtime.infrastructure.runtime_settings import get_runtime_settings
from traffic_lpr_runtime.protocol import emit_runtime_progress


AI_EVIDENCE_WORKFLOW_STEP_COUNT = 11
MIN_DISTINCT_STORYBOARD_GAP_MS = 80


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _format_time_label(time_ms: int) -> str:
    seconds = max(0, int(round(time_ms / 1000.0)))
    minutes = seconds // 60
    remaining_seconds = seconds % 60
    return f'{minutes:02d}:{remaining_seconds:02d}'


def _normalize_plate(value: str) -> str:
    from traffic_lpr_runtime.domain.text import normalize_plate_text
    return normalize_plate_text(value).upper()


def _float_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve_plate_candidate(candidates: Sequence[dict[str, Any]], candidate_id: str | None) -> dict[str, Any] | None:
    if not candidates:
        return None
    if candidate_id:
        for candidate in candidates:
            if candidate.get('id') == candidate_id:
                return candidate
    return candidates[0]


def _candidate_evidence_payload(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not candidate:
        return None
    return {
        'text': candidate.get('text'),
        'confidence': candidate.get('confidence'),
        'source': candidate.get('source'),
    }


@dataclass(frozen=True, slots=True)



class AiEvidenceProgressStep:
    key: str
    stage: str
    detail: str
    tool_label: str | None
    progress_kind: str
    step_index: int
    stage_step_index: int
    stage_step_count: int

    @property
    def progress(self) -> float:
        if AI_EVIDENCE_WORKFLOW_STEP_COUNT <= 1:
            return 1.0
        return max(0.0, min(1.0, (self.step_index - 1) / (AI_EVIDENCE_WORKFLOW_STEP_COUNT - 1)))


AI_EVIDENCE_PROGRESS_STEPS: OrderedDict[str, AiEvidenceProgressStep] = OrderedDict(
    (
        ('prepare', AiEvidenceProgressStep('prepare', 'prepare', 'Preparing AI evidence workflow.', None, 'host-step', 1, 1, 1)),
        ('build-coarse-storyboard', AiEvidenceProgressStep('build-coarse-storyboard', 'localize', 'Rendering coarse storyboard.', 'Render coarse storyboard', 'tool-call', 2, 1, 4)),
        ('llm-localize-coarse-interval', AiEvidenceProgressStep('llm-localize-coarse-interval', 'localize', 'Selecting coarse interval with AI.', 'AI coarse interval', 'tool-call', 3, 2, 4)),
        ('build-fine-storyboard', AiEvidenceProgressStep('build-fine-storyboard', 'localize', 'Rendering fine storyboard around the candidate interval.', 'Render fine storyboard', 'tool-call', 4, 3, 4)),
        ('llm-select-keyframes', AiEvidenceProgressStep('llm-select-keyframes', 'localize', 'Selecting anchor and keyframes with AI.', 'AI keyframe selection', 'tool-call', 5, 4, 4)),
        ('scan-target-candidates', AiEvidenceProgressStep('scan-target-candidates', 'resolve-target', 'Scanning anchor targets and OCR evidence.', 'Scan target candidates', 'tool-call', 6, 1, 2)),
        ('llm-resolve-target', AiEvidenceProgressStep('llm-resolve-target', 'resolve-target', 'Resolving the described target with AI.', 'AI target resolver', 'tool-call', 7, 2, 2)),
        ('analyze-interval', AiEvidenceProgressStep('analyze-interval', 'range-analysis', 'Running plate range analysis on the resolved interval.', 'Range analysis', 'tool-call', 8, 1, 1)),
        ('render-keyframes', AiEvidenceProgressStep('render-keyframes', 'render', 'Rendering evidence keyframes.', 'Render keyframes', 'tool-call', 9, 1, 1)),
        ('export-clip', AiEvidenceProgressStep('export-clip', 'export-clip', 'Exporting resolved AI evidence clip.', None, 'host-step', 10, 1, 1)),
        ('completed', AiEvidenceProgressStep('completed', 'completed', 'AI evidence workflow completed.', None, 'host-step', 11, 1, 1)),
        ('failed', AiEvidenceProgressStep('failed', 'failed', 'AI evidence workflow failed.', None, 'host-step', 11, 1, 1)),
    )
)


def _progress_for_step(step_key: str) -> AiEvidenceProgressStep:
    try:
        return AI_EVIDENCE_PROGRESS_STEPS[step_key]
    except KeyError as error:
        raise RuntimeFailure(f'Unknown AI evidence progress step: {step_key}') from error


@dataclass(slots=True)
class RenderedFrame:
    frame_id: str
    time_ms: int
    sequence_index: int
    label: str
    image_path: str
    frame_width: int
    frame_height: int

    def to_payload(self, *, image_path: str | None = None) -> dict[str, Any]:
        return {
            'frameId': self.frame_id,
            'timeMs': self.time_ms,
            'sequenceIndex': self.sequence_index,
            'label': self.label,
            'imagePath': image_path or self.image_path,
            'frameWidth': self.frame_width,
            'frameHeight': self.frame_height,
        }


@dataclass(frozen=True, slots=True)
class SelectedKeyframe:
    frame: RenderedFrame
    description: str
    keyframe_source: str = 'llm-selected'
    description_source: str = 'llm'
    is_user_facing: bool = True
    supplement_reason: str | None = None


@dataclass(frozen=True, slots=True)
class StoryboardSelection:
    start_frame: RenderedFrame
    end_frame: RenderedFrame
    anchor_frame: RenderedFrame
    summary: str
    keyframes: Sequence[SelectedKeyframe] = field(default_factory=tuple)
    keyframe_count_reason: str | None = None


@dataclass(frozen=True, slots=True)
class TargetCandidateEvidence:
    track_id: str
    label: str
    class_name: str
    detection_confidence: float
    normalized_box: dict[str, Any]
    selected_box: dict[str, Any] | None
    accepted_candidate_id: str | None
    candidates: Sequence[dict[str, Any]]
    crop_image_path: str
    crop_frame_width: int
    crop_frame_height: int
    detection_diagnostics: dict[str, Any] | None = None

    @property
    def top_candidate(self) -> dict[str, Any] | None:
        return _resolve_plate_candidate(self.candidates, self.accepted_candidate_id)

    @property
    def top_plate_text(self) -> str | None:
        top_candidate = self.top_candidate
        return _optional_string(top_candidate.get('text')) if isinstance(top_candidate, dict) else None

    @property
    def top_plate_confidence(self) -> float | None:
        top_candidate = self.top_candidate
        if not isinstance(top_candidate, dict):
            return None
        return _float_value(top_candidate.get('confidence'))

    def matching_candidate(self, plate_hint: str | None) -> dict[str, Any] | None:
        if not plate_hint:
            return None
        for candidate in self.candidates:
            candidate_text = _optional_string(candidate.get('text'))
            if candidate_text and _normalize_plate(candidate_text) == plate_hint:
                return candidate
        return None

    def has_candidate(self, candidate_id: str | None) -> bool:
        if not candidate_id:
            return False
        return any(_optional_string(candidate.get('id')) == candidate_id for candidate in self.candidates)

    def resolve_selected_candidate_id(self, candidate_id: str | None) -> str | None:
        if self.has_candidate(candidate_id):
            return candidate_id
        if self.accepted_candidate_id:
            return self.accepted_candidate_id
        top_candidate = self.top_candidate
        return _optional_string(top_candidate.get('id')) if isinstance(top_candidate, dict) else None

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            'trackId': self.track_id,
            'label': self.label,
            'imageFrameId': self.track_id,
            'className': self.class_name,
            'detectionConfidence': self.detection_confidence,
            'acceptedCandidateId': self.accepted_candidate_id,
            'acceptedPlate': _candidate_evidence_payload(self.top_candidate),
            'ocrCandidates': [_candidate_evidence_payload(candidate) for candidate in self.candidates[:3]],
        }


@dataclass(frozen=True, slots=True)
class PlateHintMatchEvidence:
    candidate_evidence: TargetCandidateEvidence
    candidate: dict[str, Any]

    def sort_key(self) -> tuple[float, float]:
        return (
            _float_value(self.candidate.get('confidence')) or 0.0,
            self.candidate_evidence.detection_confidence,
        )

    def matched_text(self, fallback: str | None) -> str:
        return _optional_string(self.candidate.get('text')) or fallback or '目標車牌'

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            'trackId': self.candidate_evidence.track_id,
            'candidate': _candidate_evidence_payload(self.candidate),
        }


@dataclass(frozen=True, slots=True)
class TargetResolutionEvidence:
    description: str
    anchor_frame: RenderedFrame
    plate_hint: str | None
    candidates: Sequence[TargetCandidateEvidence]
    exact_plate_hint_matches: Sequence[PlateHintMatchEvidence] = field(default_factory=tuple)

    @property
    def primary_exact_plate_hint_match(self) -> PlateHintMatchEvidence | None:
        return self.exact_plate_hint_matches[0] if self.exact_plate_hint_matches else None

    def find_candidate(self, track_id: str | None) -> TargetCandidateEvidence | None:
        if not track_id:
            return None
        return next((candidate for candidate in self.candidates if candidate.track_id == track_id), None)

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            'description': self.description,
            'anchorFrame': {
                'frameId': self.anchor_frame.frame_id,
                'timeMs': self.anchor_frame.time_ms,
                'timeLabel': _format_time_label(self.anchor_frame.time_ms),
            },
            'plateHint': self.plate_hint,
            'policy': {
                'plateHintPriority': 'strong-prior',
                'allowOverrideWhenVisualEvidenceContradicts': True,
                'allowedTrackIds': [candidate.track_id for candidate in self.candidates],
            },
            'targets': [candidate.to_prompt_payload() for candidate in self.candidates],
            'exactPlateHintMatches': [match.to_prompt_payload() for match in self.exact_plate_hint_matches],
        }


@dataclass(frozen=True, slots=True)
class AiEvidenceRuntimeBridge:
    detect_targets: Callable[[Any, int, str, NormalizedRect | None], list[TrackedRegion]]
    analyze_frame: Callable[[dict[str, Any]], dict[str, Any]]
    analyze_interval: Callable[[dict[str, Any]], dict[str, Any]]


