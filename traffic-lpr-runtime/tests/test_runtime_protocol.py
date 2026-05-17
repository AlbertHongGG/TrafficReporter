from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.entrypoints.cli import _unwrap_protocol_request
from traffic_lpr_runtime.domain.errors import RuntimeFailure


class RuntimeProtocolTests(unittest.TestCase):
    def test_unwrap_protocol_request_accepts_versioned_envelope(self) -> None:
        payload, protocol_mode, request_id = _unwrap_protocol_request(
            '{"protocolVersion": 1, "requestId": "req-001", "subcommand": "benchmark-run", "payload": {"cases": []}}',
            'benchmark-run',
            require_protocol=True,
        )

        self.assertTrue(protocol_mode)
        self.assertEqual(request_id, 'req-001')
        self.assertEqual(payload, {'cases': []})

    def test_unwrap_protocol_request_rejects_missing_protocol_when_required(self) -> None:
        with self.assertRaises(RuntimeFailure):
            _unwrap_protocol_request('{"cases": []}', 'benchmark-run', require_protocol=True)


if __name__ == '__main__':
    unittest.main()
