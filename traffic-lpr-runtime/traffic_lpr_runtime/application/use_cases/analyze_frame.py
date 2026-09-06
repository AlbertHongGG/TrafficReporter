from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from traffic_lpr_runtime.application.contracts.commands import AnalyzeFrameCommand
from traffic_lpr_runtime.application.services.fusion.review_decision import _build_decision_trace, _request_run_id
from traffic_lpr_runtime.domain.analysis_options import AnalysisOptions
from traffic_lpr_runtime.domain.enums import EvidenceReason
from traffic_lpr_runtime.domain.interfaces import ProgressSink
from traffic_lpr_runtime.domain.models import (
    AnalysisProvenance,
    FrameSample,
    PlateCandidate,
    ReviewState,
    TrackedRegion,
)
from traffic_lpr_runtime.domain.value_objects import NormalizedRect
from traffic_lpr_runtime.infrastructure.ipc import IpcProgressSink
from traffic_lpr_runtime.infrastructure.storage import RuntimeStorageLayout


class AnalyzeFrameUseCase:
    name = 'analyze-frame'

    def __init__(
        self,
        ensure_ready: Callable[[], None],
        status: Callable[[], dict[str, Any]],
        runtime_root: Callable[[], Path],
        frame_reader: Any,
        detect_targets: Callable[[Any, int, str, NormalizedRect | None], list[TrackedRegion]],
        match_anchor_target: Callable[[list[TrackedRegion], NormalizedRect | None], TrackedRegion | None],
        analyze_plate_candidates: Callable[..., Any],
        apply_reliability_selection: Callable[..., Any],
        storage: RuntimeStorageLayout | None = None,
        progress_sink: ProgressSink | None = None,
    ) -> None:
        self._ensure_ready = ensure_ready
        self._status = status
        self._runtime_root = runtime_root
        self._frame_reader = frame_reader
        self._detect_targets = detect_targets
        self._match_anchor_target = match_anchor_target
        self._analyze_plate_candidates = analyze_plate_candidates
        self._apply_reliability_selection = apply_reliability_selection
        self._storage = storage
        self._progress_sink = progress_sink or IpcProgressSink()

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        command = AnalyzeFrameCommand.from_payload(payload)
        time_ms = command.time_ms
        options = command.options.for_interactive_frame()
        storage = self._storage or RuntimeStorageLayout.discover(self._runtime_root())
        artifact_root = storage.resolve_artifact_dir(options, f'frame-{time_ms}', command.request_id)
        marker_rect = command.marker_rect
        selected_target_box = command.selected_target_box

        self._progress_sink.emit(0.12, 'Frame', 'Reading the selected frame for interactive analysis.')
        frame = self._frame_reader.read_frame(command.source_path, time_ms)
        self._progress_sink.emit(0.28, 'Frame', 'Locating the selected vehicle and plate candidates.')
        detections = self._detect_targets(
            frame,
            time_ms,
            command.target_vehicle_kind,
            marker_rect,
        )
        target_region = self._match_anchor_target(detections, selected_target_box)
        target_box = target_region.box if target_region else selected_target_box
        self._progress_sink.emit(0.64, 'Frame', 'Running the interactive plate analysis fast path.')
        candidates, sample, observation = self._analyze_plate_candidates(
            frame,
            time_ms,
            marker_rect,
            target_box,
            list(command.country_hints),
            options,
            artifact_root,
        )
        candidates, accepted_candidate_id, selection_diagnostics = self._apply_reliability_selection(
            candidates,
            [sample],
            list(command.country_hints),
            options,
            False,
        )
        sample.selection = {'selected': True, 'priority': 1.0, 'reasons': [EvidenceReason.ANCHOR.value]}
        sample.diagnostics = {
            **(sample.diagnostics or {}),
            'selection': selection_diagnostics,
        }
        self._progress_sink.emit(0.9, 'Frame', 'Finalizing the frame analysis result.')
        runtime_status = self._status()
        decision = _build_decision_trace(candidates, accepted_candidate_id, selection_diagnostics, [sample])
        return {
            'detections': [detection.to_payload() for detection in detections],
            'sample': sample.to_payload(),
            'candidates': [candidate.to_payload() for candidate in candidates[:8]],
            'acceptedCandidateId': accepted_candidate_id,
            'review': ReviewState.evaluate(candidates, accepted_candidate_id, selection_diagnostics).to_payload(),
            'provenance': AnalysisProvenance.create('analyze-frame', payload, runtime_status, options.to_payload()).to_payload(),
            'decision': decision,
            'runtime': runtime_status,
            'jobStatus': 'completed',
            'diagnostics': {
                'analysisOptions': options.to_payload(),
                'artifactRoot': str(artifact_root) if artifact_root else None,
                'observation': observation.diagnostics if observation else None,
                'selection': selection_diagnostics,
            },
        }
