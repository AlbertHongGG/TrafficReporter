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

from traffic_lpr_runtime.application.services.ai_evidence.models import (
    AI_EVIDENCE_PROGRESS_STEPS,
    AI_EVIDENCE_WORKFLOW_STEP_COUNT,
    MIN_DISTINCT_STORYBOARD_GAP_MS,
    AiEvidenceProgressStep,
    AiEvidenceRuntimeBridge,
    PlateHintMatchEvidence,
    RenderedFrame,
    SelectedKeyframe,
    StoryboardSelection,
    TargetCandidateEvidence,
    TargetResolutionEvidence,
    _progress_for_step,
)
from traffic_lpr_runtime.application.services.ai_evidence.keyframes import (
    _build_runtime_supplemented_keyframe,
    _collapse_temporally_dense_keyframes,
    _encode_image_path,
    _fallback_keyframe_description,
    _find_closest_track_box,
    _keyframe_track_box_tolerance_ms,
    _normalize_keyframes,
    _rebalance_keyframes_for_temporal_coverage,
    _resolve_frame_ref,
    _resolve_keyframe_count_reason,
    _sample_times,
    _selected_keyframe_priority,
    _split_frames_into_temporal_buckets,
    _temporal_bucket_count,
)
from traffic_lpr_runtime.application.services.ai_evidence.target_resolver import (
    _anchor_target_detections_overlap,
    _build_summary,
    _candidate_evidence_payload,
    _canonicalize_track_id,
    _dedupe_anchor_target_detections,
    _extract_plate_hint,
    _format_time_label,
    _normalize_plate,
    _normalize_plate_hint_consistency,
    _overlap_over_smaller,
    _resolve_fine_step_ms,
    _resolve_plate_candidate,
    _summarize_result,
)


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _float_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

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


