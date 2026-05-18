from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from traffic_lpr_runtime.application.ai_provider import VisionChatImage
from traffic_lpr_runtime.domain.errors import RuntimeFailure


DEFAULT_OLLAMA_BASE_URL = 'https://lacresha-posological-steven.ngrok-free.dev'
DEFAULT_OLLAMA_MODEL = 'qwen3.6:35b'


class OllamaVisionProvider:
    kind = 'ollama'

    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        self._base_url = (base_url or os.environ.get('TRAFFIC_OLLAMA_URL') or DEFAULT_OLLAMA_BASE_URL).rstrip('/')
        self._model = model or os.environ.get('TRAFFIC_OLLAMA_MODEL') or DEFAULT_OLLAMA_MODEL

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        images: list[VisionChatImage],
        timeout_s: int = 120,
    ) -> dict[str, object]:
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

        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                raw_response = response.read().decode('utf-8')
        except urllib.error.HTTPError as error:
            detail = error.read().decode('utf-8', errors='replace').strip()
            raise RuntimeFailure(
                f'Ollama request failed with HTTP {error.code}: {detail or error.reason}.',
            ) from error
        except urllib.error.URLError as error:
            raise RuntimeFailure(f'Unable to reach Ollama provider: {error.reason}.') from error

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