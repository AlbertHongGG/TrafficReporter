from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.application.ai_provider import VisionChatImage
from traffic_lpr_runtime.domain.errors import RuntimeFailure
from traffic_lpr_runtime.infrastructure.ai_logging import JsonFileAiCallLogger, LoggingVisionLlmProvider


class ProviderStub:
    kind = 'stub'

    def __init__(self, *, response: dict[str, object] | None = None, error: Exception | None = None) -> None:
        self._response = response or {'ok': True}
        self._error = error

    def describe(self) -> dict[str, object]:
        return {
            'kind': self.kind,
            'model': 'stub-model',
        }

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        images: list[VisionChatImage],
        timeout_s: int = 1200,
        request_metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        del system_prompt, user_prompt, images, timeout_s, request_metadata
        if self._error is not None:
            raise self._error
        return dict(self._response)


class AiLoggingTests(unittest.TestCase):
    def test_logging_provider_records_success_with_parsed_response(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = LoggingVisionLlmProvider(
                inner=ProviderStub(response={'decision': 'accept', 'score': 0.98}),
                logger=JsonFileAiCallLogger(Path(temp_dir)),
            )

            result = provider.generate_json(
                system_prompt='sys',
                user_prompt='user',
                images=[VisionChatImage(frame_id='fine-001', label='fine', image_base64='YWJj')],
                request_metadata={'workflow': 'ai-evidence', 'stage': 'select-keyframes'},
            )

            self.assertEqual(result, {'decision': 'accept', 'score': 0.98})
            log_files = list(Path(temp_dir).rglob('*.json'))
            self.assertEqual(len(log_files), 1)

            payload = json.loads(log_files[0].read_text(encoding='utf-8'))
            self.assertEqual(payload['status'], 'succeeded')
            self.assertEqual(payload['provider']['model'], 'stub-model')
            self.assertEqual(payload['request']['metadata']['stage'], 'select-keyframes')
            self.assertEqual(payload['request']['images'][0]['frameId'], 'fine-001')
            self.assertEqual(payload['response'], {'decision': 'accept', 'score': 0.98})

    def test_logging_provider_records_failures_before_reraising(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = LoggingVisionLlmProvider(
                inner=ProviderStub(error=RuntimeFailure('boom')),
                logger=JsonFileAiCallLogger(Path(temp_dir)),
            )

            with self.assertRaises(RuntimeFailure):
                provider.generate_json(
                    system_prompt='sys',
                    user_prompt='user',
                    images=[VisionChatImage(frame_id='fine-001', label='fine', image_base64='YWJj')],
                    request_metadata={'workflow': 'ai-evidence', 'stage': 'resolve-target'},
                )

            log_files = list(Path(temp_dir).rglob('*.json'))
            self.assertEqual(len(log_files), 1)

            payload = json.loads(log_files[0].read_text(encoding='utf-8'))
            self.assertEqual(payload['status'], 'failed')
            self.assertEqual(payload['error']['type'], 'RuntimeFailure')
            self.assertEqual(payload['error']['message'], 'boom')
            self.assertIsNone(payload['response'])


if __name__ == '__main__':
    unittest.main()