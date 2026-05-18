from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from traffic_lpr_runtime.application.ai_provider import VisionChatImage, VisionLlmProvider


class JsonFileAiCallLogger:
    def __init__(self, logs_root: Path) -> None:
        self._logs_root = logs_root

    def record(self, entry: dict[str, Any], *, started_at_ms: int, provider_kind: str) -> Path:
        timestamp = datetime.fromtimestamp(started_at_ms / 1000.0, tz=timezone.utc)
        day_dir = self._logs_root / timestamp.strftime('%Y-%m-%d')
        day_dir.mkdir(parents=True, exist_ok=True)
        file_name = f'{timestamp.strftime("%H%M%S_%f")[:-3]}_{_slugify(provider_kind)}_{entry["callId"]}.json'
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
    ) -> dict[str, object]:
        started_at_ms = _now_ms()
        call_id = uuid4().hex
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


def _slugify(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-') or 'provider'


def _now_ms() -> int:
    return time.time_ns() // 1_000_000