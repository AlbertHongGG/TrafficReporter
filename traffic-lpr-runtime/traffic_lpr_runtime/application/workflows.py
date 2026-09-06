from __future__ import annotations

from typing import Any, Callable
from pathlib import Path

from traffic_lpr_runtime.application.services.tracking.calibration import (
    _anchor_status,
    _boxes_remain_anchored,
    _build_tracking_summary,
    _resolve_analysis_target_box,
    _resolve_interval_anchor_box,
    _selected_target_track_id,
    _tracking_advisory_reasons,
    _tracking_identity_review_reasons,
    _tracking_tier,
)
from traffic_lpr_runtime.application.services.tracking.evidence_frames import (
    _is_evidence_sample_frame,
    _mark_selected_for_evidence_analysis,
    _resolve_temporal_support_budget,
    _resolve_temporal_support_reason,
    _select_interval_evidence_frames,
    _select_temporal_support_frames,
)
from traffic_lpr_runtime.application.services.fusion.review_decision import (
    _build_decision_trace,
    _build_sample_selection_payload,
    _decision_source_for_candidate,
    _merge_reasons,
    _request_run_id,
    _safe_int,
    _sequence_advisory_reasons,
    _sequence_hard_review_reasons,
)
from traffic_lpr_runtime.application.use_cases import (
    AnalyzeFrameUseCase as FrameAnalysisWorkflow,
    ScanTargetsUseCase as TargetScanWorkflow,
)
from traffic_lpr_runtime.application.interval_analysis_service import (
    IntervalAnalysisDependencies,
    IntervalAnalysisService,
)


class IntervalAnalysisWorkflow:
    def __init__(
        self,
        ensure_ready: Callable[[], None],
        status: Callable[[], dict[str, Any]],
        runtime_root: Callable[[], Path],
        frame_reader: Any,
        track_target_across_interval: Callable[..., Any],
        calibrate_interval_target_boxes: Callable[..., Any],
        analyze_plate_candidates: Callable[..., Any],
        aggregate_candidates: Callable[..., Any],
        apply_reliability_selection: Callable[..., Any],
        build_track_payload: Callable[..., Any],
    ) -> None:
        self._service = IntervalAnalysisService(
            IntervalAnalysisDependencies(
                ensure_ready=ensure_ready,
                status=status,
                runtime_root=runtime_root,
                frame_reader=frame_reader,
                track_target_across_interval=track_target_across_interval,
                calibrate_interval_target_boxes=calibrate_interval_target_boxes,
                analyze_plate_candidates=analyze_plate_candidates,
                aggregate_candidates=aggregate_candidates,
                apply_reliability_selection=apply_reliability_selection,
                build_track_payload=build_track_payload,
            )
        )

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._service.run(payload)


__all__ = [
    'FrameAnalysisWorkflow',
    'IntervalAnalysisWorkflow',
    'TargetScanWorkflow',
    '_boxes_remain_anchored',
    '_resolve_analysis_target_box',
    '_resolve_interval_anchor_box',
    '_select_interval_evidence_frames',
]
