from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.domain.errors import RuntimeFailure
from traffic_lpr_runtime.protocol import (
    LEGACY_RUNTIME_PROTOCOL_VERSION,
    VNEXT_RUNTIME_PROTOCOL_VERSION,
    build_runtime_request_envelope,
    unwrap_runtime_request,
)


class RuntimeProtocolTests(unittest.TestCase):
    def test_unwrap_protocol_request_accepts_versioned_envelope(self) -> None:
        payload, request_context = unwrap_runtime_request(
            '{"protocolVersion": 1, "requestId": "req-001", "subcommand": "benchmark-run", "payload": {"cases": []}}',
            'benchmark-run',
            require_protocol=True,
            accepted_versions=(LEGACY_RUNTIME_PROTOCOL_VERSION,),
            error_factory=RuntimeFailure,
        )

        self.assertTrue(request_context.protocol_mode)
        self.assertEqual(request_context.request_id, 'req-001')
        self.assertEqual(payload, {'cases': []})

    def test_unwrap_protocol_request_rejects_missing_protocol_when_required(self) -> None:
        with self.assertRaises(RuntimeFailure):
            unwrap_runtime_request(
                '{"cases": []}',
                'benchmark-run',
                require_protocol=True,
                accepted_versions=(LEGACY_RUNTIME_PROTOCOL_VERSION,),
                error_factory=RuntimeFailure,
            )

    def test_build_runtime_request_envelope_requires_idempotency_key_for_v2(self) -> None:
        with self.assertRaises(ValueError):
            build_runtime_request_envelope(
                'analyze-interval',
                {'interval': {'startMs': 0, 'endMs': 1000}},
                request_id='req-002',
                protocol_version=VNEXT_RUNTIME_PROTOCOL_VERSION,
                idempotency_key='',
            )

    def test_build_runtime_request_envelope_adds_idempotency_key_for_v2(self) -> None:
        payload = build_runtime_request_envelope(
            'analyze-interval',
            {'interval': {'startMs': 0, 'endMs': 1000}},
            request_id='req-003',
            protocol_version=VNEXT_RUNTIME_PROTOCOL_VERSION,
            idempotency_key='idem-003',
        )

        self.assertEqual(payload['protocolVersion'], VNEXT_RUNTIME_PROTOCOL_VERSION)
        self.assertEqual(payload['idempotencyKey'], 'idem-003')


if __name__ == '__main__':
    unittest.main()
