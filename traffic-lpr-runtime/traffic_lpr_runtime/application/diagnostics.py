from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from traffic_lpr_runtime.application.analysis_policy import ResolvedIntervalAnalysisPolicy


@dataclass(frozen=True, slots=True)
class RuntimeStageTiming:
    tracking_ms: float
    sample_analysis_ms: float
    temporal_support_ms: float
    fusion_ms: float
    total_ms: float
    temporal_support_budget: int
    temporal_support_samples_used: int

    def to_payload(self) -> dict[str, float | int]:
        return {
            'trackingMs': self.tracking_ms,
            'sampleAnalysisMs': self.sample_analysis_ms,
            'temporalSupportMs': self.temporal_support_ms,
            'fusionMs': self.fusion_ms,
            'totalMs': self.total_ms,
            'temporalSupportBudget': self.temporal_support_budget,
            'temporalSupportSamplesUsed': self.temporal_support_samples_used,
        }


@dataclass(frozen=True, slots=True)
class IntervalAnalysisDiagnostics:
    analysis_options: dict[str, Any]
    analysis_policy: ResolvedIntervalAnalysisPolicy
    artifact_root: str | None
    tracker: dict[str, Any]
    tracking_summary: dict[str, Any]
    sequence: dict[str, Any]
    fusion: dict[str, Any]
    selection: dict[str, Any]
    timing: RuntimeStageTiming

    def to_payload(self) -> dict[str, Any]:
        return {
            'analysisOptions': self.analysis_options,
            'analysisPolicy': self.analysis_policy.to_payload(),
            'artifactRoot': self.artifact_root,
            'tracker': self.tracker,
            'trackingSummary': self.tracking_summary,
            'sequence': self.sequence,
            'fusion': self.fusion,
            'selection': self.selection,
            'timing': self.timing.to_payload(),
        }