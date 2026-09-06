from __future__ import annotations

from pathlib import Path
from typing import Any

from traffic_lpr_runtime.domain.interfaces import FrameReader, PlateRecognizer, TargetDetector
from traffic_lpr_runtime.domain.models import FrameSample, PlateCandidate, TargetTrack, TrackedRegion
from traffic_lpr_runtime.domain.value_objects import NormalizedRect
from traffic_lpr_runtime.application.contract_spec import LprContractRegistry
from traffic_lpr_runtime.application.services.analysis import (
    IntervalAnalysisDependencies,
    IntervalAnalysisService,
    PlateAnalysisService,
)
from traffic_lpr_runtime.application.services.fusion.candidate_fusion import (
    CandidateFusionService,
    apply_reliability_selection,
)
from traffic_lpr_runtime.application.services.preprocessing import (
    PlateObservation,
    PlatePreprocessor,
)
from traffic_lpr_runtime.application.services.tracking import (
    IntervalTrackingService,
    TargetCentricTracker,
)
from traffic_lpr_runtime.application.use_cases.analyze_frame import AnalyzeFrameUseCase
from traffic_lpr_runtime.application.use_cases.extract_storyboard import ExtractStoryboardUseCase
from traffic_lpr_runtime.application.use_cases.registry import (
    CallableRuntimeUseCase,
    RuntimeUseCaseRegistry,
)
from traffic_lpr_runtime.application.use_cases.scan_targets import ScanTargetsUseCase
from traffic_lpr_runtime.infrastructure.container import (
    RuntimeServiceContainer,
    build_default_runtime_service_container,
)
from traffic_lpr_runtime.infrastructure.dependencies import DependencyRegistry
from traffic_lpr_runtime.infrastructure.image_processing import QualityScorer


class LprRuntimeApplication:
    def __init__(
        self,
        dependencies: DependencyRegistry,
        frame_reader: FrameReader,
        target_detector: TargetDetector,
        primary_recognizer: PlateRecognizer,
        quality_scorer: QualityScorer,
    ) -> None:
        self._dependencies = dependencies
        self._frame_reader = frame_reader
        self._target_detector = target_detector
        self._primary_recognizer = primary_recognizer
        self._quality_scorer = quality_scorer

        # Initialize core application domain services
        self._plate_preprocessor = PlatePreprocessor(dependencies, quality_scorer)
        self._tracker = TargetCentricTracker(dependencies, frame_reader, target_detector)
        self._interval_tracking = IntervalTrackingService(frame_reader, self._target_detector.detect_targets, self._tracker)
        self._candidate_fusion = CandidateFusionService(dependencies, primary_recognizer)
        self._plate_analyzer = PlateAnalysisService(
            primary_recognizer=self._primary_recognizer,
            plate_preprocessor=self._plate_preprocessor,
            quality_scorer=self._quality_scorer,
            candidate_fusion=self._candidate_fusion,
        )

        # Initialize Use Cases
        self._target_scan_use_case = ScanTargetsUseCase(
            ensure_ready=self._dependencies.ensure_ready,
            status=self.status,
            frame_reader=self._frame_reader,
            detect_targets=self._target_detector.detect_targets,
        )
        self._frame_analysis_use_case = AnalyzeFrameUseCase(
            ensure_ready=self._dependencies.ensure_ready,
            status=self.status,
            runtime_root=self._dependencies.runtime_root,
            frame_reader=self._frame_reader,
            detect_targets=self._target_detector.detect_targets,
            match_anchor_target=self._interval_tracking.match_anchor_target,
            analyze_plate_candidates=self._plate_analyzer.analyze_plate_candidates,
            apply_reliability_selection=apply_reliability_selection,
        )
        self._interval_analysis_use_case = IntervalAnalysisService(
            IntervalAnalysisDependencies(
                ensure_ready=self._dependencies.ensure_ready,
                status=self.status,
                runtime_root=self._dependencies.runtime_root,
                frame_reader=self._frame_reader,
                track_target_across_interval=self._interval_tracking.track_target_across_interval,
                calibrate_interval_target_boxes=self._interval_tracking.calibrate_interval_target_boxes,
                analyze_plate_candidates=self._plate_analyzer.analyze_plate_candidates,
                aggregate_candidates=self._candidate_fusion.aggregate_candidates,
                apply_reliability_selection=apply_reliability_selection,
                build_track_payload=self._interval_tracking.build_track_payload,
            )
        )
        self._extract_storyboard_use_case = ExtractStoryboardUseCase(
            ensure_ready=self._dependencies.ensure_ready,
            runtime_root=self._dependencies.runtime_root,
            frame_reader=self._frame_reader,
            dependencies=self._dependencies,
        )

        # Register contract validator and command routes
        self._contract_registry = LprContractRegistry()
        self._use_case_registry = RuntimeUseCaseRegistry([
            CallableRuntimeUseCase(name='status', handler=lambda payload: self.status()),
            CallableRuntimeUseCase(name='sample-storyboard-frames', handler=self.sample_storyboard_frames),
            CallableRuntimeUseCase(name='scan-targets', handler=self.scan_targets),
            CallableRuntimeUseCase(name='analyze-frame', handler=self.analyze_frame),
            CallableRuntimeUseCase(name='analyze-interval', handler=self.analyze_interval),
        ])

    def dispatch(self, subcommand: str, payload: dict[str, Any]) -> dict[str, Any]:
        if subcommand != 'status':
            self._contract_registry.validate_request(subcommand, payload)
        result = self._use_case_registry.run(subcommand, payload)
        if subcommand != 'status':
            self._contract_registry.validate_response(subcommand, result)
        return result

    def status(self) -> dict[str, Any]:
        return self._dependencies.build_status().to_payload()

    def sample_storyboard_frames(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._extract_storyboard_use_case.run(payload)

    def scan_targets(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._target_scan_use_case.run(payload)

    def analyze_frame(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._frame_analysis_use_case.run(payload)

    def analyze_interval(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._interval_analysis_use_case.run(payload)

    # Delegations for service access & backward-compatible test hooks
    def _select_analysis_roi(self, frame: Any, marker_rect: NormalizedRect | None, target_box: NormalizedRect | None) -> tuple[Any, NormalizedRect | None]:
        analyzer = getattr(self, '_plate_analyzer', None)
        if analyzer is not None:
            return analyzer.select_analysis_roi(frame, marker_rect, target_box)
        if target_box:
            from traffic_lpr_runtime.domain.value_objects import crop_image
            return crop_image(frame, target_box), target_box
        if marker_rect:
            from traffic_lpr_runtime.domain.value_objects import crop_image
            return crop_image(frame, marker_rect), marker_rect
        return frame, None

    def _analyze_plate_candidates(self, *args: Any, **kwargs: Any) -> Any:
        analyzer = getattr(self, '_plate_analyzer', None)
        if analyzer is None:
            analyzer = PlateAnalysisService(
                primary_recognizer=getattr(self, '_primary_recognizer', None),
                plate_preprocessor=getattr(self, '_plate_preprocessor', None),
                quality_scorer=getattr(self, '_quality_scorer', None),
                candidate_fusion=getattr(self, '_candidate_fusion', None),
            )
            if hasattr(self, '_select_analysis_roi'):
                analyzer.select_analysis_roi = self._select_analysis_roi
            if hasattr(self, '_rank_sample_candidates'):
                analyzer.rank_sample_candidates = self._rank_sample_candidates
        return analyzer.analyze_plate_candidates(*args, **kwargs)

    def _recognize_observation_crop(self, *args: Any, **kwargs: Any) -> Any:
        analyzer = getattr(self, '_plate_analyzer', None)
        if analyzer is None:
            analyzer = PlateAnalysisService(
                primary_recognizer=getattr(self, '_primary_recognizer', None),
                plate_preprocessor=getattr(self, '_plate_preprocessor', None),
                quality_scorer=getattr(self, '_quality_scorer', None),
                candidate_fusion=getattr(self, '_candidate_fusion', None),
            )
        return analyzer.recognize_observation_crop(*args, **kwargs)


def build_default_application(runtime_script: Path) -> LprRuntimeApplication:
    container = build_default_runtime_service_container(runtime_script)
    return LprRuntimeApplication(
        dependencies=container.dependencies,
        frame_reader=container.frame_reader,
        target_detector=container.target_detector,
        primary_recognizer=container.primary_recognizer,
        quality_scorer=container.quality_scorer,
    )
