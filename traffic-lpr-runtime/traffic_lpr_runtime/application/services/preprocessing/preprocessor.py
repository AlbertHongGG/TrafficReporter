from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from traffic_lpr_runtime.domain.analysis_options import AnalysisOptions
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
    working_stage: str
    artifact_paths: dict[str, str]
    diagnostics: dict[str, Any]
    temporal_support: dict[str, Any] | None = None
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

    def integrate_temporal_support(
        self,
        reference_observation: PlateObservation,
        support_observations: list[PlateObservation],
        options: AnalysisOptions,
        artifact_root: Path | None,
    ) -> PlateObservation:
        support_payload = self._build_temporal_support_summary(
            reference_observation,
            [],
            reference_observation.working_stage,
            reference_observation.working_stage,
            strategy='single-frame',
            mean_alignment_score=1.0,
        )
        support_payload['meanQualityScore'] = _observation_quality_score(reference_observation)

        cv2 = self._dependencies.cv2
        numpy = self._dependencies.numpy
        if cv2 is None or numpy is None:
            reference_observation.temporal_support = support_payload
            reference_observation.diagnostics = {
                **reference_observation.diagnostics,
                'temporalSupport': support_payload,
            }
            return reference_observation

        reference_image = reference_observation.working_image
        if reference_image is None or getattr(reference_image, 'size', 0) == 0:
            reference_observation.temporal_support = support_payload
            reference_observation.diagnostics = {
                **reference_observation.diagnostics,
                'temporalSupport': support_payload,
            }
            return reference_observation

        ordered_support = sorted(
            [
                observation
                for observation in support_observations
                if observation.working_image is not None and getattr(observation.working_image, 'size', 0) > 0
            ],
            key=lambda observation: (
                abs(observation.time_ms - reference_observation.time_ms),
                -_observation_quality_score(observation),
            ),
        )[:max(0, options.temporal_neighbor_count - 1)]

        accum = reference_image.astype('float32')
        total_weight = max(_observation_quality_score(reference_observation), 0.35)
        alignment_scores: list[float] = [1.0]
        quality_scores: list[float] = [_observation_quality_score(reference_observation)]
        used_support: list[PlateObservation] = []

        reference_height, reference_width = reference_image.shape[:2]
        for observation in ordered_support:
            resized = cv2.resize(
                observation.working_image,
                (reference_width, reference_height),
                interpolation=cv2.INTER_LANCZOS4,
            )
            aligned, score = self._align_image_to_reference(reference_image, resized)
            if aligned is None or score < options.min_alignment_score:
                continue
            quality_score = max(_observation_quality_score(observation), 0.2)
            weight = quality_score * max(score, 0.2)
            accum += aligned.astype('float32') * weight
            total_weight += weight
            alignment_scores.append(score)
            quality_scores.append(quality_score)
            used_support.append(observation)

        if not used_support:
            reference_observation.temporal_support = support_payload
            reference_observation.diagnostics = {
                **reference_observation.diagnostics,
                'temporalSupport': support_payload,
            }
            return reference_observation

        temporal_image = (accum / max(total_weight, 1.0)).clip(0, 255).astype('uint8')
        strategy = 'aligned-average'
        temporal_quality = self._quality_scorer.score(temporal_image, None)
        if self._should_restore(temporal_image, temporal_quality, options, 'motion-soft'):
            restored_temporal_image, restoration = self._restore_plate(temporal_image, options)
            if restored_temporal_image is not None and getattr(restored_temporal_image, 'size', 0) > 0:
                temporal_image = restored_temporal_image
                temporal_quality = self._quality_scorer.score(temporal_image, None)
                strategy = f'aligned-average+{restoration.get("backend") or "restoration"}'

        temporal_stage = 'temporal-restored'
        support_payload = self._build_temporal_support_summary(
            reference_observation,
            used_support,
            reference_observation.working_stage,
            temporal_stage,
            strategy=strategy,
            mean_alignment_score=sum(alignment_scores) / len(alignment_scores),
        )
        support_payload['meanQualityScore'] = sum(quality_scores) / len(quality_scores)

        reference_quality = reference_observation.quality.overall_score if reference_observation.quality is not None else 0.0
        temporal_score = temporal_quality.overall_score if temporal_quality is not None else -1.0
        choose_temporal = temporal_score >= (reference_quality - 0.03)
        choose_temporal = choose_temporal or (temporal_quality is not None and temporal_quality.legibility_score >= reference_quality)
        choose_temporal = choose_temporal or len(used_support) >= max(2, options.min_interval_support_frames)

        artifact_paths = dict(reference_observation.artifact_paths)
        if artifact_root is not None and cv2 is not None:
            artifact_root.mkdir(parents=True, exist_ok=True)
            temporal_path = artifact_root / f'{reference_observation.time_ms}-temporal-restored.png'
            cv2.imwrite(str(temporal_path), temporal_image)
            artifact_paths['temporal-restored'] = str(temporal_path)
            if choose_temporal:
                artifact_paths['working'] = str(temporal_path)

        stage_scores = dict(reference_observation.diagnostics.get('stageScores') or {})
        stage_scores['temporal-restored'] = temporal_score

        if choose_temporal:
            reference_observation.working_image = temporal_image
            reference_observation.working_stage = temporal_stage
            reference_observation.quality = _merge_quality_metrics(reference_observation.quality, temporal_quality)

        reference_observation.artifact_paths = artifact_paths
        reference_observation.temporal_support = support_payload
        reference_observation.diagnostics = {
            **reference_observation.diagnostics,
            'workingStage': reference_observation.working_stage,
            'stageScores': stage_scores,
            'artifacts': artifact_paths,
            'temporalSupport': support_payload,
            'temporalSelected': choose_temporal,
        }
        return reference_observation

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
            return self._deskew_plate(plate_image)

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

    def _deskew_plate(self, plate_image: Any) -> tuple[Any, dict[str, Any]]:
        cv2 = self._dependencies.cv2
        numpy = self._dependencies.numpy
        if cv2 is None or numpy is None or plate_image is None or getattr(plate_image, 'size', 0) == 0:
            return plate_image, {'applied': False, 'method': 'crop'}

        grayscale = cv2.cvtColor(plate_image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(grayscale, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 160)
        min_line_length = max(int(round(plate_image.shape[1] * 0.4)), 24)
        max_line_gap = max(int(round(plate_image.shape[1] * 0.12)), 6)
        lines = cv2.HoughLinesP(
            edges,
            1,
            numpy.pi / 180.0,
            threshold=24,
            minLineLength=min_line_length,
            maxLineGap=max_line_gap,
        )
        if lines is None:
            return plate_image, {'applied': False, 'method': 'crop'}

        weighted_angles: list[tuple[float, float]] = []
        for line in lines.reshape(-1, 4):
            x1, y1, x2, y2 = [int(value) for value in line]
            angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
            if abs(angle) > 45.0:
                continue
            length = math.hypot(x2 - x1, y2 - y1)
            if length < max(18.0, plate_image.shape[1] * 0.18):
                continue
            weighted_angles.append((angle, length))

        if not weighted_angles:
            return plate_image, {'applied': False, 'method': 'crop'}

        total_weight = sum(weight for _, weight in weighted_angles)
        weighted_angle = sum(angle * weight for angle, weight in weighted_angles) / max(total_weight, 1e-6)
        if abs(weighted_angle) < 2.0:
            return plate_image, {'applied': False, 'method': 'crop'}

        height, width = plate_image.shape[:2]
        center = (width / 2.0, height / 2.0)
        transform = cv2.getRotationMatrix2D(center, -weighted_angle, 1.0)
        cos_theta = abs(transform[0, 0])
        sin_theta = abs(transform[0, 1])
        bound_width = int(round((height * sin_theta) + (width * cos_theta)))
        bound_height = int(round((height * cos_theta) + (width * sin_theta)))
        transform[0, 2] += (bound_width / 2.0) - center[0]
        transform[1, 2] += (bound_height / 2.0) - center[1]
        rotated = cv2.warpAffine(
            plate_image,
            transform,
            (bound_width, bound_height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )
        return rotated, {
            'applied': True,
            'method': 'hough-deskew',
            'angle': weighted_angle,
            'linesUsed': len(weighted_angles),
        }

    def _enhance_plate(self, plate_image: Any) -> Any:
        cv2 = self._dependencies.cv2
        if cv2 is None or plate_image is None or getattr(plate_image, 'size', 0) == 0:
            return plate_image

        grayscale = cv2.cvtColor(plate_image, cv2.COLOR_BGR2GRAY)
        contrast = float(grayscale.std()) / 255.0
        brightness = float(grayscale.mean()) / 255.0
        clip_limit = 3.0 if contrast < 0.22 or brightness < 0.4 else 2.2
        tile_grid = (6, 6) if min(plate_image.shape[:2]) >= 96 else (4, 4)
        lab = cv2.cvtColor(plate_image, cv2.COLOR_BGR2LAB)
        channel_l, channel_a, channel_b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid)
        equalized_l = clahe.apply(channel_l)
        merged_lab = cv2.merge((equalized_l, channel_a, channel_b))
        enhanced = cv2.cvtColor(merged_lab, cv2.COLOR_LAB2BGR)
        filter_strength = 55 if contrast < 0.22 else 45
        denoised = cv2.bilateralFilter(enhanced, 7 if contrast < 0.22 else 5, filter_strength, filter_strength)
        softened = cv2.GaussianBlur(denoised, (0, 0), 0.95 if contrast < 0.22 else 1.2)
        sharpen_gain = 1.68 if contrast < 0.22 else 1.55
        return cv2.addWeighted(denoised, sharpen_gain, softened, -(sharpen_gain - 1.0), 0)

    def _should_restore(self, plate_image: Any, quality: QualityMetrics | None, options: AnalysisOptions, quality_route: str) -> bool:
        if options.restoration_mode == 'off' or plate_image is None:
            return False
        height, width = plate_image.shape[:2]
        if min(height, width) < 52:
            return True
        if quality is None:
            return True
        if quality_route == 'high-angle':
            return False
        if quality_route == 'tiny-plate':
            return True
        return (
            quality.overall_score < 0.66
            or quality.sharpness < 0.3
            or quality.glare_score < 0.46
            or quality.contrast < 0.36
            or (quality_route in {'motion-soft', 'low-light'} and quality.legibility_score < 0.76)
        )

    def _restore_plate(self, plate_image: Any, options: AnalysisOptions) -> tuple[Any | None, dict[str, Any]]:
        restoration_mode = (options.restoration_mode or 'off').strip().lower()
        if restoration_mode == 'off':
            return None, {'applied': False, 'backend': 'none', 'mode': restoration_mode}

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
        lab = cv2.cvtColor(denoised, cv2.COLOR_BGR2LAB)
        channel_l, channel_a, channel_b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.6, tileGridSize=(6, 6))
        restored_lab = cv2.merge((clahe.apply(channel_l), channel_a, channel_b))
        restored = cv2.cvtColor(restored_lab, cv2.COLOR_LAB2BGR)
        softened = cv2.GaussianBlur(restored, (0, 0), 1.0)
        return cv2.addWeighted(restored, 1.65, softened, -0.65, 0)

    def _align_image_to_reference(self, reference_image: Any, candidate_image: Any) -> tuple[Any | None, float]:
        cv2 = self._dependencies.cv2
        numpy = self._dependencies.numpy
        if cv2 is None or numpy is None:
            return None, 0.0

        reference_gray = cv2.cvtColor(reference_image, cv2.COLOR_BGR2GRAY).astype('float32') / 255.0
        candidate_gray = cv2.cvtColor(candidate_image, cv2.COLOR_BGR2GRAY).astype('float32') / 255.0
        warp_matrix = numpy.eye(2, 3, dtype='float32')
        criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 35, 1e-4)

        try:
            score, warp_matrix = cv2.findTransformECC(reference_gray, candidate_gray, warp_matrix, cv2.MOTION_AFFINE, criteria)
            aligned = cv2.warpAffine(
                candidate_image,
                warp_matrix,
                (reference_image.shape[1], reference_image.shape[0]),
                flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
            )
            return aligned, float(score)
        except Exception:
            try:
                (shift_x, shift_y), response = cv2.phaseCorrelate(reference_gray, candidate_gray)
                translation = numpy.array([[1.0, 0.0, shift_x], [0.0, 1.0, shift_y]], dtype='float32')
                aligned = cv2.warpAffine(candidate_image, translation, (reference_image.shape[1], reference_image.shape[0]))
                return aligned, float(response)
            except Exception:
                return None, 0.0

    def _build_temporal_support_summary(
        self,
        reference_observation: PlateObservation,
        support_observations: list[PlateObservation],
        source_stage: str,
        selected_stage: str,
        *,
        strategy: str,
        mean_alignment_score: float,
    ) -> dict[str, Any]:
        support_times = [reference_observation.time_ms, *[observation.time_ms for observation in support_observations]]
        support_window_ms = max(support_times) - min(support_times) if support_times else 0
        return {
            'strategy': strategy,
            'referenceTimeMs': reference_observation.time_ms,
            'supportFrameCount': len(support_times),
            'supportWindowMs': max(0, support_window_ms),
            'supportTimes': sorted(set(support_times)),
            'meanAlignmentScore': mean_alignment_score,
            'meanQualityScore': _observation_quality_score(reference_observation),
            'sourceStage': source_stage,
            'selectedStage': selected_stage,
        }


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


def _resolve_quality_route(plate_image: Any, quality: QualityMetrics | None) -> str:
    if plate_image is None or getattr(plate_image, 'shape', None) is None:
        return 'baseline'

    height, width = plate_image.shape[:2]
    if min(height, width) < 52:
        return 'tiny-plate'
    if quality is None:
        return 'unknown'
    if quality.angle_score < 0.58:
        return 'high-angle'
    if quality.glare_score < 0.42 or quality.contrast < 0.36:
        return 'low-light'
    if quality.sharpness < 0.3 or quality.legibility_score < 0.62:
        return 'motion-soft'
    return 'baseline'


def _select_working_stage(
    *,
    quality_route: str,
    stage_candidates: list[tuple[str, Any | None, QualityMetrics | None]],
) -> tuple[str, Any, QualityMetrics | None, dict[str, float]]:
    scored_candidates: list[tuple[str, Any, QualityMetrics | None, float]] = []
    stage_scores: dict[str, float] = {}

    for stage_name, stage_image, stage_quality in stage_candidates:
        if stage_image is None:
            continue
        stage_score = _working_stage_score(stage_name, stage_quality, quality_route)
        stage_scores[stage_name] = stage_score
        scored_candidates.append((stage_name, stage_image, stage_quality, stage_score))

    if not scored_candidates:
        raise ValueError('No candidate working stages were available for plate preprocessing.')

    selected_stage_name, selected_stage_image, selected_stage_quality, _ = max(
        scored_candidates,
        key=lambda item: (item[3], 1 if item[0] == 'enhanced' else 0, 1 if item[0] == 'rectified' else 0),
    )
    return selected_stage_name, selected_stage_image, selected_stage_quality, stage_scores


def _working_stage_score(stage_name: str, quality: QualityMetrics | None, quality_route: str) -> float:
    if quality is None:
        return -1.0

    score = (
        (quality.overall_score * 0.55)
        + (quality.legibility_score * 0.25)
        + (quality.sharpness * 0.12)
        + (quality.contrast * 0.08)
    )

    if stage_name == 'enhanced':
        score += 0.02 if quality_route in {'baseline', 'low-light', 'motion-soft'} else 0.0
    elif stage_name == 'rectified':
        score += 0.02 if quality_route == 'high-angle' else 0.0
    elif stage_name == 'restored':
        if quality_route == 'tiny-plate':
            score += 0.03
        elif quality_route in {'baseline', 'high-angle'}:
            score -= 0.04
        else:
            score -= 0.02

    return score


def _observation_quality_score(observation: PlateObservation) -> float:
    return observation.quality.overall_score if observation.quality is not None else 0.0


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
