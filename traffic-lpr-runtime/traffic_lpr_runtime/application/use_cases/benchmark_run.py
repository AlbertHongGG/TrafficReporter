from __future__ import annotations

from typing import Any

from traffic_lpr_runtime.application.benchmark_workflow import BenchmarkRunWorkflow


class BenchmarkRunUseCase:
    name = 'benchmark-run'

    def __init__(self, workflow: BenchmarkRunWorkflow) -> None:
        self._workflow = workflow

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._workflow.run(payload)
