from __future__ import annotations

from pathlib import Path
from typing import Any

from traffic_lpr_runtime.domain.analysis_options import AnalysisOptions
from traffic_lpr_runtime.domain.enums import ArtifactStage, DecisionSource
from traffic_lpr_runtime.domain.errors import RuntimeFailure
from traffic_lpr_runtime.domain.interfaces import FrameReader, PlateRecognizer, TargetDetector
from traffic_lpr_runtime.domain.models import FrameSample, PlateCandidate, TargetTrack, TrackedRegion
from traffic_lpr_runtime.domain.text import normalize_plate_text
from traffic_lpr_runtime.domain.value_objects import NormalizedRect, crop_image
from traffic_lpr_runtime.application.contract_spec import LprContractRegistry
from traffic_lpr_runtime.application.interval_analysis_service import (
    IntervalAnalysisDependencies,
    IntervalAnalysisService,
)
from traffic_lpr_runtime.application.interval_tracking import IntervalTrackingService
from traffic_lpr_runtime.application.services.fusion.candidate_fusion import (
    CandidateFusionService,
    apply_reliability_selection,
)
from traffic_lpr_runtime.application.services.preprocessing import (
    PlateObservation,
    PlatePreprocessor,
)
from traffic_lpr_runtime.application.services.tracking.tracker import TargetCentricTracker
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
from traffic_lpr_runtime.infrastructure.frame_reader import OpenCvFrameReader
from traffic_lpr_runtime.infrastructure.image_processing import QualityScorer
from traffic_lpr_runtime.infrastructure.model_runtime import (
    FastAlprPlateRecognizer,
    ModelRegistry,
    UltralyticsTargetDetector,
)


HARD_PLATE_SECONDARY_CROP_SPECS = (
    (0.0, 0.3),
    (0.25, 0.0),
    (0.25, 0.3),
    (0.5, 0.0),
    (0.5, 0.3),
)

HARD_PLATE_SECONDARY_OCR_MODELS = ('cct-s-v2-global-model',)


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
        self._plate_preprocessor = PlatePreprocessor(dependencies, quality_scorer)
        self._tracker = TargetCentricTracker(dependencies, frame_reader, target_detector)
        self._interval_tracking = IntervalTrackingService(self._frame_reader, self._detect_targets, self._tracker)
        self._candidate_fusion = CandidateFusionService(dependencies, primary_recognizer)
        self._target_scan_use_case = ScanTargetsUseCase(
            ensure_ready=self._dependencies.ensure_ready,
            status=self.status,
            frame_reader=self._frame_reader,
            detect_targets=self._detect_targets,
        )
        self._frame_analysis_use_case = AnalyzeFrameUseCase(
            ensure_ready=self._dependencies.ensure_ready,
            status=self.status,
            runtime_root=self._dependencies.runtime_root,
            frame_reader=self._frame_reader,
            detect_targets=self._detect_targets,
            match_anchor_target=self._match_anchor_target,
            analyze_plate_candidates=self._analyze_plate_candidates,
            apply_reliability_selection=_apply_reliability_selection,
        )
        self._interval_analysis_use_case = IntervalAnalysisService(
            IntervalAnalysisDependencies(
                ensure_ready=self._dependencies.ensure_ready,
                status=self.status,
                runtime_root=self._dependencies.runtime_root,
                frame_reader=self._frame_reader,
                track_target_across_interval=self._track_target_across_interval,
                calibrate_interval_target_boxes=self._calibrate_interval_target_boxes,
                analyze_plate_candidates=self._analyze_plate_candidates,
                aggregate_candidates=self._aggregate_candidates,
                apply_reliability_selection=_apply_reliability_selection,
                build_track_payload=self._build_track_payload,
            )
        )
        self._extract_storyboard_use_case = ExtractStoryboardUseCase(
            ensure_ready=self._dependencies.ensure_ready,
            runtime_root=self._dependencies.runtime_root,
            frame_reader=self._frame_reader,
            dependencies=self._dependencies,
        )
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

    def _detect_targets(
        self,
        frame: Any,
        time_ms: int,
        vehicle_kind: str,
        marker_rect: NormalizedRect | None,
    ) -> list[TrackedRegion]:
        return self._target_detector.detect_targets(frame, time_ms, vehicle_kind, marker_rect)

    def _select_analysis_roi(
        self,
        frame: Any,
        marker_rect: NormalizedRect | None,
        target_box: NormalizedRect | None,
    ) -> tuple[Any, NormalizedRect | None]:
        if target_box:
            return crop_image(frame, target_box), target_box
        if marker_rect:
            return crop_image(frame, marker_rect), marker_rect
        return frame, None

    def _analyze_plate_candidates(
        self,
        frame: Any,
        time_ms: int,
        marker_rect: NormalizedRect | None,
        target_box: NormalizedRect | None,
        country_hints: list[str],
        options: AnalysisOptions,
        artifact_root: Path | None,
        support_observations: list[PlateObservation] | None = None,
    ) -> tuple[list[PlateCandidate], FrameSample, PlateObservation | None]:
        working_image, crop_box = self._select_analysis_roi(frame, marker_rect, target_box)
        recognizer_backend = _normalize_recognizer_backend(options.recognizer_backend)
        allow_crop_refinement = recognizer_backend != 'baseline'
        baseline_candidates = self._primary_recognizer.recognize(working_image, time_ms, crop_box)
        best_baseline = baseline_candidates[0] if baseline_candidates else None
        observation = None
        crop_candidates: list[PlateCandidate] = []

        if allow_crop_refinement and best_baseline and best_baseline.box is not None:
            observation = self._plate_preprocessor.prepare(
                frame,
                time_ms,
                target_box,
                best_baseline.box,
                options,
                artifact_root,
            )
            if observation is not None:
                if support_observations:
                    observation = self._plate_preprocessor.integrate_temporal_support(
                        observation,
                        support_observations,
                        options,
                        artifact_root,
                    )
                crop_candidates = self._recognize_observation_crop(
                    observation,
                    time_ms,
                    best_baseline.box,
                    country_hints,
                    options,
                )
                observation.ocr_candidates = crop_candidates
        elif allow_crop_refinement and marker_rect is not None and target_box is None and _looks_like_plate_roi(marker_rect):
            observation = self._plate_preprocessor.prepare(
                frame,
                time_ms,
                None,
                marker_rect,
                options,
                artifact_root,
            )
            if observation is not None:
                if support_observations:
                    observation = self._plate_preprocessor.integrate_temporal_support(
                        observation,
                        support_observations,
                        options,
                        artifact_root,
                    )
                crop_candidates = self._recognize_observation_crop(
                    observation,
                    time_ms,
                    marker_rect,
                    country_hints,
                    options,
                    extra_diagnostics={'directPlateRoi': True},
                )
                for candidate in crop_candidates:
                    candidate.confidence = max(candidate.confidence, min(1.0, candidate.confidence * 1.06))
                observation.ocr_candidates = crop_candidates

        candidates = self._rank_sample_candidates(baseline_candidates, crop_candidates, observation)
        for candidate in candidates:
            candidate.diagnostics = {
                **(candidate.diagnostics or {}),
                'recognizerBackend': recognizer_backend,
            }
        best_candidate = candidates[0] if candidates else best_baseline
        sample_quality = (
            observation.quality
            if observation is not None and observation.quality is not None
            else best_candidate.quality if best_candidate else self._quality_scorer.score(working_image, None)
        )
        sample = FrameSample(
            id=f'sample-{time_ms}',
            time_ms=time_ms,
            target_box=target_box,
            plate_box=(observation.plate_box if observation is not None else None) or (best_candidate.box if best_candidate else None),
            quality=sample_quality,
            candidates=candidates[:6],
            image_path=(observation.artifact_paths.get('working') if observation is not None else None),
            selection=None,
            ocr_input=self._observation_ocr_input(observation),
            temporal_support=(observation.temporal_support if observation is not None else None),
            diagnostics={
                'analysisOptions': options.to_payload(),
                'recognizerBackend': recognizer_backend,
                'allowCropRefinement': allow_crop_refinement,
                'baselineCandidateCount': len(baseline_candidates),
                'ocrCandidateCount': len(crop_candidates),
                'baselineCandidates': [
                    {
                        'text': candidate.text,
                        'confidence': candidate.confidence,
                        'source': candidate.source,
                    }
                    for candidate in baseline_candidates[: options.max_plate_candidates]
                ],
                'ocrCandidates': [
                    {
                        'text': candidate.text,
                        'confidence': candidate.confidence,
                        'source': candidate.source,
                        'diagnostics': candidate.diagnostics,
                    }
                    for candidate in crop_candidates[: max(options.max_plate_candidates, 3)]
                ],
                'plateProcessing': observation.diagnostics if observation is not None else None,
            },
        )
        return candidates, sample, observation

    def _observation_ocr_input(self, observation: PlateObservation | None) -> dict[str, Any] | None:
        if observation is None:
            return None
        support = observation.temporal_support or {}
        source = DecisionSource.TEMPORAL_RESTORED.value if observation.working_stage == ArtifactStage.TEMPORAL_RESTORED.value else DecisionSource.SINGLE_FRAME.value
        return {
            'stage': observation.working_stage,
            'variant': observation.working_stage,
            'source': source,
            'imagePath': observation.artifact_paths.get('working'),
            'supportFrameCount': int(support.get('supportFrameCount') or 1),
        }

    def _recognize_observation_crop(
        self,
        observation: PlateObservation,
        time_ms: int,
        plate_box: NormalizedRect | None,
        country_hints: list[str],
        options: AnalysisOptions,
        extra_diagnostics: dict[str, Any] | None = None,
    ) -> list[PlateCandidate]:
        diagnostics_extra = dict(extra_diagnostics or {})
        crop_candidates = self._primary_recognizer.recognize_plate_crop(
            observation.working_image,
            time_ms,
            plate_box,
            country_hints,
            options.ocr_models(),
        )
        for candidate in crop_candidates:
            candidate.diagnostics = {
                **(candidate.diagnostics or {}),
                **diagnostics_extra,
                'ocrVariant': 'working',
            }

        for variant_name, variant_image in [
            ('enhanced', observation.enhanced_image),
            ('rectified', observation.rectified_image),
            ('original', observation.original_image),
        ]:
            if variant_image is None or getattr(variant_image, 'size', 0) == 0 or variant_image is observation.working_image:
                continue
            variant_candidates = self._primary_recognizer.recognize_plate_crop(
                variant_image,
                time_ms,
                plate_box,
                country_hints,
                options.ocr_models(),
            )
            for candidate in variant_candidates:
                candidate.diagnostics = {
                    **(candidate.diagnostics or {}),
                    **diagnostics_extra,
                    'ocrVariant': variant_name,
                }
            crop_candidates.extend(variant_candidates)

        crop_candidates.extend(
            self._secondary_subcrop_candidates(
                observation,
                time_ms,
                plate_box,
                country_hints,
                options,
                diagnostics_extra,
            )
        )

        return _merge_unique_crop_candidates(crop_candidates)

    def _secondary_subcrop_candidates(
        self,
        observation: PlateObservation,
        time_ms: int,
        plate_box: NormalizedRect | None,
        country_hints: list[str],
        options: AnalysisOptions,
        diagnostics_extra: dict[str, Any],
    ) -> list[PlateCandidate]:
        if not options.enable_secondary_subcrop_ocr:
            return []

        diagnostics = observation.diagnostics or {}
        quality_route = str(diagnostics.get('qualityRoute') or '')
        if quality_route not in {'high-angle', 'tiny-plate', 'motion-soft'}:
            return []

        original_image = observation.original_image
        if original_image is None or getattr(original_image, 'size', 0) == 0:
            return []

        shape = getattr(original_image, 'shape', None)
        if shape is None or min(shape[:2]) > 96:
            return []

        crop_box_payload = diagnostics.get('ocrCropBox')
        source_box_payload = diagnostics.get('sourcePlateBox')
        if not isinstance(crop_box_payload, dict) or not isinstance(source_box_payload, dict):
            return []

        try:
            crop_box = NormalizedRect.from_payload(crop_box_payload)
            source_box = NormalizedRect.from_payload(source_box_payload)
        except (TypeError, ValueError):
            return []
        if crop_box is None or source_box is None or crop_box.width <= 0 or crop_box.height <= 0:
            return []

        relative_box = NormalizedRect(
            x=(source_box.x - crop_box.x) / crop_box.width,
            y=(source_box.y - crop_box.y) / crop_box.height,
            width=source_box.width / crop_box.width,
            height=source_box.height / crop_box.height,
        )
        model_names = list(dict.fromkeys([*options.ocr_models(), *HARD_PLATE_SECONDARY_OCR_MODELS]))
        secondary_candidates: list[PlateCandidate] = []

        for width_pad_ratio, height_pad_ratio in HARD_PLATE_SECONDARY_CROP_SPECS:
            x1 = max(0.0, relative_box.x - (relative_box.width * width_pad_ratio))
            y1 = max(0.0, relative_box.y - (relative_box.height * height_pad_ratio))
            x2 = min(1.0, relative_box.x + relative_box.width * (1.0 + width_pad_ratio))
            y2 = min(1.0, relative_box.y + relative_box.height * (1.0 + height_pad_ratio))
            if x2 <= x1 or y2 <= y1:
                continue

            subcrop_box = NormalizedRect(x=x1, y=y1, width=x2 - x1, height=y2 - y1)
            subcrop_image = crop_image(original_image, subcrop_box)
            if subcrop_image is None or getattr(subcrop_image, 'size', 0) == 0:
                continue

            subcrop_candidates = self._primary_recognizer.recognize_plate_crop(
                subcrop_image,
                time_ms,
                plate_box,
                country_hints,
                model_names,
            )
            for candidate in subcrop_candidates:
                candidate.diagnostics = {
                    **(candidate.diagnostics or {}),
                    **diagnostics_extra,
                    'ocrVariant': 'secondary-subcrop',
                    'subcrop': {
                        'wx': width_pad_ratio,
                        'hy': height_pad_ratio,
                    },
                }
            secondary_candidates.extend(subcrop_candidates)

        return secondary_candidates

    def _aggregate_candidates(
        self,
        samples: list[FrameSample],
        observations: list[PlateObservation],
        country_hints: list[str],
        options: AnalysisOptions,
        artifact_root: Path | None,
    ) -> tuple[list[PlateCandidate], dict[str, Any]]:
        return self._candidate_fusion.aggregate_candidates(
            samples,
            observations,
            country_hints,
            options,
            artifact_root,
        )

    def _resolve_sample_step_ms(
        self,
        interval: dict[str, int],
        requested_every_ms: int | None,
        requested_max_samples: int | None,
    ) -> int:
        return self._interval_tracking.resolve_sample_step_ms(interval, requested_every_ms, requested_max_samples)

    def _sample_times(
        self,
        interval: dict[str, int],
        requested_every_ms: int | None,
        requested_max_samples: int | None,
    ) -> list[int]:
        return self._interval_tracking.sample_times(interval, requested_every_ms, requested_max_samples)

    def _match_anchor_target(
        self,
        detections: list[TrackedRegion],
        selected_target_box: NormalizedRect | None,
    ) -> TrackedRegion | None:
        return self._interval_tracking.match_anchor_target(detections, selected_target_box)

    def _match_tracked_target(
        self,
        detections: list[TrackedRegion],
        previous_box: NormalizedRect | None,
    ) -> TrackedRegion | None:
        return self._interval_tracking._match_tracked_target(detections, previous_box)

    def _track_target_across_interval(
        self,
        source_path: str,
        interval: dict[str, int],
        anchor_time_ms: int,
        vehicle_kind: str,
        selected_target_box: NormalizedRect | None,
        sample_every_ms: int | None,
        max_samples: int | None,
        options: AnalysisOptions,
        preserve_dense_evidence_samples: bool = False,
    ) -> tuple[list[TrackedRegion], dict[str, Any]]:
        return self._interval_tracking.track_target_across_interval(
            source_path,
            interval,
            anchor_time_ms,
            vehicle_kind,
            selected_target_box,
            sample_every_ms,
            max_samples,
            options,
            preserve_dense_evidence_samples,
        )

    def _calibrate_interval_target_boxes(
        self,
        tracked_frames: list[TrackedRegion],
        anchor_time_ms: int,
        selected_target_box: NormalizedRect | None,
    ) -> dict[int, NormalizedRect]:
        return self._interval_tracking.calibrate_interval_target_boxes(
            tracked_frames,
            anchor_time_ms,
            selected_target_box,
        )

    def _build_track_payload(self, tracked_frames: list[TrackedRegion], diagnostics: dict[str, Any]) -> list[TargetTrack]:
        return self._interval_tracking.build_track_payload(tracked_frames, diagnostics)

    def _rank_sample_candidates(
        self,
        baseline_candidates: list[PlateCandidate],
        crop_candidates: list[PlateCandidate],
        observation: PlateObservation | None,
    ) -> list[PlateCandidate]:
        return self._candidate_fusion.rank_sample_candidates(
            baseline_candidates,
            crop_candidates,
            observation,
        )


def _apply_reliability_selection(
    candidates: list[PlateCandidate],
    samples: list[FrameSample],
    country_hints: list[str],
    options: AnalysisOptions,
    interval_mode: bool,
) -> tuple[list[PlateCandidate], str | None, dict[str, Any]]:
    return apply_reliability_selection(candidates, samples, country_hints, options, interval_mode)


def _looks_like_plate_roi(rect: NormalizedRect) -> bool:
    if rect.height <= 0 or rect.width <= 0:
        return False
    aspect_ratio = rect.width / max(rect.height, 1e-6)
    return rect.area() <= 0.12 and 1.1 <= aspect_ratio <= 12.0


def _normalize_recognizer_backend(value: str | None) -> str:
    normalized = (value or 'hybrid').strip().lower()
    return normalized if normalized in {'baseline', 'hybrid'} else 'hybrid'


def _merge_unique_crop_candidates(candidates: list[PlateCandidate]) -> list[PlateCandidate]:
    merged: dict[tuple[str, str], PlateCandidate] = {}
    for candidate in candidates:
        text = normalize_plate_text(candidate.text)
        if not text:
            continue
        key = (text, candidate.source)
        current = merged.get(key)
        if current is None or candidate.confidence >= current.confidence:
            merged[key] = candidate
    return sorted(
        merged.values(),
        key=lambda candidate: (
            candidate.confidence,
            candidate.quality.overall_score if candidate.quality else 0.0,
        ),
        reverse=True,
    )


def build_default_application(runtime_script: Path) -> LprRuntimeApplication:
    container = build_default_runtime_service_container(runtime_script)
    return LprRuntimeApplication(
        dependencies=container.dependencies,
        frame_reader=container.frame_reader,
        target_detector=container.target_detector,
        primary_recognizer=container.primary_recognizer,
        quality_scorer=container.quality_scorer,
    )
