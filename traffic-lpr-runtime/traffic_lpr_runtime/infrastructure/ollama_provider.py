from __future__ import annotations

import json
import queue
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from traffic_lpr_runtime.application.ai_provider import VisionChatImage
from traffic_lpr_runtime.domain.errors import RuntimeFailure
from traffic_lpr_runtime.infrastructure.runtime_settings import DEFAULT_OLLAMA_TIMEOUT_S, get_runtime_settings


MIN_OLLAMA_TIMEOUT_S = 30
OLLAMA_PROGRESS_HEARTBEAT_S = 45.0
RETRYABLE_OLLAMA_HTTP_STATUS_CODES = frozenset({502, 503, 504})


def _resolve_timeout_seconds(value: int | str | None) -> int:
    if value is None or value == '':
        return DEFAULT_OLLAMA_TIMEOUT_S
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return DEFAULT_OLLAMA_TIMEOUT_S
    return max(MIN_OLLAMA_TIMEOUT_S, parsed)


def _is_timeout_reason(reason: object) -> bool:
    return isinstance(reason, (TimeoutError, socket.timeout)) or 'timed out' in str(reason).lower()


def _should_retry_http_error(code: int, detail: str) -> bool:
    if code in RETRYABLE_OLLAMA_HTTP_STATUS_CODES:
        return True
    lowered_detail = detail.lower()
    return 'err_ngrok_3004' in lowered_detail or 'ngrok gateway error' in lowered_detail


class OllamaVisionProvider:
    kind = 'ollama'

    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        settings = get_runtime_settings().ollama
        self._base_url = (base_url or settings.base_url).rstrip('/')
        self._model = model or settings.model
        self._timeout_s = settings.timeout_s
        self._retry_attempts = settings.retry_attempts
        self._retry_delay_s = settings.retry_delay_s

    def describe(self) -> dict[str, object]:
        return {
            'kind': self.kind,
            'baseUrl': self._base_url,
            'model': self._model,
            'defaultTimeoutS': self._timeout_s,
        }

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        images: list[VisionChatImage],
        timeout_s: int = DEFAULT_OLLAMA_TIMEOUT_S,
        request_metadata: dict[str, Any] | None = None,
        progress_callback: Callable[[], None] | None = None,
    ) -> dict[str, object]:
        del request_metadata
        resolved_timeout_s = _resolve_timeout_seconds(timeout_s or self._timeout_s)
        payload = {
            'model': self._model,
            'stream': False,
            'format': 'json',
            'messages': [
                {
                    'role': 'system',
                    'content': system_prompt,
                },
                {
                    'role': 'user',
                    'content': user_prompt,
                    'images': [image.image_base64 for image in images],
                },
            ],
            'options': {
                'temperature': 0.1,
            },
        }
        request = urllib.request.Request(
            f'{self._base_url}/api/chat',
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )

        for attempt in range(self._retry_attempts + 1):
            try:
                raw_response = _urlopen_with_heartbeat(
                    request,
                    resolved_timeout_s=resolved_timeout_s,
                    progress_callback=progress_callback,
                )
                break
            except urllib.error.HTTPError as error:
                detail = error.read().decode('utf-8', errors='replace').strip()
                if attempt < self._retry_attempts and _should_retry_http_error(error.code, detail):
                    time.sleep(self._retry_delay_s * (attempt + 1))
                    continue
                raise RuntimeFailure(
                    f'Ollama request failed with HTTP {error.code}: {detail or error.reason}.',
                ) from error
            except urllib.error.URLError as error:
                if _is_timeout_reason(error.reason):
                    raise RuntimeFailure(
                        f'Ollama request timed out after {resolved_timeout_s}s. Increase TRAFFIC_OLLAMA_TIMEOUT_S if the remote model is slow.',
                    ) from error
                raise RuntimeFailure(f'Unable to reach Ollama provider: {error.reason}.') from error
            except (TimeoutError, socket.timeout) as error:
                raise RuntimeFailure(
                    f'Ollama request timed out after {resolved_timeout_s}s. Increase TRAFFIC_OLLAMA_TIMEOUT_S if the remote model is slow.',
                ) from error
            except OSError as error:
                if _is_timeout_reason(error):
                    raise RuntimeFailure(
                        f'Ollama request timed out after {resolved_timeout_s}s. Increase TRAFFIC_OLLAMA_TIMEOUT_S if the remote model is slow.',
                    ) from error
                raise

        try:
            response_payload = json.loads(raw_response)
        except json.JSONDecodeError as error:
            raise RuntimeFailure(f'Ollama returned invalid JSON envelope: {error}.') from error

        if not isinstance(response_payload, dict):
            raise RuntimeFailure('Ollama response envelope must be a JSON object.')

        message = response_payload.get('message')
        if not isinstance(message, dict):
            raise RuntimeFailure('Ollama response did not contain a chat message payload.')

        content = message.get('content')
        if not isinstance(content, str) or not content.strip():
            raise RuntimeFailure('Ollama response did not contain any JSON content.')

        return _parse_json_object(content)


def _parse_json_object(content: str) -> dict[str, object]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = _repair_json_object(content)

    if not isinstance(parsed, dict):
        raise RuntimeFailure('Ollama JSON result must be an object.')
    return parsed


def _urlopen_with_heartbeat(
    request: urllib.request.Request,
    *,
    resolved_timeout_s: int,
    progress_callback: Callable[[], None] | None,
) -> str:
    result_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

    def perform_request() -> None:
        try:
            with urllib.request.urlopen(request, timeout=resolved_timeout_s) as response:
                result_queue.put(('response', response.read().decode('utf-8')))
        except Exception as error:  # pragma: no cover - exercised through public generate_json paths
            result_queue.put(('error', error))

    worker = threading.Thread(target=perform_request, daemon=True)
    worker.start()

    deadline = time.monotonic() + float(max(MIN_OLLAMA_TIMEOUT_S, resolved_timeout_s))
    heartbeat_interval_s = max(0.01, min(float(OLLAMA_PROGRESS_HEARTBEAT_S), float(resolved_timeout_s)))

    while True:
        remaining_s = deadline - time.monotonic()
        if remaining_s <= 0:
            raise TimeoutError(f'Ollama request timed out after {resolved_timeout_s}s.')

        try:
            kind, payload = result_queue.get(timeout=min(heartbeat_interval_s, remaining_s))
        except queue.Empty:
            if progress_callback is not None:
                progress_callback()
            continue

        if kind == 'response':
            return str(payload)
        raise payload


def _repair_json_object(content: str) -> dict[str, Any]:
    first_brace = content.find('{')
    last_brace = content.rfind('}')
    if first_brace == -1 or last_brace == -1 or last_brace <= first_brace:
        raise RuntimeFailure('Ollama returned malformed JSON that could not be repaired.')

    candidate = content[first_brace:last_brace + 1]
    try:
        repaired = json.loads(candidate)
    except json.JSONDecodeError as error:
        raise RuntimeFailure(f'Ollama returned malformed JSON that could not be repaired: {error}.') from error

    if not isinstance(repaired, dict):
        raise RuntimeFailure('Ollama repaired JSON result must be an object.')
    return repaired