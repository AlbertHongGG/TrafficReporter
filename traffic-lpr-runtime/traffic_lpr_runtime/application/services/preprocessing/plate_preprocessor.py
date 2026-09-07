from __future__ import annotations

from pathlib import Path
from typing import Any

from traffic_lpr_runtime.domain.analysis_options import AnalysisOptions
from traffic_lpr_runtime.domain.value_objects import NormalizedRect, clamp, crop_image
from traffic_lpr_runtime.domain.interfaces import PlateRestorer, QualityScorer
from traffic_lpr_runtime.infrastructure.dependencies import DependencyRegistry

from .enhancement import EnhancementMixin
from .observation import PlateObservation
from .quality import _merge_quality_metrics, _resolve_quality_route, _select_working_stage
from .rectification import RectificationMixin
from .temporal import TemporalMixin


class PlatePreprocessor(RectificationMixin, EnhancementMixin, TemporalMixin):
    def __init__(
        self,
        dependencies: DependencyRegistry,
        quality_scorer: QualityScorer,
        restorer: PlateRestorer | None = None,
    ) -> None:
        self._dependencies = dependencies
        self._quality_scorer = quality_scorer
        self._restorer = restorer

    def prepare(
        self,
        frame: Any,
        time_ms: int,
        target_box: NormalizedRect | None,
        plate_box: NormalizedRect | None,
        options: AnalysisOptions,
        artifact_root: Path | None,
        *,
        allow_restore: bool = True,
    ) -> PlateObservation | None:
        if frame is None or plate_box is None:
            return None

        ocr_crop_box = self._expand_plate_crop_box(frame, plate_box)
        original_image = crop_image(frame, ocr_crop_box)
        if original_image is None or getattr(original_image, 'size', 0) == 0:
            return None

        rectified_image = original_image
        rectification = {'applied': False, 'method': 'crop'}
        if options.enable_rectification:
            rectified_image, rectification = self._rectify_plate(original_image)

        enhanced_image = self._enhance_plate(rectified_image) if options.enable_enhancement else rectified_image
        source_quality = self._quality_scorer.score(frame, plate_box)
        original_quality = self._quality_scorer.score(original_image, None)
        rectified_quality = self._quality_scorer.score(rectified_image, None)
        enhanced_quality = self._quality_scorer.score(enhanced_image, None)
        merged_quality = _merge_quality_metrics(source_quality, enhanced_quality)
        quality_route = _resolve_quality_route(original_image, merged_quality)

        restored_image = None
        restoration = {'applied': False, 'backend': 'none', 'mode': options.restoration_mode}
        restored_quality = None
        if allow_restore and self._should_restore(enhanced_image, merged_quality, options, quality_route):
            restored_image, restoration = self._restore_plate(enhanced_image, options)
            if restored_image is not None:
                restored_quality = self._quality_scorer.score(restored_image, None)

        working_stage, working_image, working_quality, stage_scores = _select_working_stage(
            quality_route=quality_route,
            stage_candidates=[
                ('original', original_image, original_quality),
                ('rectified', rectified_image, rectified_quality),
                ('enhanced', enhanced_image, enhanced_quality),
                ('restored', restored_image, restored_quality),
            ],
        )
        merged_quality = _merge_quality_metrics(source_quality, working_quality or enhanced_quality)

        artifact_paths = self._persist_artifacts(
            artifact_root,
            time_ms,
            original_image,
            rectified_image,
            enhanced_image,
            restored_image,
            working_image,
        )
        diagnostics = {
            'rectification': rectification,
            'restoreApplied': restored_image is not None,
            'restoration': restoration,
            'qualityRoute': quality_route,
            'ocrCropBox': ocr_crop_box.to_payload(),
            'sourcePlateBox': plate_box.to_payload(),
            'originalShape': list(original_image.shape[:2]),
            'workingShape': list(working_image.shape[:2]),
            'workingStage': working_stage,
            'stageScores': stage_scores,
            'artifacts': artifact_paths,
        }
        return PlateObservation(
            time_ms=time_ms,
            target_box=target_box,
            plate_box=plate_box,
            quality=merged_quality,
            original_image=original_image,
            rectified_image=rectified_image,
            enhanced_image=enhanced_image,
            restored_image=restored_image,
            working_image=working_image,
            working_stage=working_stage,
            artifact_paths=artifact_paths,
            diagnostics=diagnostics,
        )

    def _expand_plate_crop_box(self, frame: Any, plate_box: NormalizedRect) -> NormalizedRect:
        if frame is None or getattr(frame, 'shape', None) is None:
            return plate_box

        frame_height, frame_width = frame.shape[:2]
        if frame_height <= 0 or frame_width <= 0:
            return plate_box

        pixel_width = plate_box.width * frame_width
        pixel_height = plate_box.height * frame_height

        width_pad = max(plate_box.width * 0.18, 10.0 / frame_width)
        height_pad = max(plate_box.height * 0.6, 6.0 / frame_height)

        if pixel_height < 14:
            width_pad = max(width_pad, plate_box.width * 0.4, 22.0 / frame_width)
            height_pad = max(height_pad, plate_box.height * 2.6, 18.0 / frame_height)
        elif pixel_height < 24:
            width_pad = max(width_pad, plate_box.width * 0.26, 14.0 / frame_width)
            height_pad = max(height_pad, plate_box.height * 1.25, 10.0 / frame_height)

        if pixel_width < 72:
            width_pad = max(width_pad, 18.0 / frame_width)

        x1 = clamp(plate_box.x - width_pad, 0.0, 1.0)
        y1 = clamp(plate_box.y - height_pad, 0.0, 1.0)
        x2 = clamp(plate_box.x + plate_box.width + width_pad, min(1.0, x1 + (1.0 / frame_width)), 1.0)
        y2 = clamp(plate_box.y + plate_box.height + height_pad, min(1.0, y1 + (1.0 / frame_height)), 1.0)
        return NormalizedRect(x=x1, y=y1, width=x2 - x1, height=y2 - y1)

    def _persist_artifacts(
        self,
        artifact_root: Path | None,
        time_ms: int,
        original_image: Any,
        rectified_image: Any,
        enhanced_image: Any,
        restored_image: Any | None,
        working_image: Any,
    ) -> dict[str, str]:
        if artifact_root is None or self._dependencies.cv2 is None:
            return {}

        cv2 = self._dependencies.cv2
        artifact_root.mkdir(parents=True, exist_ok=True)
        artifact_paths: dict[str, str] = {}
        for name, image in [
            ('original', original_image),
            ('rectified', rectified_image),
            ('enhanced', enhanced_image),
            ('working', working_image),
            ('restored', restored_image),
        ]:
            if image is None:
                continue
            output_path = artifact_root / f'{time_ms}-{name}.png'
            cv2.imwrite(str(output_path), image)
            artifact_paths[name] = str(output_path)
        return artifact_paths
