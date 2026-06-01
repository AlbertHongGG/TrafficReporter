from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from traffic_lpr_runtime.application.ai_provider import VisionChatImage, VisionLlmProvider
from traffic_lpr_runtime.infrastructure.runtime_layout import build_run_id


class JsonFileAiCallLogger:
    def __init__(self, runs_root: Path) -> None:
        self._runs_root = runs_root

    def record(
        self,
        entry: dict[str, Any],
        *,
        started_at_ms: int,
        provider_kind: str,
        run_id: str,
        stage_label: str | None = None,
    ) -> Path:
        timestamp = datetime.fromtimestamp(started_at_ms / 1000.0)
        day_dir = self._runs_root / run_id / 'ai-logs'
        day_dir.mkdir(parents=True, exist_ok=True)
        file_name_parts = [timestamp.strftime('%H%M%S_%f')[:-3]]
        if stage_label:
            file_name_parts.append(stage_label)
        file_name_parts.extend([_slugify(provider_kind), entry['callId']])
        file_name = f'{"_".join(file_name_parts)}.json'
        output_path = day_dir / file_name
        output_path.write_text(
            json.dumps(_json_safe(entry), ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        return output_path


class LoggingVisionLlmProvider:
    def __init__(self, inner: VisionLlmProvider, logger: JsonFileAiCallLogger) -> None:
        self._inner = inner
        self._logger = logger

    @property
    def kind(self) -> str:
        return self._inner.kind

    def describe(self) -> dict[str, object]:
        metadata = self._inner.describe()
        return metadata if isinstance(metadata, dict) else {'kind': self.kind}

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        images: list[VisionChatImage],
        timeout_s: int = 1200,
        request_metadata: dict[str, Any] | None = None,
        progress_callback: Callable[[], None] | None = None,
    ) -> dict[str, object]:
        started_at_ms = _now_ms()
        call_id = uuid4().hex
        resolved_run_id = _extract_run_id(request_metadata)
        resolved_stage_label = _extract_stage_label(request_metadata)
        request_payload = {
            'systemPrompt': system_prompt,
            'userPrompt': user_prompt,
            'timeoutS': int(timeout_s),
            'imageCount': len(images),
            'images': [_image_payload(image) for image in images],
            'metadata': _json_safe(request_metadata or {}),
        }

        try:
            response = self._inner.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                images=images,
                timeout_s=timeout_s,
                request_metadata=request_metadata,
                progress_callback=progress_callback,
            )
        except Exception as error:
            completed_at_ms = _now_ms()
            self._logger.record(
                {
                    'logVersion': 1,
                    'callId': call_id,
                    'status': 'failed',
                    'provider': _json_safe(self.describe()),
                    'timing': _timing_payload(started_at_ms, completed_at_ms),
                    'request': request_payload,
                    'response': None,
                    'error': {
                        'type': type(error).__name__,
                        'message': str(error),
                    },
                },
                started_at_ms=started_at_ms,
                provider_kind=self.kind,
                run_id=resolved_run_id,
                stage_label=resolved_stage_label,
            )
            raise

        completed_at_ms = _now_ms()
        self._logger.record(
            {
                'logVersion': 1,
                'callId': call_id,
                'status': 'succeeded',
                'provider': _json_safe(self.describe()),
                'timing': _timing_payload(started_at_ms, completed_at_ms),
                'request': request_payload,
                'response': _json_safe(response),
                'error': None,
            },
            started_at_ms=started_at_ms,
            provider_kind=self.kind,
            run_id=resolved_run_id,
            stage_label=resolved_stage_label,
        )
        return response


def _timing_payload(started_at_ms: int, completed_at_ms: int) -> dict[str, int]:
    return {
        'startedAtMs': started_at_ms,
        'completedAtMs': completed_at_ms,
        'durationMs': max(0, completed_at_ms - started_at_ms),
    }


def _image_payload(image: VisionChatImage) -> dict[str, Any]:
    encoded_bytes = image.image_base64.encode('ascii', errors='ignore')
    return {
        'frameId': image.frame_id,
        'label': image.label,
        'imageBase64': image.image_base64,
        'imageBase64Length': len(image.image_base64),
        'imageSha256': hashlib.sha256(encoded_bytes).hexdigest(),
    }


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _extract_run_id(request_metadata: dict[str, Any] | None) -> str:
    if isinstance(request_metadata, dict):
        for key in ('runId', 'requestId'):
            value = request_metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return build_run_id()


def _extract_stage_label(request_metadata: dict[str, Any] | None) -> str | None:
    if not isinstance(request_metadata, dict):
        return None

    raw_stage = request_metadata.get('stage')
    if not isinstance(raw_stage, str) or not raw_stage.strip():
        return None

    stage = raw_stage.strip().lower()
    if stage in {'coarse', 'fine', 'target'}:
        return stage
    if 'coarse' in stage:
        return 'coarse'
    if 'fine' in stage or 'keyframe' in stage:
        return 'fine'
    if 'target' in stage:
        return 'target'
    return _slugify(stage)


def _slugify(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-') or 'provider'


def _now_ms() -> int:
    return time.time_ns() // 1_000_000