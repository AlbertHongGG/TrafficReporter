from __future__ import annotations

from typing import Any

from traffic_lpr_runtime.application.services.analysis.interval_service import (
    IntervalAnalysisDependencies,
    IntervalAnalysisService,
)


class AnalyzeIntervalUseCase:
    name = 'analyze-interval'

    def __init__(self, service: IntervalAnalysisService) -> None:
        self._service = service

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._service.run(payload)
