from __future__ import annotations

import base64
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from traffic_lpr_runtime.application.ai_provider import VisionChatImage, VisionLlmProvider
from traffic_lpr_runtime.domain.errors import RuntimeFailure
from traffic_lpr_runtime.domain.models import TrackedRegion
from traffic_lpr_runtime.domain.value_objects import NormalizedRect, crop_image


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


class AiEvidenceWorkflow:
    def __init__(
        self,
        *,
        ensure_ready: Callable[[], None],
        status: Callable[[], dict[str, Any]],
        runtime_root: Callable[[], Path],
        dependencies: Any,
        frame_reader: Any,
        detect_targets: Callable[[Any, int, str, NormalizedRect | None], list[TrackedRegion]],
        analyze_frame: Callable[[dict[str, Any]], dict[str, Any]],
        analyze_interval: Callable[[dict[str, Any]], dict[str, Any]],
        provider: VisionLlmProvider,
    ) -> None:
        self._ensure_ready = ensure_ready
        self._status = status
        self._runtime_root = runtime_root
        self._dependencies = dependencies
        self._frame_reader = frame_reader
        self._detect_targets = detect_targets
        self._analyze_frame = analyze_frame
        self._analyze_interval = analyze_interval
        self._provider = provider

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        description = str(payload.get('description') or '').strip()
        if not description:
            raise RuntimeFailure('AI evidence analysis requires a non-empty natural-language description.')

        request_id = _optional_string(payload.get('requestId')) or f'ai-evidence-{int(time.time() * 1000)}'
        artifact_root = self._resolve_artifact_root(request_id)
        source_path = str(payload['sourcePath'])
        marker_rect = NormalizedRect.from_payload(payload.get('markerRect'))
        duration_ms = self._probe_duration_ms(source_path)
        target_vehicle_kind = str(payload.get('targetVehicleKind') or 'vehicle')
        country_hints = [str(value) for value in (payload.get('countryHints') or []) if str(value).strip()]
        analysis_profile_id = _optional_string(payload.get('analysisProfileId'))
        enable_developer_diagnostics = bool(payload.get('enableDeveloperDiagnostics'))
        max_keyframes = max(8, min(10, int(payload.get('maxKeyframes') or 8)))
        coarse_step_ms = max(1000, int(payload.get('coarseSampleEveryMs') or 4000))
        fine_padding_ms = max(1000, int(payload.get('fineWindowPaddingMs') or 2000))

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
            func=lambda: self._select_coarse_interval(description, coarse_frames),
        )

        fine_start_ms = max(0, coarse_choice['startFrame']['timeMs'] - fine_padding_ms)
        fine_end_ms = min(duration_ms, coarse_choice['endFrame']['timeMs'] + fine_padding_ms)
        if fine_end_ms <= fine_start_ms:
            fine_end_ms = min(duration_ms, fine_start_ms + max(fine_padding_ms * 2, 1000))

        fine_step_ms = _resolve_fine_step_ms(
            start_ms=fine_start_ms,
            end_ms=fine_end_ms,
            requested_step_ms=int(payload.get('fineSampleEveryMs') or 500),
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
            func=lambda: self._select_fine_interval(description, fine_frames, max_keyframes),
        )

        planned_interval = {
            'startMs': int(fine_choice['startFrame']['timeMs']),
            'endMs': int(fine_choice['endFrame']['timeMs']),
        }
        if planned_interval['endMs'] < planned_interval['startMs']:
            planned_interval = {
                'startMs': planned_interval['endMs'],
                'endMs': planned_interval['startMs'],
            }

        anchor_frame = fine_choice['anchorFrame']
        target_resolution = self._record_tool_call(
            tool_calls,
            stage='resolve-target',
            tool_name='llm-resolve-target',
            input_summary=f'anchor={anchor_frame.frame_id} timeMs={anchor_frame.time_ms}',
            func=lambda: self._resolve_target(
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
            func=lambda: self._analyze_interval({
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

        projection = self._build_projection(interval_result, planned_interval)
        plate_candidate = _resolve_plate_candidate(projection['candidates'], projection['acceptedCandidateId'])
        keyframes = self._record_tool_call(
            tool_calls,
            stage='render',
            tool_name='render-keyframes',
            input_summary=f'keyframes={len(fine_choice["keyframes"])}',
            func=lambda: self._render_keyframes(
                source_path=source_path,
                keyframe_refs=fine_choice['keyframes'],
                analysis_track=projection['analysisTrack'],
                output_dir=artifact_root / 'keyframes',
            ),
        )

        summary = fine_choice['summary'] or _build_summary(description, planned_interval, plate_candidate)
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
        artifact_root = self._runtime_root() / '.runtime' / 'ai-evidence' / request_id
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

    def _select_coarse_interval(self, description: str, frames: list[RenderedFrame]) -> dict[str, Any]:
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
        )
        return {
            'startFrame': _resolve_frame_ref(response.get('startFrameId'), frames),
            'endFrame': _resolve_frame_ref(response.get('endFrameId'), frames),
            'anchorFrame': _resolve_frame_ref(response.get('anchorFrameId'), frames),
            'summary': str(response.get('summary') or '').strip(),
        }

    def _select_fine_interval(
        self,
        description: str,
        frames: list[RenderedFrame],
        max_keyframes: int,
    ) -> dict[str, Any]:
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
        )
        start_frame = _resolve_frame_ref(response.get('startFrameId'), frames)
        end_frame = _resolve_frame_ref(response.get('endFrameId'), frames)
        anchor_frame = _resolve_frame_ref(response.get('anchorFrameId'), frames)
        keyframe_refs = _normalize_keyframes(response.get('keyframes'), frames, desired_count=max_keyframes)
        return {
            'startFrame': start_frame,
            'endFrame': end_frame,
            'anchorFrame': anchor_frame,
            'summary': str(response.get('summary') or '').strip(),
            'keyframes': keyframe_refs,
        }

    def _resolve_target(
        self,
        *,
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
        detections = self._detect_targets(frame, anchor_frame.time_ms, target_vehicle_kind, marker_rect)
        if not detections:
            raise RuntimeFailure('AI evidence target resolution found no detectable targets on the selected anchor frame.')

        detections = sorted(detections, key=lambda detection: detection.confidence, reverse=True)[:6]
        annotated_path, frame_width, frame_height = self._render_detection_reference(frame, detections, output_dir)
        detection_payloads: list[dict[str, Any]] = []
        chat_images = [VisionChatImage(
            frame_id='anchor-overview',
            label=f'anchor-overview @ T+{_format_time_label(anchor_frame.time_ms)}',
            image_base64=self._encode_chat_image(annotated_path),
        )]
        plate_hint = _extract_plate_hint(description)

        for index, detection in enumerate(detections):
            crop_path = output_dir / f'target-{index:02d}.jpg'
            crop = crop_image(frame, detection.box)
            rendered_crop, crop_width, crop_height = self._prepare_frame_image(
                crop,
                title=f'target-{index:02d}',
                subtitle=f'T+{_format_time_label(anchor_frame.time_ms)}',
            )
            self._write_image(crop_path, rendered_crop)
            frame_result = self._analyze_frame({
                'sourcePath': source_path,
                'timeMs': anchor_frame.time_ms,
                'markerRect': marker_rect.to_payload() if marker_rect else None,
                'targetVehicleKind': target_vehicle_kind,
                'selectedTargetBox': detection.box.to_payload(),
                'countryHints': country_hints,
                'analysisProfileId': analysis_profile_id,
                'enableDeveloperDiagnostics': enable_developer_diagnostics,
                'requestId': f'{anchor_frame.frame_id}-target-{index:02d}',
            })
            best_candidate = _resolve_plate_candidate(frame_result.get('candidates') or [], frame_result.get('acceptedCandidateId'))
            detection_payloads.append({
                'trackId': detection.id,
                'label': f'target-{index:02d}',
                'className': detection.class_name,
                'confidence': detection.confidence,
                'normalizedBox': detection.box.to_payload(),
                'selectedBox': self._overlay_payload(detection.box, frame_width, frame_height),
                'topPlateText': best_candidate['text'] if isinstance(best_candidate, dict) else None,
                'topPlateConfidence': best_candidate['confidence'] if isinstance(best_candidate, dict) else None,
                'acceptedCandidateId': frame_result.get('acceptedCandidateId'),
                'candidates': frame_result.get('candidates') or [],
                'cropImagePath': str(crop_path),
                'cropFrameWidth': crop_width,
                'cropFrameHeight': crop_height,
            })
            chat_images.append(VisionChatImage(
                frame_id=detection.id,
                label=f'target-{index:02d} @ T+{_format_time_label(anchor_frame.time_ms)}',
                image_base64=self._encode_chat_image(crop_path),
            ))

        if plate_hint:
            for detection_payload in detection_payloads:
                for candidate in detection_payload['candidates']:
                    candidate_text = str(candidate.get('text') or '')
                    if _normalize_plate(candidate_text) == plate_hint:
                        return {
                            'anchorFrameId': anchor_frame.frame_id,
                            'selectedTrackId': detection_payload['trackId'],
                            'selectedCandidateId': candidate.get('id'),
                            'confidence': 0.99,
                            'rationale': f'直接匹配描述中的車牌號碼 {candidate_text}。',
                            'selectedBox': detection_payload['selectedBox'],
                        }

        system_prompt = (
            '你是交通事件 target resolver。你必須只從提供的候選 target IDs 中選出最符合描述的目標。'
            '請結合 anchor overview、各個 target crop、以及系統提供的 OCR 提示判斷。只輸出 JSON。'
        )
        detection_list = '\n'.join(
            f'- {payload["trackId"]} ({payload["label"]}) class={payload["className"]} '
            f'ocr={payload["topPlateText"] or "--"} conf={payload["topPlateConfidence"] or 0:.3f}'
            for payload in detection_payloads
        )
        user_prompt = (
            f'使用者描述:\n{description}\n\n'
            f'anchor frame: {anchor_frame.frame_id} @ T+{_format_time_label(anchor_frame.time_ms)}\n\n'
            f'候選 target:\n{detection_list}\n\n'
            '請輸出 JSON:\n'
            '{"selectedTrackId":"...","confidence":0.0,"rationale":"..."}'
        )
        response = self._provider.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            images=chat_images,
        )
        selected_track_id = _optional_string(response.get('selectedTrackId'))
        selected_payload = next((payload for payload in detection_payloads if payload['trackId'] == selected_track_id), None)
        if selected_payload is None:
            selected_payload = detection_payloads[0]
            selected_track_id = selected_payload['trackId']

        return {
            'anchorFrameId': anchor_frame.frame_id,
            'selectedTrackId': selected_track_id,
            'selectedCandidateId': selected_payload.get('acceptedCandidateId'),
            'confidence': float(response.get('confidence') or 0.5),
            'rationale': str(response.get('rationale') or f'預設選擇 {selected_payload["label"]}。').strip(),
            'selectedBox': selected_payload['selectedBox'],
        }

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
        keyframe_refs: list[dict[str, Any]],
        analysis_track: dict[str, Any] | None,
        output_dir: Path,
    ) -> list[dict[str, Any]]:
        output_dir.mkdir(parents=True, exist_ok=True)
        rendered_keyframes: list[dict[str, Any]] = []
        for keyframe in keyframe_refs:
            rendered_frame = keyframe['frame']
            frame = self._frame_reader.read_frame(source_path, rendered_frame.time_ms)
            box = _find_closest_track_box(analysis_track, rendered_frame.time_ms)
            title = rendered_frame.frame_id
            subtitle = f'T+{_format_time_label(rendered_frame.time_ms)}'
            annotated, frame_width, frame_height = self._prepare_frame_image(frame, title=title, subtitle=subtitle, box=box)
            output_path = output_dir / f'{rendered_frame.frame_id}.jpg'
            self._write_image(output_path, annotated)
            rendered_keyframes.append({
                'frame': rendered_frame.to_payload(image_path=str(output_path)),
                'description': str(keyframe.get('description') or rendered_frame.label),
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

    def _build_projection(self, interval_result: dict[str, Any], interval: dict[str, Any]) -> dict[str, Any]:
        target_tracks = interval_result.get('targetTracks') or []
        analysis_track = target_tracks[0] if target_tracks else None
        return {
            'interval': interval,
            'targetTracks': target_tracks,
            'analysisTrack': analysis_track,
            'selectedTargetTrackId': analysis_track.get('id') if isinstance(analysis_track, dict) else None,
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


def _normalize_keyframes(value: Any, frames: list[RenderedFrame], *, desired_count: int) -> list[dict[str, Any]]:
    by_id = {frame.frame_id: frame for frame in frames}
    selected: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        frame_id = item.get('frameId') if isinstance(item, dict) else item if isinstance(item, str) else None
        if isinstance(frame_id, str) and frame_id in by_id:
            selected.append({
                'frame': by_id[frame_id],
                'description': str(item.get('description') or by_id[frame_id].label) if isinstance(item, dict) else by_id[frame_id].label,
            })
    selected = list(OrderedDict((entry['frame'].frame_id, entry) for entry in selected).values())
    if len(selected) >= desired_count:
        return selected[:desired_count]

    remaining = [frame for frame in frames if frame.frame_id not in {item['frame'].frame_id for item in selected}]
    while len(selected) < desired_count and remaining:
        pick_index = min(len(remaining) - 1, max(0, round((len(remaining) - 1) * (len(selected) / max(1, desired_count - 1)))))
        fallback_frame = remaining.pop(pick_index)
        selected.append({
            'frame': fallback_frame,
            'description': fallback_frame.label,
        })
    return sorted(selected, key=lambda entry: entry['frame'].time_ms)


def _find_closest_track_box(track: dict[str, Any] | None, time_ms: int) -> dict[str, Any] | None:
    if not isinstance(track, dict):
        return None
    frames = [frame for frame in (track.get('frames') or []) if isinstance(frame, dict) and isinstance(frame.get('box'), dict)]
    if not frames:
        return None
    closest = min(frames, key=lambda frame: abs(int(frame.get('timeMs') or 0) - time_ms))
    return closest.get('box') if isinstance(closest.get('box'), dict) else None


def _resolve_plate_candidate(candidates: list[dict[str, Any]], accepted_candidate_id: Any) -> dict[str, Any] | None:
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


def _extract_plate_hint(description: str) -> str | None:
    match = re.search(r'([A-Z0-9]{2,4}-?[A-Z0-9]{2,4})', description.upper())
    if not match:
        return None
    return _normalize_plate(match.group(1))


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


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