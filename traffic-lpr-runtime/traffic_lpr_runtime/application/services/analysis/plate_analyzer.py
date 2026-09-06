from __future__ import annotations

from pathlib import Path
from typing import Any

from traffic_lpr_runtime.domain.analysis_options import AnalysisOptions
from traffic_lpr_runtime.domain.enums import ArtifactStage, DecisionSource
from traffic_lpr_runtime.domain.interfaces import PlateRecognizer, QualityScorer
from traffic_lpr_runtime.domain.models import FrameSample, PlateCandidate
from traffic_lpr_runtime.domain.text import normalize_plate_text
from traffic_lpr_runtime.domain.value_objects import NormalizedRect, crop_image
from traffic_lpr_runtime.application.services.fusion.candidate_fusion import CandidateFusionService
from traffic_lpr_runtime.application.services.preprocessing import PlateObservation, PlatePreprocessor

HARD_PLATE_SECONDARY_CROP_SPECS = (
    (0.0, 0.3),
    (0.25, 0.0),
    (0.25, 0.3),
    (0.5, 0.0),
    (0.5, 0.3),
)

HARD_PLATE_SECONDARY_OCR_MODELS = ('cct-s-v2-global-model',)


class PlateAnalysisService:
    def __init__(
        self,
        primary_recognizer: PlateRecognizer,
        plate_preprocessor: PlatePreprocessor,
        quality_scorer: QualityScorer,
        candidate_fusion: CandidateFusionService,
    ) -> None:
        self._primary_recognizer = primary_recognizer
        self._plate_preprocessor = plate_preprocessor
        self._quality_scorer = quality_scorer
        self._candidate_fusion = candidate_fusion

    def select_analysis_roi(
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

    def analyze_plate_candidates(
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
        working_image, crop_box = self.select_analysis_roi(frame, marker_rect, target_box)
        recognizer_backend = self._normalize_recognizer_backend(options.recognizer_backend)
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
                crop_candidates = self.recognize_observation_crop(
                    observation,
                    time_ms,
                    best_baseline.box,
                    country_hints,
                    options,
                )
                observation.ocr_candidates = crop_candidates
        elif allow_crop_refinement and marker_rect is not None and target_box is None and self._looks_like_plate_roi(marker_rect):
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
                crop_candidates = self.recognize_observation_crop(
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

        candidates = self.rank_sample_candidates(baseline_candidates, crop_candidates, observation)
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
            ocr_input=self.observation_ocr_input(observation),
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

    def observation_ocr_input(self, observation: PlateObservation | None) -> dict[str, Any] | None:
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

    def recognize_observation_crop(
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
            self.secondary_subcrop_candidates(
                observation,
                time_ms,
                plate_box,
                country_hints,
                options,
                diagnostics_extra,
            )
        )

        return self._merge_unique_crop_candidates(crop_candidates)

    def secondary_subcrop_candidates(
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

    def rank_sample_candidates(
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

    def _looks_like_plate_roi(self, rect: NormalizedRect) -> bool:
        if rect.height <= 0 or rect.width <= 0:
            return False
        aspect_ratio = rect.width / max(rect.height, 1e-6)
        return rect.area() <= 0.12 and 1.1 <= aspect_ratio <= 12.0

    def _normalize_recognizer_backend(self, value: str | None) -> str:
        normalized = (value or 'hybrid').strip().lower()
        return normalized if normalized in {'baseline', 'hybrid'} else 'hybrid'

    def _merge_unique_crop_candidates(self, candidates: list[PlateCandidate]) -> list[PlateCandidate]:
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
