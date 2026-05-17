from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from traffic_lpr_runtime.application.pipeline_support import AnalysisOptions
from traffic_lpr_runtime.domain.models import PlateCandidate, QualityMetrics
from traffic_lpr_runtime.domain.value_objects import NormalizedRect, clamp, crop_image
from traffic_lpr_runtime.infrastructure.dependencies import DependencyRegistry
from traffic_lpr_runtime.infrastructure.image_processing import QualityScorer
from traffic_lpr_runtime.infrastructure.mambair_runtime import MambaIrV2LightRestorer


@dataclass(slots=True)
class PlateObservation:
    time_ms: int
    target_box: NormalizedRect | None
    plate_box: NormalizedRect | None
    quality: QualityMetrics | None
    original_image: Any
    rectified_image: Any
    enhanced_image: Any
    restored_image: Any | None
    working_image: Any
    artifact_paths: dict[str, str]
    diagnostics: dict[str, Any]
    ocr_candidates: list[PlateCandidate] = field(default_factory=list)


class PlatePreprocessor:
    def __init__(self, dependencies: DependencyRegistry, quality_scorer: QualityScorer) -> None:
        self._dependencies = dependencies
        self._quality_scorer = quality_scorer
        self._mambair_restorer = MambaIrV2LightRestorer(dependencies)

    def prepare(
        self,
        frame: Any,
        time_ms: int,
        target_box: NormalizedRect | None,
        plate_box: NormalizedRect | None,
        options: AnalysisOptions,
        artifact_root: Path | None,
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
        crop_quality = self._quality_scorer.score(enhanced_image, None)
        merged_quality = _merge_quality_metrics(source_quality, crop_quality)

        restored_image = None
        restoration = {'applied': False, 'backend': 'none', 'mode': options.restoration_mode}
        if self._should_restore(enhanced_image, merged_quality, options):
            restored_image, restoration = self._restore_plate(enhanced_image, options)
        working_image = restored_image if restored_image is not None else enhanced_image

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
            'ocrCropBox': ocr_crop_box.to_payload(),
            'sourcePlateBox': plate_box.to_payload(),
            'originalShape': list(original_image.shape[:2]),
            'workingShape': list(working_image.shape[:2]),
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

    def _rectify_plate(self, plate_image: Any) -> tuple[Any, dict[str, Any]]:
        cv2 = self._dependencies.cv2
        if cv2 is None or plate_image is None or getattr(plate_image, 'size', 0) == 0:
            return plate_image, {'applied': False, 'method': 'crop'}

        grayscale = cv2.cvtColor(plate_image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(grayscale, (5, 5), 0)
        edges = cv2.Canny(blurred, 60, 180)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        image_area = max(float(plate_image.shape[0] * plate_image.shape[1]), 1.0)
        best_quad: Any = None
        best_score = 0.0

        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < image_area * 0.12:
                continue
            rect = cv2.minAreaRect(contour)
            (_, _), (width, height), _ = rect
            if width <= 1 or height <= 1:
                continue
            aspect_ratio = max(width, height) / max(min(width, height), 1.0)
            if not 2.0 <= aspect_ratio <= 6.5:
                continue
            score = (area / image_area) - (abs(aspect_ratio - 3.2) * 0.08)
            if score <= best_score:
                continue
            best_score = score
            best_quad = cv2.boxPoints(rect)

        if best_quad is None:
            return plate_image, {'applied': False, 'method': 'crop'}

        ordered = _order_quad_points(best_quad)
        dest_width = max(128, int(round(max(_distance(ordered[0], ordered[1]), _distance(ordered[2], ordered[3])))))
        dest_height = max(40, int(round(dest_width / 3.2)))
        destination = self._dependencies.numpy.array(
            [[0, 0], [dest_width - 1, 0], [dest_width - 1, dest_height - 1], [0, dest_height - 1]],
            dtype='float32',
        )
        transform = cv2.getPerspectiveTransform(ordered, destination)
        rectified = cv2.warpPerspective(plate_image, transform, (dest_width, dest_height))
        return rectified, {'applied': True, 'method': 'minAreaRect', 'score': best_score}

    def _enhance_plate(self, plate_image: Any) -> Any:
        cv2 = self._dependencies.cv2
        if cv2 is None or plate_image is None or getattr(plate_image, 'size', 0) == 0:
            return plate_image

        lab = cv2.cvtColor(plate_image, cv2.COLOR_BGR2LAB)
        channel_l, channel_a, channel_b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
        equalized_l = clahe.apply(channel_l)
        merged_lab = cv2.merge((equalized_l, channel_a, channel_b))
        enhanced = cv2.cvtColor(merged_lab, cv2.COLOR_LAB2BGR)
        denoised = cv2.bilateralFilter(enhanced, 5, 45, 45)
        softened = cv2.GaussianBlur(denoised, (0, 0), 1.2)
        return cv2.addWeighted(denoised, 1.55, softened, -0.55, 0)

    def _should_restore(self, plate_image: Any, quality: QualityMetrics | None, options: AnalysisOptions) -> bool:
        if options.restoration_mode == 'off' or plate_image is None:
            return False
        height, width = plate_image.shape[:2]
        if min(height, width) < 42:
            return True
        if quality is None:
            return True
        return (
            quality.overall_score < 0.62
            or quality.sharpness < 0.28
            or quality.glare_score < 0.45
            or quality.contrast < 0.35
        )

    def _restore_plate(self, plate_image: Any, options: AnalysisOptions) -> tuple[Any | None, dict[str, Any]]:
        restoration_mode = (options.restoration_mode or 'mambairv2').strip().lower()
        if restoration_mode.startswith('mambairv2'):
            scale = 4 if restoration_mode.endswith('x4') or min(plate_image.shape[:2]) < 40 else 2
            restored_image = self._mambair_restorer.restore(plate_image, scale=scale)
            if restored_image is not None and getattr(restored_image, 'size', 0) > 0:
                return restored_image, {
                    'applied': True,
                    'backend': 'mambairv2-lightsr',
                    'mode': restoration_mode,
                    'scale': scale,
                }

        if restoration_mode == 'off':
            return None, {'applied': False, 'backend': 'none', 'mode': restoration_mode}

        restored_image = self._classical_restore_plate(plate_image)
        return restored_image, {
            'applied': restored_image is not None,
            'backend': 'classical',
            'mode': restoration_mode,
        }

    def _classical_restore_plate(self, plate_image: Any) -> Any:
        cv2 = self._dependencies.cv2
        if cv2 is None or plate_image is None or getattr(plate_image, 'size', 0) == 0:
            return plate_image

        upscaled = cv2.resize(plate_image, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_LANCZOS4)
        denoised = cv2.fastNlMeansDenoisingColored(upscaled, None, 3, 3, 7, 21)
        softened = cv2.GaussianBlur(denoised, (0, 0), 1.0)
        return cv2.addWeighted(denoised, 1.65, softened, -0.65, 0)


def _merge_quality_metrics(
    source_quality: QualityMetrics | None,
    crop_quality: QualityMetrics | None,
) -> QualityMetrics | None:
    if source_quality is None:
        return crop_quality
    if crop_quality is None:
        return source_quality

    overall_score = max(source_quality.overall_score, crop_quality.overall_score)
    if overall_score >= 0.82:
        legibility_level = 'perfect'
    elif overall_score >= 0.62:
        legibility_level = 'good'
    elif overall_score >= 0.35:
        legibility_level = 'poor'
    else:
        legibility_level = 'illegible'

    return QualityMetrics(
        sharpness=max(source_quality.sharpness, crop_quality.sharpness),
        contrast=max(source_quality.contrast, crop_quality.contrast),
        plate_area=source_quality.plate_area,
        angle_score=max(source_quality.angle_score, crop_quality.angle_score),
        occlusion_score=max(source_quality.occlusion_score, crop_quality.occlusion_score),
        glare_score=max(source_quality.glare_score, crop_quality.glare_score),
        legibility_score=max(source_quality.legibility_score, crop_quality.legibility_score),
        overall_score=overall_score,
        legibility_level=legibility_level,
    )


def _order_quad_points(points: Any) -> Any:
    numpy = __import__('numpy')
    ordered = numpy.zeros((4, 2), dtype='float32')
    sums = points.sum(axis=1)
    diffs = points[:, 0] - points[:, 1]
    ordered[0] = points[sums.argmin()]
    ordered[2] = points[sums.argmax()]
    ordered[1] = points[diffs.argmin()]
    ordered[3] = points[diffs.argmax()]
    return ordered


def _distance(left: Any, right: Any) -> float:
    return float((((left[0] - right[0]) ** 2) + ((left[1] - right[1]) ** 2)) ** 0.5)
