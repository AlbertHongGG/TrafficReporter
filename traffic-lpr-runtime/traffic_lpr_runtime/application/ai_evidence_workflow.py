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


class AiEvidenceWorkflow:
    def __init__(
        self,
        *,
        ensure_ready: Callable[[], None],
        status: Callable[[], dict[str, Any]],
        runtime_root: Callable[[], Path],
        dependencies: Any,
        frame_reader: Any,
        runtime_bridge: AiEvidenceRuntimeBridge,
        provider: VisionLlmProvider,
    ) -> None:
        self._ensure_ready = ensure_ready
        self._status = status
        self._runtime_root = runtime_root
        self._dependencies = dependencies
        self._frame_reader = frame_reader
        self._runtime_bridge = runtime_bridge
        self._provider = provider
        self._prompt_catalog = load_ai_evidence_prompt_catalog()

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        settings = get_runtime_settings()
        description = str(payload.get('description') or '').strip()
        if not description:
            raise RuntimeFailure('AI evidence analysis requires a non-empty natural-language description.')

        request_id = _optional_string(payload.get('requestId')) or build_run_id()
        artifact_root = self._resolve_artifact_root(request_id)
        source_path = str(payload['sourcePath'])
        marker_rect = NormalizedRect.from_payload(payload.get('markerRect'))
        duration_ms = self._probe_duration_ms(source_path)
        target_vehicle_kind = str(payload.get('targetVehicleKind') or 'vehicle')
        country_hints = [str(value) for value in (payload.get('countryHints') or []) if str(value).strip()]
        analysis_profile_id = _optional_string(payload.get('analysisProfileId'))
        enable_developer_diagnostics = bool(payload.get('enableDeveloperDiagnostics'))
        max_keyframes = max(8, min(10, int(payload.get('maxKeyframes') or settings.ai_evidence.max_keyframes)))
        coarse_step_ms = max(1000, int(payload.get('coarseSampleEveryMs') or settings.ai_evidence.coarse_sample_every_ms))
        fine_padding_ms = max(1000, int(payload.get('fineWindowPaddingMs') or settings.ai_evidence.fine_window_padding_ms))

        tool_calls: list[dict[str, Any]] = []

        coarse_frames = self._record_tool_call(
            tool_calls,
            request_id=request_id,
            progress_step_key='build-coarse-storyboard',
            stage='localize',
            tool_name='build-coarse-storyboard',
            input_summary=f'durationMs={duration_ms} coarseStepMs={coarse_step_ms}',
            func=lambda: self._render_storyboard_frames(
                source_path=source_path,
                output_dir=artifact_root / 'coarse',
                prefix='coarse',
                times_ms=_sample_times(duration_ms, coarse_step_ms, max_samples=18),
            ),
        )
        coarse_choice = self._record_tool_call(
            tool_calls,
            request_id=request_id,
            progress_step_key='llm-localize-coarse-interval',
            stage='localize',
            tool_name='llm-localize-coarse-interval',
            input_summary=f'frames={len(coarse_frames)} description={description[:96]}',
            func=lambda: self._select_coarse_interval(request_id, description, coarse_frames),
        )

        fine_start_ms = max(0, coarse_choice.start_frame.time_ms - fine_padding_ms)
        fine_end_ms = min(duration_ms, coarse_choice.end_frame.time_ms + fine_padding_ms)
        if fine_end_ms <= fine_start_ms:
            fine_end_ms = min(duration_ms, fine_start_ms + max(fine_padding_ms * 2, 1000))

        fine_step_ms = _resolve_fine_step_ms(
            start_ms=fine_start_ms,
            end_ms=fine_end_ms,
            requested_step_ms=int(payload.get('fineSampleEveryMs') or settings.ai_evidence.fine_sample_every_ms),
            preferred_samples=max_keyframes + 6,
            max_samples=24,
        )
        fine_frames = self._record_tool_call(
            tool_calls,
            request_id=request_id,
            progress_step_key='build-fine-storyboard',
            stage='localize',
            tool_name='build-fine-storyboard',
            input_summary=f'interval={fine_start_ms}-{fine_end_ms} fineStepMs={fine_step_ms}',
            func=lambda: self._render_storyboard_frames(
                source_path=source_path,
                output_dir=artifact_root / 'fine',
                prefix='fine',
                times_ms=_sample_times(fine_end_ms - fine_start_ms, fine_step_ms, max_samples=24, offset_ms=fine_start_ms),
            ),
        )
        fine_choice = self._record_tool_call(
            tool_calls,
            request_id=request_id,
            progress_step_key='llm-select-keyframes',
            stage='localize',
            tool_name='llm-select-keyframes',
            input_summary=f'frames={len(fine_frames)} maxKeyframes={max_keyframes}',
            func=lambda: self._select_fine_interval(request_id, description, fine_frames, max_keyframes),
        )

        planned_interval = {
            'startMs': int(fine_choice.start_frame.time_ms),
            'endMs': int(fine_choice.end_frame.time_ms),
        }
        if planned_interval['endMs'] < planned_interval['startMs']:
            planned_interval = {
                'startMs': planned_interval['endMs'],
                'endMs': planned_interval['startMs'],
            }

        anchor_frame = fine_choice.anchor_frame
        target_resolution = self._resolve_target(
            tool_calls=tool_calls,
            request_id=request_id,
            description=description,
            source_path=source_path,
            marker_rect=marker_rect,
            target_vehicle_kind=target_vehicle_kind,
            country_hints=country_hints,
            analysis_profile_id=analysis_profile_id,
            enable_developer_diagnostics=enable_developer_diagnostics,
            anchor_frame=anchor_frame,
            output_dir=artifact_root / 'target-resolution',
        )

        interval_result = self._record_tool_call(
            tool_calls,
            request_id=request_id,
            progress_step_key='analyze-interval',
            stage='range-analysis',
            tool_name='analyze-interval',
            input_summary=(
                f'interval={planned_interval["startMs"]}-{planned_interval["endMs"]} '
                f'anchor={anchor_frame.time_ms} selectedTarget={target_resolution["selectedBox"] is not None}'
            ),
            func=lambda: self._runtime_bridge.analyze_interval({
                'sourcePath': source_path,
                'interval': planned_interval,
                'anchorTimeMs': anchor_frame.time_ms,
                'targetVehicleKind': target_vehicle_kind,
                'selectedTargetBox': target_resolution['selectedBox']['normalizedBox'] if target_resolution['selectedBox'] else None,
                'selectedTargetTrackId': target_resolution.get('selectedTrackId'),
                'countryHints': country_hints,
                'analysisProfileId': analysis_profile_id,
                'enableDeveloperDiagnostics': enable_developer_diagnostics,
                'analysisIntent': 'ai-evidence-range',
                'latencyBudgetMs': 45_000,
                'requestId': request_id,
            }),
        )

        projection = self._build_projection(interval_result, planned_interval, target_resolution)
        plate_candidate = _resolve_plate_candidate(projection['candidates'], projection['acceptedCandidateId'])
        keyframes = self._record_tool_call(
            tool_calls,
            request_id=request_id,
            progress_step_key='render-keyframes',
            stage='render',
            tool_name='render-keyframes',
            input_summary=f'keyframes={len(fine_choice.keyframes)}',
            func=lambda: self._render_keyframes(
                source_path=source_path,
                keyframe_refs=fine_choice.keyframes,
                analysis_track=projection['analysisTrack'],
                output_dir=artifact_root / 'keyframes',
            ),
        )

        summary = fine_choice.summary or _build_summary(description, planned_interval, plate_candidate)
        keyframe_count_reason = _resolve_keyframe_count_reason(
            rendered_count=len(keyframes),
            desired_count=max_keyframes,
            available_frame_count=len(fine_frames),
            provider_reason=fine_choice.keyframe_count_reason,
        )
        runtime_status = self._status()
        return {
            'requestId': request_id,
            'description': description,
            'summary': summary,
            'provider': self._provider.kind,
            'interval': planned_interval,
            'plateNumber': plate_candidate['text'] if plate_candidate else None,
            'plateCandidate': plate_candidate,
            'primaryAnchor': anchor_frame.to_payload(),
            'targetSelection': target_resolution,
            'keyframes': keyframes,
            'keyframeCountReason': keyframe_count_reason,
            'toolCalls': tool_calls,
            'projection': projection,
            'runtime': runtime_status,
        }

    def _emit_progress(
        self,
        *,
        request_id: str,
        progress: float,
        stage: str,
        detail: str,
        progress_kind: str | None = None,
        tool_name: str | None = None,
        tool_label: str | None = None,
        step_index: int | None = None,
        step_count: int | None = None,
        stage_step_index: int | None = None,
        stage_step_count: int | None = None,
    ) -> None:
        emit_runtime_progress({
            'progress': max(0.0, min(1.0, progress)),
            'stage': stage,
            'detail': detail,
            'progressKind': progress_kind,
            'toolName': tool_name,
            'toolLabel': tool_label,
            'stepIndex': step_index,
            'stepCount': step_count,
            'stageStepIndex': stage_step_index,
            'stageStepCount': stage_step_count,
            'done': False,
            'failed': False,
            'requestId': request_id,
        })

    def _emit_progress_step(self, *, request_id: str, step_key: str) -> None:
        step = _progress_for_step(step_key)
        self._emit_progress(
            request_id=request_id,
            progress=step.progress,
            stage=step.stage,
            detail=step.detail,
            progress_kind=step.progress_kind,
            tool_name=step.key if step.progress_kind == 'tool-call' else None,
            tool_label=step.tool_label,
            step_index=step.step_index,
            step_count=AI_EVIDENCE_WORKFLOW_STEP_COUNT,
            stage_step_index=step.stage_step_index,
            stage_step_count=step.stage_step_count,
        )

    def _probe_duration_ms(self, source_path: str) -> int:
        cv2 = self._dependencies.cv2
        capture = cv2.VideoCapture(source_path)
        try:
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
            duration_ms = int(round((frame_count / fps) * 1000)) if fps > 0 and frame_count > 0 else 0
            if duration_ms <= 0:
                duration_ms = 1000
            return duration_ms
        finally:
            capture.release()

    def _resolve_artifact_root(self, request_id: str) -> Path:
        artifact_root = run_child(self._runtime_root(), request_id, 'ai-evidence')
        artifact_root.mkdir(parents=True, exist_ok=True)
        return artifact_root

    def _render_storyboard_frames(
        self,
        *,
        source_path: str,
        output_dir: Path,
        prefix: str,
        times_ms: list[int],
    ) -> list[RenderedFrame]:
        output_dir.mkdir(parents=True, exist_ok=True)
        frames: list[RenderedFrame] = []
        for index, time_ms in enumerate(times_ms):
            frame = self._frame_reader.read_frame(source_path, time_ms)
            rendered, width, height = self._prepare_frame_image(
                frame,
                title=f'{prefix}-{index:03d}',
                subtitle=f'T+{_format_time_label(time_ms)}',
                show_header=True,
            )
            image_path = output_dir / f'{prefix}-{index:03d}.jpg'
            self._write_image(image_path, rendered)
            frames.append(RenderedFrame(
                frame_id=f'{prefix}-{index:03d}',
                time_ms=time_ms,
                sequence_index=index,
                label=f'{prefix}-{index:03d} @ T+{_format_time_label(time_ms)}',
                image_path=str(image_path),
                frame_width=width,
                frame_height=height,
            ))
        if not frames:
            raise RuntimeFailure('AI evidence storyboard sampling produced no frames.')
        return frames

    def _select_coarse_interval(self, request_id: str, description: str, frames: list[RenderedFrame]) -> StoryboardSelection:
        prompt_stage = self._prompt_catalog.coarse
        frame_list = '\n'.join(f'- {frame.frame_id}: {frame.label}' for frame in frames)
        user_prompt = prompt_stage.render_user_prompt(
            description=description,
            frameList=frame_list,
        )
        response = self._provider.generate_json(
            system_prompt=prompt_stage.system_prompt,
            user_prompt=user_prompt,
            images=[self._frame_to_chat_image(frame) for frame in frames],
            request_metadata={
                'workflow': 'ai-evidence',
                'runId': request_id,
                'requestId': request_id,
                'stage': 'coarse',
                'operation': 'localize-coarse-interval',
                'frameCount': len(frames),
            },
            progress_callback=lambda: self._emit_progress_step(
                request_id=request_id,
                step_key='llm-localize-coarse-interval',
            ),
        )
        return StoryboardSelection(
            start_frame=_resolve_frame_ref(response.get('startFrameId'), frames),
            end_frame=_resolve_frame_ref(response.get('endFrameId'), frames),
            anchor_frame=_resolve_frame_ref(response.get('anchorFrameId'), frames),
            summary=str(response.get('summary') or '').strip(),
        )

    def _select_fine_interval(
        self,
        request_id: str,
        description: str,
        frames: list[RenderedFrame],
        max_keyframes: int,
    ) -> StoryboardSelection:
        prompt_stage = self._prompt_catalog.fine
        frame_list = '\n'.join(f'- {frame.frame_id}: {frame.label}' for frame in frames)
        user_prompt = prompt_stage.render_user_prompt(
            description=description,
            frameList=frame_list,
            maxKeyframes=max_keyframes,
        )
        response = self._provider.generate_json(
            system_prompt=prompt_stage.system_prompt,
            user_prompt=user_prompt,
            images=[self._frame_to_chat_image(frame) for frame in frames],
            request_metadata={
                'workflow': 'ai-evidence',
                'runId': request_id,
                'requestId': request_id,
                'stage': 'fine',
                'operation': 'select-keyframes',
                'frameCount': len(frames),
                'maxKeyframes': max_keyframes,
            },
            progress_callback=lambda: self._emit_progress_step(
                request_id=request_id,
                step_key='llm-select-keyframes',
            ),
        )
        start_frame = _resolve_frame_ref(response.get('startFrameId'), frames)
        end_frame = _resolve_frame_ref(response.get('endFrameId'), frames)
        anchor_frame = _resolve_frame_ref(response.get('anchorFrameId'), frames)
        keyframe_refs = _normalize_keyframes(response.get('keyframes'), frames, desired_count=max_keyframes)
        return StoryboardSelection(
            start_frame=start_frame,
            end_frame=end_frame,
            anchor_frame=anchor_frame,
            summary=str(response.get('summary') or '').strip(),
            keyframes=tuple(keyframe_refs),
            keyframe_count_reason=_optional_string(response.get('keyframeCountReason')),
        )

    def _resolve_target(
        self,
        *,
        tool_calls: list[dict[str, Any]],
        request_id: str,
        description: str,
        source_path: str,
        marker_rect: NormalizedRect | None,
        target_vehicle_kind: str,
        country_hints: list[str],
        analysis_profile_id: str | None,
        enable_developer_diagnostics: bool,
        anchor_frame: RenderedFrame,
        output_dir: Path,
    ) -> dict[str, Any]:
        def collect_evidence() -> tuple[TargetResolutionEvidence, list[VisionChatImage]]:
            output_dir.mkdir(parents=True, exist_ok=True)
            frame = self._frame_reader.read_frame(source_path, anchor_frame.time_ms)
            detections = self._runtime_bridge.detect_targets(frame, anchor_frame.time_ms, target_vehicle_kind, marker_rect)
            if not detections:
                raise RuntimeFailure('AI evidence target resolution found no detectable targets on the selected anchor frame.')

            deduped_detections = _dedupe_anchor_target_detections(detections)
            deduped_detections = sorted(deduped_detections, key=lambda detection: detection.confidence, reverse=True)[:6]
            annotated_path, frame_width, frame_height = self._render_detection_reference(frame, deduped_detections, output_dir)
            return self._collect_target_resolution_evidence(
                request_id=request_id,
                description=description,
                source_path=source_path,
                marker_rect=marker_rect,
                target_vehicle_kind=target_vehicle_kind,
                country_hints=country_hints,
                analysis_profile_id=analysis_profile_id,
                enable_developer_diagnostics=enable_developer_diagnostics,
                anchor_frame=anchor_frame,
                frame=frame,
                detections=deduped_detections,
                output_dir=output_dir,
                annotated_path=annotated_path,
                frame_width=frame_width,
                frame_height=frame_height,
            )

        resolution_evidence, chat_images = self._record_tool_call(
            tool_calls,
            request_id=request_id,
            progress_step_key='scan-target-candidates',
            stage='resolve-target',
            tool_name='scan-target-candidates',
            input_summary=f'anchor={anchor_frame.frame_id} timeMs={anchor_frame.time_ms}',
            func=collect_evidence,
        )
        response = self._record_tool_call(
            tool_calls,
            request_id=request_id,
            progress_step_key='llm-resolve-target',
            stage='resolve-target',
            tool_name='llm-resolve-target',
            input_summary=f'anchor={anchor_frame.frame_id} candidates={len(resolution_evidence.candidates)}',
            func=lambda: self._resolve_target_with_ai(request_id, anchor_frame, resolution_evidence, chat_images),
        )

        return self._finalize_target_resolution(
            anchor_frame=anchor_frame,
            response=response,
            resolution_evidence=resolution_evidence,
        )

    def _resolve_target_with_ai(
        self,
        request_id: str,
        anchor_frame: RenderedFrame,
        resolution_evidence: TargetResolutionEvidence,
        chat_images: list[VisionChatImage],
    ) -> dict[str, Any] | None:
        system_prompt, user_prompt = self._build_target_resolution_prompt(resolution_evidence)
        try:
            return self._provider.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                images=chat_images,
                request_metadata={
                    'workflow': 'ai-evidence',
                    'runId': request_id,
                    'requestId': request_id,
                    'stage': 'target',
                    'operation': 'resolve-target',
                    'anchorFrameId': anchor_frame.frame_id,
                    'anchorTimeMs': anchor_frame.time_ms,
                    'candidateCount': len(resolution_evidence.candidates),
                    'plateHint': resolution_evidence.plate_hint,
                    'plateHintPolicy': 'strong-prior-not-absolute',
                    'plateHintMatchCount': len(resolution_evidence.exact_plate_hint_matches),
                    'plateHintMatchTrackId': (
                        resolution_evidence.primary_exact_plate_hint_match.candidate_evidence.track_id
                        if resolution_evidence.primary_exact_plate_hint_match is not None else None
                    ),
                },
                progress_callback=lambda: self._emit_progress_step(
                    request_id=request_id,
                    step_key='llm-resolve-target',
                ),
            )
        except Exception:
            if resolution_evidence.primary_exact_plate_hint_match is None:
                raise
            return None

    def _collect_target_resolution_evidence(
        self,
        *,
        request_id: str,
        description: str,
        source_path: str,
        marker_rect: NormalizedRect | None,
        target_vehicle_kind: str,
        country_hints: list[str],
        analysis_profile_id: str | None,
        enable_developer_diagnostics: bool,
        anchor_frame: RenderedFrame,
        frame: Any,
        detections: Sequence[TrackedRegion],
        output_dir: Path,
        annotated_path: Path,
        frame_width: int,
        frame_height: int,
    ) -> tuple[TargetResolutionEvidence, list[VisionChatImage]]:
        detection_evidence: list[TargetCandidateEvidence] = []
        chat_images = [VisionChatImage(
            frame_id='anchor-overview',
            label=f'anchor-overview @ T+{_format_time_label(anchor_frame.time_ms)}',
            image_base64=self._encode_chat_image(annotated_path),
        )]

        for index, detection in enumerate(detections):
            label = f'target-{index:02d}'
            crop_path = output_dir / f'{label}.jpg'
            crop = crop_image(frame, detection.box)
            rendered_crop, crop_width, crop_height = self._prepare_frame_image(
                crop,
                title=label,
                subtitle=f'T+{_format_time_label(anchor_frame.time_ms)}',
                show_header=False,
            )
            self._write_image(crop_path, rendered_crop)
            frame_result = self._runtime_bridge.analyze_frame({
                'sourcePath': source_path,
                'timeMs': anchor_frame.time_ms,
                'markerRect': marker_rect.to_payload() if marker_rect else None,
                'targetVehicleKind': target_vehicle_kind,
                'selectedTargetBox': detection.box.to_payload(),
                'countryHints': country_hints,
                'analysisProfileId': analysis_profile_id,
                'enableDeveloperDiagnostics': enable_developer_diagnostics,
                'requestId': f'{request_id}-{anchor_frame.frame_id}-target-{index:02d}',
            })
            candidates = tuple(candidate for candidate in (frame_result.get('candidates') or []) if isinstance(candidate, dict))
            detection_evidence.append(TargetCandidateEvidence(
                track_id=detection.id,
                label=label,
                class_name=detection.class_name,
                detection_confidence=detection.confidence,
                normalized_box=detection.box.to_payload(),
                selected_box=self._overlay_payload(detection.box, frame_width, frame_height),
                accepted_candidate_id=_optional_string(frame_result.get('acceptedCandidateId')),
                candidates=candidates,
                crop_image_path=str(crop_path),
                crop_frame_width=crop_width,
                crop_frame_height=crop_height,
                detection_diagnostics=detection.diagnostics,
            ))
            chat_images.append(VisionChatImage(
                frame_id=detection.id,
                label=f'{label} @ T+{_format_time_label(anchor_frame.time_ms)}',
                image_base64=self._encode_chat_image(crop_path),
            ))

        plate_hint = _extract_plate_hint(description)
        exact_plate_hint_matches = [
            PlateHintMatchEvidence(candidate_evidence=candidate_evidence, candidate=matched_candidate)
            for candidate_evidence in detection_evidence
            for matched_candidate in [candidate_evidence.matching_candidate(plate_hint)]
            if matched_candidate is not None
        ]
        exact_plate_hint_matches.sort(key=lambda match: match.sort_key(), reverse=True)
        return TargetResolutionEvidence(
            description=description,
            anchor_frame=anchor_frame,
            plate_hint=plate_hint,
            candidates=tuple(detection_evidence),
            exact_plate_hint_matches=tuple(exact_plate_hint_matches),
        ), chat_images

    def _build_target_resolution_prompt(
        self,
        resolution_evidence: TargetResolutionEvidence,
    ) -> tuple[str, str]:
        prompt_stage = self._prompt_catalog.target
        prompt_payload = json.dumps(
            resolution_evidence.to_prompt_payload(),
            ensure_ascii=False,
            indent=2,
        )
        user_prompt = prompt_stage.render_user_prompt(
            promptPayload=prompt_payload,
        )
        return prompt_stage.system_prompt, user_prompt

    def _finalize_target_resolution(
        self,
        *,
        anchor_frame: RenderedFrame,
        response: dict[str, Any] | None,
        resolution_evidence: TargetResolutionEvidence,
    ) -> dict[str, Any]:
        candidate_tracks = self._build_target_candidate_tracks(
            anchor_frame=anchor_frame,
            candidates=resolution_evidence.candidates,
        )
        strong_prior_match = resolution_evidence.primary_exact_plate_hint_match
        response = response or {}
        selected_track_id = _optional_string(response.get('selectedTrackId'))
        selected_candidate_id = _optional_string(response.get('selectedCandidateId'))
        selected_candidate = resolution_evidence.find_candidate(selected_track_id)
        rationale = str(response.get('rationale') or '').strip()
        confidence = _float_value(response.get('confidence')) or 0.5
        plate_hint_consistency = _normalize_plate_hint_consistency(response.get('plateHintConsistency'))

        if selected_candidate is not None:
            selected_candidate_id = selected_candidate.resolve_selected_candidate_id(selected_candidate_id)

        if strong_prior_match is not None:
            matched_candidate = strong_prior_match.candidate_evidence
            matched_candidate_id = _optional_string(strong_prior_match.candidate.get('id'))
            matched_candidate_text = strong_prior_match.matched_text(resolution_evidence.plate_hint)
            if selected_candidate is None:
                selected_candidate = matched_candidate
                selected_track_id = matched_candidate.track_id
                selected_candidate_id = matched_candidate_id
                confidence = max(confidence, 0.99)
                plate_hint_consistency = 'supporting'
                rationale = f'依據描述中的車牌 {matched_candidate_text} 與 OCR 候選完全一致，直接鎖定目標。'
            elif selected_candidate.track_id == matched_candidate.track_id:
                selected_candidate_id = matched_candidate_id
                confidence = max(confidence, 0.99)
                if plate_hint_consistency != 'contradicted':
                    plate_hint_consistency = 'supporting'
                if not rationale:
                    rationale = f'依據描述中的車牌 {matched_candidate_text} 與 OCR 候選完全一致，優先鎖定目標。'
            elif plate_hint_consistency != 'contradicted':
                overridden_track_id = selected_track_id or '未知 target'
                selected_candidate = matched_candidate
                selected_track_id = matched_candidate.track_id
                selected_candidate_id = matched_candidate_id
                confidence = max(confidence, 0.99)
                plate_hint_consistency = 'supporting'
                rationale = (
                    f'依據描述中的車牌 {matched_candidate_text} 與 OCR 候選完全一致，'
                    f'覆寫模型原先提議的 {overridden_track_id}。'
                )

        if selected_candidate is None:
            selected_candidate = resolution_evidence.candidates[0]
            selected_track_id = selected_candidate.track_id
            selected_candidate_id = selected_candidate.resolve_selected_candidate_id(selected_candidate_id)

        if plate_hint_consistency is None:
            if resolution_evidence.plate_hint is None:
                plate_hint_consistency = 'not-applicable'
            elif strong_prior_match is not None and selected_candidate.track_id == strong_prior_match.candidate_evidence.track_id:
                plate_hint_consistency = 'supporting'
            else:
                plate_hint_consistency = 'neutral'

        if not rationale:
            if plate_hint_consistency == 'contradicted' and resolution_evidence.plate_hint:
                rationale = f'畫面證據與描述中的車牌提示矛盾，因此改選 {selected_candidate.label}。'
            else:
                rationale = f'預設選擇 {selected_candidate.label}。'

        return {
            'anchorFrameId': anchor_frame.frame_id,
            'selectedTrackId': selected_track_id,
            'selectedCandidateId': selected_candidate_id,
            'confidence': confidence,
            'rationale': rationale,
            'selectedBox': selected_candidate.selected_box,
            'plateHint': resolution_evidence.plate_hint,
            'plateHintConsistency': plate_hint_consistency,
            'strongPriorTrackId': (
                strong_prior_match.candidate_evidence.track_id
                if strong_prior_match is not None else None
            ),
            'candidateTracks': candidate_tracks,
        }

    def _build_target_candidate_tracks(
        self,
        *,
        anchor_frame: RenderedFrame,
        candidates: Sequence[TargetCandidateEvidence],
    ) -> list[dict[str, Any]]:
        tracks: list[dict[str, Any]] = []
        for candidate in candidates:
            top_plate_text = candidate.top_plate_text
            label = top_plate_text or candidate.label
            tracks.append({
                'id': candidate.track_id,
                'className': candidate.class_name,
                'label': label,
                'confidence': candidate.detection_confidence,
                'frames': [{
                    'id': f'{candidate.track_id}-anchor',
                    'timeMs': anchor_frame.time_ms,
                    'box': candidate.normalized_box,
                    'confidence': candidate.detection_confidence,
                    'className': candidate.class_name,
                    'diagnostics': {
                        'source': 'ai-evidence-target-resolution',
                        'acceptedCandidateId': candidate.accepted_candidate_id,
                        'targetDetection': candidate.detection_diagnostics,
                        'ocrEvidence': candidate.to_prompt_payload(),
                    },
                }],
                'diagnostics': {
                    'source': 'ai-evidence-target-resolution',
                    'anchorFrameId': anchor_frame.frame_id,
                    'targetDetection': candidate.detection_diagnostics,
                    'ocrEvidence': candidate.to_prompt_payload(),
                },
            })
        return tracks

    def _render_detection_reference(
        self,
        frame: Any,
        detections: list[TrackedRegion],
        output_dir: Path,
    ) -> tuple[Path, int, int]:
        cv2 = self._dependencies.cv2
        annotated = frame.copy()
        height, width = annotated.shape[:2]
        for index, detection in enumerate(detections):
            x1, y1, x2, y2 = detection.box.to_pixels(width, height)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (16, 16, 255), 3)
            cv2.putText(
                annotated,
                f'target-{index:02d}',
                (x1, max(32, y1 - 12)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.9,
                (16, 16, 255),
                2,
                cv2.LINE_AA,
            )
        rendered, _, _ = self._prepare_frame_image(
            annotated,
            title='anchor-overview',
            subtitle='candidate targets',
            show_header=False,
        )
        output_path = output_dir / 'anchor-overview.jpg'
        self._write_image(output_path, rendered)
        return output_path, width, height

    def _render_keyframes(
        self,
        *,
        source_path: str,
        keyframe_refs: Sequence[SelectedKeyframe],
        analysis_track: dict[str, Any] | None,
        output_dir: Path,
    ) -> list[dict[str, Any]]:
        output_dir.mkdir(parents=True, exist_ok=True)
        rendered_keyframes: list[dict[str, Any]] = []
        for keyframe in keyframe_refs:
            if not keyframe.is_user_facing:
                continue
            rendered_frame = keyframe.frame
            frame = self._frame_reader.read_frame(source_path, rendered_frame.time_ms)
            box, box_source, box_time_delta_ms = _find_closest_track_box(analysis_track, rendered_frame.time_ms)
            annotated, frame_width, frame_height = self._prepare_frame_image(
                frame,
                title=rendered_frame.frame_id,
                subtitle=f'T+{_format_time_label(rendered_frame.time_ms)}',
                box=box if isinstance(box, dict) else None,
                show_header=False,
            )
            output_path = output_dir / f'{rendered_frame.frame_id}.png'
            self._write_image(output_path, annotated)
            rendered_keyframes.append({
                'frame': rendered_frame.to_payload(image_path=str(output_path)),
                'description': keyframe.description,
                'overlay': self._overlay_payload(NormalizedRect.from_payload(box) if isinstance(box, dict) else None, frame_width, frame_height),
                'keyframeSource': keyframe.keyframe_source,
                'descriptionSource': keyframe.description_source,
                'isValidForUserFacingOutput': True,
                'supplementReason': keyframe.supplement_reason,
                'boxSource': box_source,
                'boxTimeDeltaMs': box_time_delta_ms,
            })
        return rendered_keyframes

    def _prepare_frame_image(
        self,
        frame: Any,
        *,
        title: str,
        subtitle: str,
        box: dict[str, Any] | None = None,
        show_header: bool = True,
    ) -> tuple[Any, int, int]:
        cv2 = self._dependencies.cv2
        image = frame.copy()
        height, width = image.shape[:2]
        if box:
            normalized_box = NormalizedRect.from_payload(box)
            if normalized_box is not None:
                x1, y1, x2, y2 = normalized_box.to_pixels(width, height)
                cv2.rectangle(image, (x1, y1), (x2, y2), (16, 16, 255), 3)
        if show_header:
            cv2.rectangle(image, (0, 0), (min(width, 520), 84), (8, 8, 8), -1)
            cv2.putText(image, title, (18, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.putText(image, subtitle, (18, 66), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (222, 222, 222), 2, cv2.LINE_AA)
        longest_side = max(width, height)
        if longest_side > 1280:
            scale = 1280.0 / float(longest_side)
            image = cv2.resize(image, (int(round(width * scale)), int(round(height * scale))), interpolation=cv2.INTER_AREA)
            height, width = image.shape[:2]
        return image, width, height

    def _write_image(self, path: Path, image: Any) -> None:
        cv2 = self._dependencies.cv2
        suffix = path.suffix.lower()
        if suffix == '.png':
            ok, encoded = cv2.imencode('.png', image, [int(cv2.IMWRITE_PNG_COMPRESSION), 3])
        else:
            ok, encoded = cv2.imencode('.jpg', image, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        if not ok:
            raise RuntimeFailure(f'Unable to encode image artifact at {path}.')
        path.write_bytes(encoded.tobytes())

    def _frame_to_chat_image(self, frame: RenderedFrame) -> VisionChatImage:
        return VisionChatImage(
            frame_id=frame.frame_id,
            label=frame.label,
            image_base64=self._encode_chat_image(Path(frame.image_path)),
        )

    def _encode_chat_image(self, path: Path) -> str:
        cv2 = self._dependencies.cv2
        image = cv2.imread(str(path))
        if image is None:
            return _encode_image_path(path)

        height, width = image.shape[:2]
        longest_side = max(width, height)
        if longest_side > 960:
            scale = 960.0 / float(longest_side)
            image = cv2.resize(
                image,
                (int(round(width * scale)), int(round(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
            height, width = image.shape[:2]

        shortest_side = min(width, height)
        if 0 < shortest_side < 64:
            scale = 64.0 / float(shortest_side)
            image = cv2.resize(
                image,
                (max(64, int(round(width * scale))), max(64, int(round(height * scale)))),
                interpolation=cv2.INTER_CUBIC,
            )

        ok, encoded = cv2.imencode('.jpg', image, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
        if not ok:
            return _encode_image_path(path)
        return base64.b64encode(encoded.tobytes()).decode('ascii')

    def _overlay_payload(
        self,
        normalized_box: NormalizedRect | None,
        frame_width: int,
        frame_height: int,
    ) -> dict[str, Any] | None:
        if normalized_box is None:
            return None
        x1, y1, x2, y2 = normalized_box.to_pixels(frame_width, frame_height)
        return {
            'normalizedBox': normalized_box.to_payload(),
            'pixelBox': {
                'x': max(0, x1),
                'y': max(0, y1),
                'width': max(1, x2 - x1),
                'height': max(1, y2 - y1),
            },
            'frameWidth': frame_width,
            'frameHeight': frame_height,
        }

    def _build_projection(
        self,
        interval_result: dict[str, Any],
        interval: dict[str, Any],
        target_resolution: dict[str, Any],
    ) -> dict[str, Any]:
        interval_target_tracks = interval_result.get('targetTracks') or []
        target_tracks = target_resolution.get('candidateTracks') or interval_target_tracks
        selected_target_track_id = _optional_string(target_resolution.get('selectedTrackId'))
        analysis_track = interval_result.get('analysisTrack') if isinstance(interval_result.get('analysisTrack'), dict) else None
        if analysis_track is None:
            analysis_track = next(
                (
                    track for track in interval_target_tracks
                    if isinstance(track, dict) and _optional_string(track.get('id')) == selected_target_track_id
                ),
                None,
            )
        if analysis_track is None:
            if len(interval_target_tracks) == 1 and selected_target_track_id is not None and isinstance(interval_target_tracks[0], dict):
                analysis_track = _canonicalize_track_id(interval_target_tracks[0], selected_target_track_id)
            else:
                analysis_track = interval_target_tracks[0] if interval_target_tracks else None
        if selected_target_track_id is None and isinstance(analysis_track, dict):
            selected_target_track_id = _optional_string(analysis_track.get('id'))
        return {
            'interval': interval,
            'targetTracks': target_tracks,
            'analysisTrack': analysis_track,
            'selectedTargetTrackId': selected_target_track_id,
            'samples': interval_result.get('samples') or [],
            'candidates': interval_result.get('candidates') or [],
            'acceptedCandidateId': interval_result.get('acceptedCandidateId'),
            'review': interval_result.get('review'),
            'provenance': interval_result.get('provenance'),
            'decision': interval_result.get('decision'),
        }

    def _record_tool_call(
        self,
        tool_calls: list[dict[str, Any]],
        *,
        request_id: str,
        progress_step_key: str,
        stage: str,
        tool_name: str,
        input_summary: str,
        func: Callable[[], Any],
    ) -> Any:
        self._emit_progress_step(request_id=request_id, step_key=progress_step_key)
        started_at_ms = time.time_ns() // 1_000_000
        success = False
        output_summary = ''
        try:
            result = func()
            success = True
            output_summary = _summarize_result(result)
            return result
        finally:
            tool_calls.append({
                'stage': stage,
                'toolName': tool_name,
                'inputSummary': input_summary,
                'outputSummary': output_summary,
                'startedAtMs': started_at_ms,
                'completedAtMs': time.time_ns() // 1_000_000,
                'success': success,
            })


def _sample_times(duration_ms: int, step_ms: int, *, max_samples: int, offset_ms: int = 0) -> list[int]:
    if duration_ms <= 0:
        return [offset_ms]
    times: list[int] = []
    current = offset_ms
    end_ms = offset_ms + duration_ms
    while current <= end_ms:
        times.append(current)
        current += step_ms
    if times[-1] != end_ms:
        if end_ms - times[-1] < MIN_DISTINCT_STORYBOARD_GAP_MS:
            times[-1] = end_ms
        else:
            times.append(end_ms)
    if len(times) <= max_samples:
        return times
    indices = [round(index * (len(times) - 1) / max(1, max_samples - 1)) for index in range(max_samples)]
    return [times[index] for index in OrderedDict.fromkeys(indices)]


def _dedupe_anchor_target_detections(detections: Sequence[TrackedRegion]) -> list[TrackedRegion]:
    deduped: list[TrackedRegion] = []
    suppressed_counts: dict[str, int] = {}

    for detection in sorted(detections, key=lambda candidate: candidate.confidence, reverse=True):
        duplicate_owner = next(
            (candidate for candidate in deduped if _anchor_target_detections_overlap(candidate, detection)),
            None,
        )
        if duplicate_owner is not None:
            suppressed_counts[duplicate_owner.id] = suppressed_counts.get(duplicate_owner.id, 0) + 1
            continue
        deduped.append(detection)

    for detection in deduped:
        suppressed = suppressed_counts.get(detection.id, 0)
        if suppressed <= 0:
            continue
        detection.diagnostics = {
            **(detection.diagnostics or {}),
            'suppressedDuplicateDetections': suppressed,
        }

    return deduped


def _anchor_target_detections_overlap(left: TrackedRegion, right: TrackedRegion) -> bool:
    if left.class_name != right.class_name:
        return False

    iou = left.box.intersection_over_union(right.box)
    overlap_over_smaller = _overlap_over_smaller(left.box, right.box)
    center_distance = left.box.center_distance(right.box)
    area_similarity = min(left.box.area(), right.box.area()) / max(left.box.area(), right.box.area(), 1e-6)
    return (
        iou >= 0.58
        or overlap_over_smaller >= 0.78
        or (
            overlap_over_smaller >= 0.52
            and center_distance <= 0.055
            and area_similarity >= 0.34
        )
    )


def _overlap_over_smaller(left: NormalizedRect, right: NormalizedRect) -> float:
    left_x2 = left.x + left.width
    left_y2 = left.y + left.height
    right_x2 = right.x + right.width
    right_y2 = right.y + right.height
    inter_x1 = max(left.x, right.x)
    inter_y1 = max(left.y, right.y)
    inter_x2 = min(left_x2, right_x2)
    inter_y2 = min(left_y2, right_y2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    return inter_area / max(min(left.area(), right.area()), 1e-6)


def _canonicalize_track_id(track: dict[str, Any], canonical_track_id: str) -> dict[str, Any]:
    original_track_id = _optional_string(track.get('id'))
    if original_track_id == canonical_track_id:
        return track
    return {
        **track,
        'id': canonical_track_id,
        'diagnostics': {
            **(track.get('diagnostics') or {}),
            'canonicalizedFromTrackId': original_track_id,
        },
    }


def _resolve_fine_step_ms(
    *,
    start_ms: int,
    end_ms: int,
    requested_step_ms: int,
    preferred_samples: int,
    max_samples: int,
) -> int:
    duration_ms = max(1, end_ms - start_ms)
    minimum_step = max(80, duration_ms // max(1, max_samples - 1))
    preferred_step = max(80, duration_ms // max(1, preferred_samples - 1))
    return max(minimum_step, min(max(80, requested_step_ms), preferred_step))


def _encode_image_path(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode('ascii')


def _resolve_frame_ref(value: Any, frames: list[RenderedFrame]) -> RenderedFrame:
    if isinstance(value, str):
        for frame in frames:
            if frame.frame_id == value:
                return frame
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        for frame in frames:
            if frame.sequence_index == int(value):
                return frame
    raise RuntimeFailure('LLM returned an unknown frame reference.')


def _normalize_keyframes(value: Any, frames: list[RenderedFrame], *, desired_count: int) -> list[SelectedKeyframe]:
    ordered_frames = sorted(frames, key=lambda item: item.time_ms)
    by_id = {frame.frame_id: frame for frame in ordered_frames}
    selected: list[SelectedKeyframe] = []
    for item in value if isinstance(value, list) else []:
        frame_id = item.get('frameId') if isinstance(item, dict) else item if isinstance(item, str) else None
        if isinstance(frame_id, str) and frame_id in by_id:
            frame = by_id[frame_id]
            description = ''
            if isinstance(item, dict):
                description = str(item.get('description') or '').strip()
            if description:
                selected.append(SelectedKeyframe(
                    frame=frame,
                    description=description,
                ))
                continue
            selected.append(SelectedKeyframe(
                frame=frame,
                description=_fallback_keyframe_description(frame=frame, frames=ordered_frames),
                description_source='fallback',
                supplement_reason='missing-description',
            ))
    deduped: list[SelectedKeyframe] = []
    seen_frame_ids: set[str] = set()
    for entry in selected:
        if entry.frame.frame_id in seen_frame_ids:
            continue
        seen_frame_ids.add(entry.frame.frame_id)
        deduped.append(entry)
    deduped = _collapse_temporally_dense_keyframes(deduped)
    deduped = _rebalance_keyframes_for_temporal_coverage(
        deduped,
        ordered_frames,
        desired_count=desired_count,
    )
    seen_frame_ids = {entry.frame.frame_id for entry in deduped}
    if len(deduped) < desired_count:
        for frame in ordered_frames:
            if frame.frame_id in seen_frame_ids:
                continue
            seen_frame_ids.add(frame.frame_id)
            deduped.append(_build_runtime_supplemented_keyframe(
                frame=frame,
                frames=ordered_frames,
                supplement_reason='under-target-backfill',
            ))
            if len(deduped) >= desired_count:
                break
    return sorted(deduped, key=lambda entry: entry.frame.time_ms)[:desired_count]


def _build_runtime_supplemented_keyframe(
    *,
    frame: RenderedFrame,
    frames: list[RenderedFrame],
    supplement_reason: str,
) -> SelectedKeyframe:
    return SelectedKeyframe(
        frame=frame,
        description=_fallback_keyframe_description(frame=frame, frames=frames),
        keyframe_source='runtime-supplemented',
        description_source='fallback',
        supplement_reason=supplement_reason,
    )


def _collapse_temporally_dense_keyframes(
    keyframes: list[SelectedKeyframe],
    *,
    minimum_gap_ms: int = MIN_DISTINCT_STORYBOARD_GAP_MS,
) -> list[SelectedKeyframe]:
    collapsed: list[SelectedKeyframe] = []
    for entry in sorted(keyframes, key=lambda item: item.frame.time_ms):
        if not collapsed:
            collapsed.append(entry)
            continue
        previous = collapsed[-1]
        if entry.frame.time_ms - previous.frame.time_ms >= minimum_gap_ms:
            collapsed.append(entry)
            continue
        if _selected_keyframe_priority(entry) >= _selected_keyframe_priority(previous):
            collapsed[-1] = entry
    return collapsed


def _selected_keyframe_priority(entry: SelectedKeyframe) -> tuple[int, int, int]:
    return (
        1 if entry.description_source == 'llm' else 0,
        1 if entry.keyframe_source == 'llm-selected' else 0,
        entry.frame.time_ms,
    )


def _rebalance_keyframes_for_temporal_coverage(
    keyframes: list[SelectedKeyframe],
    frames: list[RenderedFrame],
    *,
    desired_count: int,
) -> list[SelectedKeyframe]:
    if not keyframes or not frames or desired_count <= 0:
        return sorted(keyframes, key=lambda item: item.frame.time_ms)

    bucket_count = _temporal_bucket_count(len(frames), desired_count)
    if bucket_count <= 1:
        return sorted(keyframes, key=lambda item: item.frame.time_ms)

    buckets = _split_frames_into_temporal_buckets(frames, bucket_count)
    frame_bucket_indices = {
        frame.frame_id: bucket_index
        for bucket_index, bucket in enumerate(buckets)
        for frame in bucket
    }
    per_bucket_cap = max(1, (desired_count + bucket_count - 1) // bucket_count)
    selected_by_id = {
        entry.frame.frame_id: entry
        for entry in sorted(keyframes, key=lambda item: item.frame.time_ms)
    }
    result: list[SelectedKeyframe] = []
    seen_frame_ids: set[str] = set()
    bucket_counts = [0] * len(buckets)

    def add_entry(entry: SelectedKeyframe, *, respect_cap: bool) -> bool:
        frame_id = entry.frame.frame_id
        if frame_id in seen_frame_ids:
            return False
        bucket_index = frame_bucket_indices.get(frame_id)
        if bucket_index is None:
            return False
        if respect_cap and bucket_counts[bucket_index] >= per_bucket_cap:
            return False
        seen_frame_ids.add(frame_id)
        bucket_counts[bucket_index] += 1
        result.append(entry)
        return True

    for bucket in buckets:
        bucket_selected = [selected_by_id[frame.frame_id] for frame in bucket if frame.frame_id in selected_by_id]
        if bucket_selected:
            add_entry(bucket_selected[0], respect_cap=False)
            continue
        fallback_frame = _pick_bucket_frame(bucket, seen_frame_ids)
        if fallback_frame is None:
            continue
        add_entry(_build_runtime_supplemented_keyframe(
            frame=fallback_frame,
            frames=frames,
            supplement_reason='temporal-coverage',
        ), respect_cap=False)

    for entry in sorted(keyframes, key=lambda item: item.frame.time_ms):
        if len(result) >= desired_count:
            break
        add_entry(entry, respect_cap=True)

    while len(result) < desired_count:
        progress = False
        for bucket_index in _bucket_fill_order(bucket_counts):
            if len(result) >= desired_count:
                break
            if bucket_counts[bucket_index] >= per_bucket_cap:
                continue
            fallback_frame = _pick_bucket_frame(buckets[bucket_index], seen_frame_ids)
            if fallback_frame is None:
                continue
            if add_entry(_build_runtime_supplemented_keyframe(
                frame=fallback_frame,
                frames=frames,
                supplement_reason='temporal-coverage',
            ), respect_cap=True):
                progress = True
        if not progress:
            break

    return sorted(result, key=lambda item: item.frame.time_ms)


def _temporal_bucket_count(frame_count: int, desired_count: int) -> int:
    if frame_count <= 0 or desired_count <= 0:
        return 0
    if desired_count >= 8 and frame_count >= 5:
        return 5
    if desired_count >= 6 and frame_count >= 4:
        return 4
    return min(frame_count, desired_count)


def _split_frames_into_temporal_buckets(frames: list[RenderedFrame], bucket_count: int) -> list[list[RenderedFrame]]:
    buckets: list[list[RenderedFrame]] = []
    for bucket_index in range(bucket_count):
        start = (bucket_index * len(frames)) // bucket_count
        end = max(start + 1, ((bucket_index + 1) * len(frames)) // bucket_count)
        bucket = frames[start:end]
        if bucket:
            buckets.append(bucket)
    return buckets


def _pick_bucket_frame(bucket: list[RenderedFrame], seen_frame_ids: set[str]) -> RenderedFrame | None:
    candidates = [frame for frame in bucket if frame.frame_id not in seen_frame_ids]
    if not candidates:
        return None
    center_frame = bucket[len(bucket) // 2]
    return min(candidates, key=lambda frame: (abs(frame.time_ms - center_frame.time_ms), frame.time_ms))


def _bucket_fill_order(bucket_counts: list[int]) -> list[int]:
    if not bucket_counts:
        return []
    center_index = (len(bucket_counts) - 1) / 2
    return sorted(
        range(len(bucket_counts)),
        key=lambda index: (bucket_counts[index], abs(index - center_index), index),
    )


def _resolve_keyframe_count_reason(
    *,
    rendered_count: int,
    desired_count: int,
    available_frame_count: int,
    provider_reason: str | None,
) -> str | None:
    if rendered_count >= 8:
        return None
    if available_frame_count < 8:
        return f'Only {available_frame_count} distinct fine storyboard frame(s) were available, so 8 keyframes could not be produced.'
    if rendered_count < desired_count and provider_reason:
        return provider_reason
    return f'Only {rendered_count} user-facing keyframe(s) survived runtime rendering after validation.'


def _fallback_keyframe_description(*, frame: RenderedFrame, frames: list[RenderedFrame]) -> str:
    ordered_frames = sorted(frames, key=lambda item: item.time_ms)
    if not ordered_frames:
        return '這是事件中的關鍵畫面，請重點查看主要目標與周邊情境。'

    position = ordered_frames.index(frame) if frame in ordered_frames else 0
    if position == 0:
        stage_description = '這是事件開始附近的關鍵畫面，請重點確認目標最初出現的位置與周邊情境。'
    elif position == len(ordered_frames) - 1:
        stage_description = '這是事件尾段的關鍵畫面，請重點確認目標最後的位置、動作與結果。'
    else:
        stage_description = '這是事件進行中的關鍵畫面，請重點查看目標的動作變化與周邊互動。'

    return f'{stage_description} 畫面時間約為 T+{_format_time_label(frame.time_ms)}。'


def _find_closest_track_box(track: dict[str, Any] | None, time_ms: int) -> tuple[dict[str, Any] | None, str | None, int | None]:
    if not isinstance(track, dict):
        return None, None, None
    frames = [frame for frame in (track.get('frames') or []) if isinstance(frame, dict) and isinstance(frame.get('box'), dict)]
    if not frames:
        return None, None, None
    closest = min(frames, key=lambda frame: abs(int(frame.get('timeMs') or 0) - time_ms))
    closest_time_ms = int(closest.get('timeMs') or 0)
    time_delta_ms = abs(closest_time_ms - time_ms)
    if time_delta_ms > _keyframe_track_box_tolerance_ms(frames):
        return None, None, time_delta_ms
    return closest.get('box') if isinstance(closest.get('box'), dict) else None, 'analysis-track', time_delta_ms


def _keyframe_track_box_tolerance_ms(track_frames: Sequence[dict[str, Any]]) -> int:
    ordered_times = sorted(
        int(frame.get('timeMs') or 0)
        for frame in track_frames
        if isinstance(frame, dict)
    )
    if len(ordered_times) < 2:
        return 240
    deltas = [
        current - previous
        for previous, current in zip(ordered_times, ordered_times[1:])
        if current > previous
    ]
    if not deltas:
        return 240
    deltas.sort()
    median_delta = deltas[len(deltas) // 2]
    return max(180, min(600, median_delta * 2))


def _resolve_plate_candidate(candidates: Sequence[dict[str, Any]], accepted_candidate_id: Any) -> dict[str, Any] | None:
    accepted_id = _optional_string(accepted_candidate_id)
    if accepted_id:
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get('id') == accepted_id:
                return candidate
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return None


def _format_time_label(time_ms: int) -> str:
    total_ms = max(0, int(time_ms))
    total_seconds, milliseconds = divmod(total_ms, 1000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f'{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}'
    return f'{minutes:02d}:{seconds:02d}.{milliseconds:03d}'


def _normalize_plate(value: str) -> str:
    return ''.join(character for character in value.upper() if character.isalnum())


def _candidate_evidence_payload(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return None
    text = _optional_string(candidate.get('text'))
    return {
        'candidateId': _optional_string(candidate.get('id')),
        'text': text,
        'normalizedText': _normalize_plate(text) if text else None,
        'confidence': _float_value(candidate.get('confidence')) or 0.0,
        'source': _optional_string(candidate.get('source')),
    }


def _normalize_plate_hint_consistency(value: Any) -> str | None:
    normalized = _optional_string(value.lower()) if isinstance(value, str) else None
    if normalized in {'supporting', 'neutral', 'contradicted', 'not-applicable'}:
        return normalized
    return None


def _extract_plate_hint(description: str) -> str | None:
    match = re.search(r'([A-Z0-9]{2,4}-?[A-Z0-9]{2,4})', description.upper())
    if not match:
        return None
    return _normalize_plate(match.group(1))


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _float_value(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _build_summary(description: str, interval: dict[str, Any], plate_candidate: dict[str, Any] | None) -> str:
    plate_text = plate_candidate.get('text') if isinstance(plate_candidate, dict) else None
    plate_label = f'，車牌 {plate_text}' if isinstance(plate_text, str) and plate_text else ''
    return (
        f'根據描述「{description}」，完整事件區段為影片 T+{_format_time_label(int(interval["startMs"]))} '
        f'到 T+{_format_time_label(int(interval["endMs"]))}{plate_label}。'
    )


def _summarize_result(result: Any) -> str:
    if isinstance(result, list):
        return f'items={len(result)}'
    if isinstance(result, dict):
        if 'summary' in result:
            return str(result.get('summary') or '')[:160]
        return f'keys={len(result)}'
    return str(result)[:160]