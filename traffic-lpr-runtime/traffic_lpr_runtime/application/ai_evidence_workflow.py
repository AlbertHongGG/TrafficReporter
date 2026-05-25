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
from traffic_lpr_runtime.domain.errors import RuntimeFailure
from traffic_lpr_runtime.domain.models import TrackedRegion
from traffic_lpr_runtime.domain.value_objects import NormalizedRect, crop_image
from traffic_lpr_runtime.infrastructure.runtime_layout import build_run_id, run_child
from traffic_lpr_runtime.infrastructure.runtime_settings import get_runtime_settings


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


@dataclass(frozen=True, slots=True)
class StoryboardSelection:
    start_frame: RenderedFrame
    end_frame: RenderedFrame
    anchor_frame: RenderedFrame
    summary: str
    keyframes: Sequence[SelectedKeyframe] = field(default_factory=tuple)


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
        target_resolution = self._record_tool_call(
            tool_calls,
            stage='resolve-target',
            tool_name='llm-resolve-target',
            input_summary=f'anchor={anchor_frame.frame_id} timeMs={anchor_frame.time_ms}',
            func=lambda: self._resolve_target(
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
            ),
        )

        interval_result = self._record_tool_call(
            tool_calls,
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
                'countryHints': country_hints,
                'analysisProfileId': analysis_profile_id,
                'enableDeveloperDiagnostics': enable_developer_diagnostics,
                'sampleEveryMs': fine_step_ms,
                'maxSamples': max(12, len(fine_frames) + 4),
                'requestId': request_id,
            }),
        )

        projection = self._build_projection(interval_result, planned_interval, target_resolution)
        plate_candidate = _resolve_plate_candidate(projection['candidates'], projection['acceptedCandidateId'])
        keyframes = self._record_tool_call(
            tool_calls,
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
            'toolCalls': tool_calls,
            'projection': projection,
            'runtime': runtime_status,
        }

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
        system_prompt = (
            '你是交通事件關鍵證據規劃器。你只能引用系統提供的 frameId，不能自行猜測時間。'
            '請根據使用者描述，從提供的 frameId 中找出最可能涵蓋完整事件過程的起點、終點與 anchor。'
            '只輸出 JSON 物件。'
        )
        frame_list = '\n'.join(f'- {frame.frame_id}: {frame.label}' for frame in frames)
        user_prompt = (
            f'使用者描述:\n{description}\n\n'
            f'可用 frame 參考:\n{frame_list}\n\n'
            '請輸出 JSON:\n'
            '{"startFrameId":"...","endFrameId":"...","anchorFrameId":"...","summary":"..."}'
        )
        response = self._provider.generate_json(
            system_prompt=system_prompt,
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
        system_prompt = (
            '你是交通事件關鍵幀規劃器。你只能引用提供的 frameId，不能自由編造新的時間。'
            '請選出完整事件區段的起點、終點、一個 target anchor，以及 8 到 10 個足以描述完整過程的關鍵幀。'
            '每個關鍵幀都要有一句簡短中文描述。只輸出 JSON 物件。'
        )
        frame_list = '\n'.join(f'- {frame.frame_id}: {frame.label}' for frame in frames)
        user_prompt = (
            f'使用者描述:\n{description}\n\n'
            f'可用 frame 參考:\n{frame_list}\n\n'
            '請輸出 JSON:\n'
            '{"startFrameId":"...","endFrameId":"...","anchorFrameId":"...","summary":"...",'
            '"keyframes":[{"frameId":"...","description":"..."}]}'
        )
        response = self._provider.generate_json(
            system_prompt=system_prompt,
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
        )

    def _resolve_target(
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
        output_dir: Path,
    ) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        frame = self._frame_reader.read_frame(source_path, anchor_frame.time_ms)
        detections = self._runtime_bridge.detect_targets(frame, anchor_frame.time_ms, target_vehicle_kind, marker_rect)
        if not detections:
            raise RuntimeFailure('AI evidence target resolution found no detectable targets on the selected anchor frame.')

        detections = sorted(detections, key=lambda detection: detection.confidence, reverse=True)[:6]
        annotated_path, frame_width, frame_height = self._render_detection_reference(frame, detections, output_dir)
        resolution_evidence, chat_images = self._collect_target_resolution_evidence(
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
            detections=detections,
            output_dir=output_dir,
            annotated_path=annotated_path,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        system_prompt, user_prompt = self._build_target_resolution_prompt(resolution_evidence)
        try:
            response = self._provider.generate_json(
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
            )
        except Exception:
            if resolution_evidence.primary_exact_plate_hint_match is None:
                raise
            response = None

        return self._finalize_target_resolution(
            anchor_frame=anchor_frame,
            response=response,
            resolution_evidence=resolution_evidence,
        )

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
        system_prompt = (
            '你是交通事件 target resolver。你必須只從提供的候選 target IDs 中選出最符合描述的目標。'
            '請結合 anchor overview、各個 target crop、以及結構化 OCR 證據判斷。只輸出 JSON。'
        )
        prompt_payload = json.dumps(
            resolution_evidence.to_prompt_payload(),
            ensure_ascii=False,
            indent=2,
        )
        user_prompt = (
            '請根據以下 JSON 證據與對應圖片選擇 target。targets[*].imageFrameId 會對應到提供的 crop 圖。\n'
            '如果 exactPlateHintMatches 非空，代表 OCR 與描述中的車牌提示完全一致，這是 strong prior；'
            '只有當畫面證據明確矛盾時，才可改選其他 target，並將 plateHintConsistency 設為 contradicted。\n\n'
            f'{prompt_payload}\n\n'
            '請只輸出 JSON:\n'
            '{"selectedTrackId":"...","selectedCandidateId":"...","confidence":0.0,'
            '"plateHintConsistency":"supporting|neutral|contradicted|not-applicable","rationale":"..."}'
        )
        return system_prompt, user_prompt

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
                        'ocrEvidence': candidate.to_prompt_payload(),
                    },
                }],
                'diagnostics': {
                    'source': 'ai-evidence-target-resolution',
                    'anchorFrameId': anchor_frame.frame_id,
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
        rendered, _, _ = self._prepare_frame_image(annotated, title='anchor-overview', subtitle='candidate targets')
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
            rendered_frame = keyframe.frame
            frame = self._frame_reader.read_frame(source_path, rendered_frame.time_ms)
            box = _find_closest_track_box(analysis_track, rendered_frame.time_ms)
            title = rendered_frame.frame_id
            subtitle = f'T+{_format_time_label(rendered_frame.time_ms)}'
            annotated, frame_width, frame_height = self._prepare_frame_image(frame, title=title, subtitle=subtitle, box=box)
            output_path = output_dir / f'{rendered_frame.frame_id}.jpg'
            self._write_image(output_path, annotated)
            rendered_keyframes.append({
                'frame': rendered_frame.to_payload(image_path=str(output_path)),
                'description': keyframe.description,
                'overlay': self._overlay_payload(NormalizedRect.from_payload(box) if isinstance(box, dict) else None, frame_width, frame_height),
            })
        return rendered_keyframes

    def _prepare_frame_image(
        self,
        frame: Any,
        *,
        title: str,
        subtitle: str,
        box: dict[str, Any] | None = None,
    ) -> tuple[Any, int, int]:
        cv2 = self._dependencies.cv2
        image = frame.copy()
        height, width = image.shape[:2]
        if box:
            normalized_box = NormalizedRect.from_payload(box)
            if normalized_box is not None:
                x1, y1, x2, y2 = normalized_box.to_pixels(width, height)
                cv2.rectangle(image, (x1, y1), (x2, y2), (16, 16, 255), 3)
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
        ok, encoded = cv2.imencode('.jpg', image)
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
        analysis_track = next(
            (
                track for track in interval_target_tracks
                if isinstance(track, dict) and _optional_string(track.get('id')) == selected_target_track_id
            ),
            None,
        )
        if analysis_track is None:
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
        }

    def _record_tool_call(
        self,
        tool_calls: list[dict[str, Any]],
        *,
        stage: str,
        tool_name: str,
        input_summary: str,
        func: Callable[[], Any],
    ) -> Any:
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
        times.append(end_ms)
    if len(times) <= max_samples:
        return times
    indices = [round(index * (len(times) - 1) / max(1, max_samples - 1)) for index in range(max_samples)]
    return [times[index] for index in OrderedDict.fromkeys(indices)]


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
    by_id = {frame.frame_id: frame for frame in frames}
    selected: list[SelectedKeyframe] = []
    for item in value if isinstance(value, list) else []:
        frame_id = item.get('frameId') if isinstance(item, dict) else item if isinstance(item, str) else None
        if isinstance(frame_id, str) and frame_id in by_id:
            frame = by_id[frame_id]
            selected.append(SelectedKeyframe(
                frame=frame,
                description=str(item.get('description') or frame.label) if isinstance(item, dict) else frame.label,
            ))
    deduped: list[SelectedKeyframe] = []
    seen_frame_ids: set[str] = set()
    for entry in selected:
        if entry.frame.frame_id in seen_frame_ids:
            continue
        seen_frame_ids.add(entry.frame.frame_id)
        deduped.append(entry)
    selected = deduped
    if len(selected) >= desired_count:
        return selected[:desired_count]

    remaining = [frame for frame in frames if frame.frame_id not in {item.frame.frame_id for item in selected}]
    while len(selected) < desired_count and remaining:
        pick_index = min(len(remaining) - 1, max(0, round((len(remaining) - 1) * (len(selected) / max(1, desired_count - 1)))))
        fallback_frame = remaining.pop(pick_index)
        selected.append(SelectedKeyframe(
            frame=fallback_frame,
            description=fallback_frame.label,
        ))
    return sorted(selected, key=lambda entry: entry.frame.time_ms)


def _find_closest_track_box(track: dict[str, Any] | None, time_ms: int) -> dict[str, Any] | None:
    if not isinstance(track, dict):
        return None
    frames = [frame for frame in (track.get('frames') or []) if isinstance(frame, dict) and isinstance(frame.get('box'), dict)]
    if not frames:
        return None
    closest = min(frames, key=lambda frame: abs(int(frame.get('timeMs') or 0) - time_ms))
    return closest.get('box') if isinstance(closest.get('box'), dict) else None


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