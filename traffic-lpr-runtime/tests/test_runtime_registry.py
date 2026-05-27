from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.domain.errors import RuntimeFailure
from traffic_lpr_runtime.vnext import CallableRuntimeUseCase, RuntimeUseCaseRegistry


class RuntimeUseCaseRegistryTests(unittest.TestCase):
    def test_runs_registered_use_case(self) -> None:
        registry = RuntimeUseCaseRegistry([
            CallableRuntimeUseCase(name='status', handler=lambda payload: payload | {'ok': True}),
        ])

        result = registry.run('status', {'available': True})

        self.assertEqual(result, {'available': True, 'ok': True})

    def test_rejects_duplicate_registration(self) -> None:
        registry = RuntimeUseCaseRegistry()
        registry.register(CallableRuntimeUseCase(name='status', handler=lambda payload: payload))

        with self.assertRaises(RuntimeFailure):
            registry.register(CallableRuntimeUseCase(name='status', handler=lambda payload: payload))


if __name__ == '__main__':
    unittest.main()