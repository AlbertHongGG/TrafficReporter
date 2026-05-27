from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_benchmark.infrastructure.runtime_bridge_client import build_runtime_request_envelope, unwrap_runtime_response


class RuntimeBridgeProtocolTests(unittest.TestCase):
    def test_build_runtime_request_envelope_uses_shared_protocol_version(self) -> None:
        payload = build_runtime_request_envelope('benchmark-run', {'cases': []}, request_id='bench-001')

        self.assertEqual(payload['protocolVersion'], 1)
        self.assertEqual(payload['requestId'], 'bench-001')
        self.assertEqual(payload['subcommand'], 'benchmark-run')

    def test_unwrap_runtime_response_accepts_protocol_success_payload(self) -> None:
        result = unwrap_runtime_response({
            'protocolVersion': 1,
            'requestId': 'bench-002',
            'ok': True,
            'result': {'summary': 'ok'},
        })

        self.assertEqual(result, {'summary': 'ok'})


if __name__ == '__main__':
    unittest.main()