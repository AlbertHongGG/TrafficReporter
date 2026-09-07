from __future__ import annotations

from pathlib import Path
from typing import Any

from traffic_lpr_runtime.domain.analysis_options import AnalysisOptions

from .observation import PlateObservation, _observation_quality_score
from .quality import _merge_quality_metrics


class TemporalMixin:
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
