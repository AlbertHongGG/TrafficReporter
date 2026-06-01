from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.domain.errors import RuntimeFailure
from traffic_lpr_runtime.protocol import (
    LEGACY_RUNTIME_PROTOCOL_VERSION,
    VNEXT_RUNTIME_PROTOCOL_VERSION,
    RuntimeRequestContext,
    build_runtime_progress,
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

    def test_build_runtime_progress_wraps_progress_payload_with_request_context(self) -> None:
        payload = build_runtime_progress(
            {
                'progress': 0.42,
                'stage': 'Interval',
                'detail': 'Analyzing tracked sample 2/5.',
                'done': False,
                'failed': False,
                'trackingTier': 'partial',
                'coverageRatio': 0.4,
            },
            request_context=RuntimeRequestContext(
                protocol_mode=True,
                protocol_version=LEGACY_RUNTIME_PROTOCOL_VERSION,
                request_id='req-004',
                idempotency_key=None,
            ),
        )

        self.assertEqual(payload['kind'], 'progress')
        self.assertEqual(payload['requestId'], 'req-004')
        self.assertEqual(payload['progress']['requestId'], 'req-004')
        self.assertEqual(payload['progress']['trackingTier'], 'partial')

    def test_build_runtime_progress_stringifies_numeric_request_id_for_payload(self) -> None:
        payload = build_runtime_progress(
            {
                'progress': 0.1,
                'stage': 'Interval',
                'detail': 'Validating the anchor frame and starting interval tracking.',
                'done': False,
                'failed': False,
            },
            request_context=RuntimeRequestContext(
                protocol_mode=True,
                protocol_version=LEGACY_RUNTIME_PROTOCOL_VERSION,
                request_id=1,
                idempotency_key=None,
            ),
        )

        self.assertEqual(payload['requestId'], 1)
        self.assertEqual(payload['progress']['requestId'], '1')


if __name__ == '__main__':
    unittest.main()
