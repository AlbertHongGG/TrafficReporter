from __future__ import annotations

from typing import Any

from traffic_lpr_runtime.application.ai_evidence_workflow import AiEvidenceWorkflow


class AiEvidenceUseCase:
    name = 'ai-evidence'

    def __init__(self, workflow: AiEvidenceWorkflow) -> None:
        self._workflow = workflow

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._workflow.run(payload)
