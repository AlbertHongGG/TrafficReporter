from __future__ import annotations

import io
import json
import sys
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.application.ai_provider import VisionChatImage
from traffic_lpr_runtime.domain.errors import RuntimeFailure
from traffic_lpr_runtime.infrastructure.ollama_provider import OllamaVisionProvider


class _ResponseStub:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> _ResponseStub:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        del exc_type, exc, tb
        return False

    def read(self) -> bytes:
        return self._payload


def _http_error(*, code: int, body: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url='https://example.test/api/chat',
        code=code,
        msg='HTTP error',
        hdrs=None,
        fp=io.BytesIO(body.encode('utf-8')),
    )


class OllamaVisionProviderTests(unittest.TestCase):
    def test_generate_json_retries_retryable_gateway_error_once(self) -> None:
        provider = OllamaVisionProvider(base_url='https://example.test', model='unit-test-model')
        retryable_error = _http_error(
            code=503,
            body='ngrok gateway error\nThe server returned an invalid or incomplete HTTP response.\r\n\r\nERR_NGROK_3004.',
        )
        success_response = _ResponseStub(
            json.dumps({'message': {'content': json.dumps({'decision': 'accept'})}}).encode('utf-8'),
        )

        with patch('traffic_lpr_runtime.infrastructure.ollama_provider.time.sleep') as sleep_mock:
            with patch(
                'traffic_lpr_runtime.infrastructure.ollama_provider.urllib.request.urlopen',
                side_effect=[retryable_error, success_response],
            ) as urlopen_mock:
                result = provider.generate_json(
                    system_prompt='sys',
                    user_prompt='user',
                    images=[VisionChatImage(frame_id='fine-001', label='fine', image_base64='YWJj')],
                )

        self.assertEqual(result, {'decision': 'accept'})
        self.assertEqual(urlopen_mock.call_count, 2)
        sleep_mock.assert_called_once()

    def test_generate_json_does_not_retry_non_retryable_http_error(self) -> None:
        provider = OllamaVisionProvider(base_url='https://example.test', model='unit-test-model')
        fatal_error = _http_error(code=400, body='bad request')

        with patch('traffic_lpr_runtime.infrastructure.ollama_provider.time.sleep') as sleep_mock:
            with patch(
                'traffic_lpr_runtime.infrastructure.ollama_provider.urllib.request.urlopen',
                side_effect=fatal_error,
            ) as urlopen_mock:
                with self.assertRaises(RuntimeFailure) as context:
                    provider.generate_json(
                        system_prompt='sys',
                        user_prompt='user',
                        images=[VisionChatImage(frame_id='fine-001', label='fine', image_base64='YWJj')],
                    )

        self.assertIn('HTTP 400', str(context.exception))
        self.assertEqual(urlopen_mock.call_count, 1)
        sleep_mock.assert_not_called()

    def test_generate_json_emits_heartbeat_while_waiting_for_slow_response(self) -> None:
        provider = OllamaVisionProvider(base_url='https://example.test', model='unit-test-model')
        heartbeat_count = 0

        def slow_urlopen(request, timeout):
            del request, timeout
            time.sleep(0.035)
            return _ResponseStub(
                json.dumps({'message': {'content': json.dumps({'decision': 'accept'})}}).encode('utf-8'),
            )

        with patch('traffic_lpr_runtime.infrastructure.ollama_provider.OLLAMA_PROGRESS_HEARTBEAT_S', 0.01):
            with patch(
                'traffic_lpr_runtime.infrastructure.ollama_provider.urllib.request.urlopen',
                side_effect=slow_urlopen,
            ):
                def on_heartbeat() -> None:
                    nonlocal heartbeat_count
                    heartbeat_count += 1

                result = provider.generate_json(
                    system_prompt='sys',
                    user_prompt='user',
                    images=[VisionChatImage(frame_id='fine-001', label='fine', image_base64='YWJj')],
                    progress_callback=on_heartbeat,
                )

        self.assertEqual(result, {'decision': 'accept'})
        self.assertGreaterEqual(heartbeat_count, 1)


if __name__ == '__main__':
    unittest.main()