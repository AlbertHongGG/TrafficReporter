from __future__ import annotations

from typing import Any

from traffic_lpr_runtime.domain.models import QualityMetrics


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
