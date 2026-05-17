from __future__ import annotations

from pathlib import Path
from typing import Any

from traffic_lpr_runtime.application.pipeline_support import AnalysisOptions
from traffic_lpr_runtime.application.preprocessing import PlateObservation
from traffic_lpr_runtime.domain.interfaces import PlateRecognizer
from traffic_lpr_runtime.domain.models import FrameSample, PlateCandidate
from traffic_lpr_runtime.domain.text import normalize_plate_text
from traffic_lpr_runtime.infrastructure.dependencies import DependencyRegistry


class CandidateFusionService:
    def __init__(self, dependencies: DependencyRegistry, primary_recognizer: PlateRecognizer) -> None:
        self._dependencies = dependencies
        self._primary_recognizer = primary_recognizer

    def rank_sample_candidates(
        self,
        baseline_candidates: list[PlateCandidate],
        crop_candidates: list[PlateCandidate],
        observation: PlateObservation | None,
    ) -> list[PlateCandidate]:
        aggregated: dict[str, PlateCandidate] = {}
        for candidate in [*baseline_candidates, *crop_candidates]:
            text = normalize_plate_text(candidate.text)
            if not text:
                continue
            quality_weight = candidate.quality.overall_score if candidate.quality else (observation.quality.overall_score if observation and observation.quality else 0.55)
            taiwan_prior = float((candidate.diagnostics or {}).get('taiwanPrior') or 1.0)
            source_weight = 1.04 if candidate.source.startswith('ocr:') else 0.96
            candidate.confidence = max(0.0, min(1.0, candidate.confidence * (0.72 + (quality_weight * 0.28)) * source_weight * taiwan_prior))

            current = aggregated.get(text)
            if current is None or candidate.confidence >= current.confidence:
                aggregated[text] = candidate

        return sorted(
            aggregated.values(),
            key=lambda candidate: (
                candidate.confidence,
                candidate.quality.overall_score if candidate.quality else 0.0,
            ),
            reverse=True,
        )

    def aggregate_candidates(
        self,
        samples: list[FrameSample],
        observations: list[PlateObservation],
        country_hints: list[str],
        options: AnalysisOptions,
        artifact_root: Path | None,
    ) -> tuple[list[PlateCandidate], dict[str, Any]]:
        source_weights = {
            'baseline': 0.96,
            'fused': 1.08,
            'legacy-vote': 1.0,
            'fused-char': 1.12,
            'fused-image': 1.16,
        }
        aggregated: dict[str, dict[str, Any]] = {}
        candidate_pool: list[PlateCandidate] = []

        for sample in samples:
            for candidate in sample.candidates:
                candidate_pool.append(candidate)

        char_fused_candidate = self._fuse_by_character_position(samples)
        if char_fused_candidate is not None:
            candidate_pool.append(char_fused_candidate)

        legacy_candidate = self._legacy_vote_candidate(samples)
        if legacy_candidate is not None:
            candidate_pool.append(legacy_candidate)

        fused_image_candidates, fused_image_diagnostics = self._fuse_aligned_plate_images(
            observations,
            country_hints,
            options,
            artifact_root,
        )
        candidate_pool.extend(fused_image_candidates)

        for candidate in candidate_pool:
            text = normalize_plate_text(candidate.text)
            if not text:
                continue
            source_key = candidate.source.split(':', 1)[0]
            quality_weight = candidate.quality.overall_score if candidate.quality else 0.55
            taiwan_prior = float((candidate.diagnostics or {}).get('taiwanPrior') or 1.0)
            weight = candidate.confidence * quality_weight * source_weights.get(source_key, 1.0) * taiwan_prior

            current = aggregated.get(text)
            if current is None:
                aggregated[text] = {
                    'weight': weight,
                    'supportFrames': {candidate.frame_time_ms} if candidate.frame_time_ms is not None else set(),
                    'best_raw_confidence': candidate.confidence,
                    'candidate': PlateCandidate(
                        id=f'candidate-{len(aggregated)}',
                        text=text,
                        confidence=weight,
                        source='fused',
                        frame_time_ms=candidate.frame_time_ms,
                        country_code=candidate.country_code,
                        box=candidate.box,
                        quality=candidate.quality,
                        diagnostics={
                            'supportFrames': [candidate.frame_time_ms] if candidate.frame_time_ms is not None else [],
                            'sources': [candidate.source],
                        },
                    ),
                }
                continue

            current['weight'] += weight
            if candidate.frame_time_ms is not None:
                current['supportFrames'].add(candidate.frame_time_ms)
            diagnostics = current['candidate'].diagnostics or {'supportFrames': [], 'sources': []}
            diagnostics['supportFrames'] = sorted(time for time in current['supportFrames'] if time is not None)
            diagnostics['sources'] = sorted({*diagnostics.get('sources', []), candidate.source})
            current['candidate'].diagnostics = diagnostics
            if candidate.confidence >= current['best_raw_confidence']:
                current['best_raw_confidence'] = candidate.confidence
                current['candidate'].frame_time_ms = candidate.frame_time_ms
                current['candidate'].country_code = candidate.country_code
                current['candidate'].box = candidate.box
                current['candidate'].quality = candidate.quality

        ranked = sorted(aggregated.values(), key=lambda item: item['weight'], reverse=True)
        if not ranked:
            return [], {
                'fusionMode': options.fusion_mode,
                'candidatePoolSize': len(candidate_pool),
                'fusedImage': fused_image_diagnostics,
            }

        best_weight = max(item['weight'] for item in ranked) or 1.0
        fused_candidates: list[PlateCandidate] = []
        for item in ranked[:8]:
            candidate = item['candidate']
            candidate.confidence = max(0.0, min(1.0, item['weight'] / best_weight))
            fused_candidates.append(candidate)

        return fused_candidates, {
            'fusionMode': options.fusion_mode,
            'candidatePoolSize': len(candidate_pool),
            'charFusionApplied': char_fused_candidate is not None,
            'legacyVoteApplied': legacy_candidate is not None,
            'fusedImage': fused_image_diagnostics,
        }

    def _legacy_vote_candidate(self, samples: list[FrameSample]) -> PlateCandidate | None:
        weighted_by_text: dict[str, float] = {}
        representative: PlateCandidate | None = None
        for sample in samples:
            candidate = sample.candidates[0] if sample.candidates else None
            if candidate is None:
                continue
            text = normalize_plate_text(candidate.text)
            if not text:
                continue
            weighted_by_text[text] = weighted_by_text.get(text, 0.0) + candidate.confidence
            if representative is None or candidate.confidence > representative.confidence:
                representative = candidate

        if not weighted_by_text or representative is None:
            return None
        fused_text = max(weighted_by_text.items(), key=lambda item: item[1])[0]
        return PlateCandidate(
            id='legacy-vote-0',
            text=fused_text,
            confidence=max(weighted_by_text.values()) / max(sum(weighted_by_text.values()), 1.0),
            source='legacy-vote',
            frame_time_ms=representative.frame_time_ms,
            country_code=representative.country_code,
            box=representative.box,
            quality=representative.quality,
            diagnostics={'supportTexts': weighted_by_text},
        )

    def _fuse_by_character_position(self, samples: list[FrameSample]) -> PlateCandidate | None:
        length_votes: dict[int, float] = {}
        best_candidate: PlateCandidate | None = None
        for sample in samples:
            candidate = sample.candidates[0] if sample.candidates else None
            if candidate is None:
                continue
            text = normalize_plate_text(candidate.text)
            if not text:
                continue
            weight = candidate.confidence * (candidate.quality.overall_score if candidate.quality else 0.55)
            length_votes[len(text)] = length_votes.get(len(text), 0.0) + weight
            if best_candidate is None or candidate.confidence > best_candidate.confidence:
                best_candidate = candidate

        if not length_votes or best_candidate is None:
            return None

        target_length = max(length_votes.items(), key=lambda item: item[1])[0]
        position_votes: list[dict[str, float]] = [dict() for _ in range(target_length)]
        support_frames: list[int] = []

        for sample in samples:
            candidate = sample.candidates[0] if sample.candidates else None
            if candidate is None:
                continue
            text = normalize_plate_text(candidate.text)
            if not text or abs(len(text) - target_length) > 1:
                continue
            char_confidences = list((candidate.diagnostics or {}).get('charConfidences') or [])
            sample_weight = candidate.confidence * (candidate.quality.overall_score if candidate.quality else 0.55)
            for index, character in enumerate(text[:target_length]):
                character_weight = sample_weight * (float(char_confidences[index]) if index < len(char_confidences) else 1.0)
                position_votes[index][character] = position_votes[index].get(character, 0.0) + character_weight
            if candidate.frame_time_ms is not None:
                support_frames.append(candidate.frame_time_ms)

        if any(not votes for votes in position_votes):
            return None

        fused_text = ''.join(max(votes.items(), key=lambda item: item[1])[0] for votes in position_votes)
        confidence = sum(max(votes.values()) / max(sum(votes.values()), 1.0) for votes in position_votes) / len(position_votes)
        return PlateCandidate(
            id='fused-char-0',
            text=fused_text,
            confidence=confidence,
            source='fused-char',
            frame_time_ms=best_candidate.frame_time_ms,
            country_code=best_candidate.country_code,
            box=best_candidate.box,
            quality=best_candidate.quality,
            diagnostics={'supportFrames': sorted(set(support_frames)), 'targetLength': target_length},
        )

    def _fuse_aligned_plate_images(
        self,
        observations: list[PlateObservation],
        country_hints: list[str],
        options: AnalysisOptions,
        artifact_root: Path | None,
    ) -> tuple[list[PlateCandidate], dict[str, Any]]:
        if len(observations) < 2 or self._dependencies.cv2 is None or self._dependencies.numpy is None:
            return [], {'applied': False, 'reason': 'insufficient-observations'}

        cv2 = self._dependencies.cv2
        reference = max(observations, key=lambda observation: observation.quality.overall_score if observation.quality else 0.0)
        reference_image = reference.working_image
        if reference_image is None or getattr(reference_image, 'size', 0) == 0:
            return [], {'applied': False, 'reason': 'empty-reference'}

        reference_height, reference_width = reference_image.shape[:2]
        accum = reference_image.astype('float32')
        total_weight = 1.0
        support = 1
        alignment_scores: list[float] = [1.0]

        for observation in observations:
            if observation is reference:
                continue
            candidate_image = observation.working_image
            if candidate_image is None or getattr(candidate_image, 'size', 0) == 0:
                continue
            resized = cv2.resize(candidate_image, (reference_width, reference_height), interpolation=cv2.INTER_LANCZOS4)
            aligned, score = self._align_plate_to_reference(reference_image, resized)
            if aligned is None or score < options.min_alignment_score:
                continue

            weight = max(observation.quality.overall_score if observation.quality else 0.55, 0.2) * max(score, 0.2)
            accum += aligned.astype('float32') * weight
            total_weight += weight
            support += 1
            alignment_scores.append(score)

        if support < 2:
            return [], {'applied': False, 'reason': 'insufficient-aligned'}

        fused_image = (accum / max(total_weight, 1.0)).clip(0, 255).astype('uint8')
        if artifact_root is not None:
            fused_path = artifact_root / 'fused-image.png'
            cv2.imwrite(str(fused_path), fused_image)

        fused_candidates = self._primary_recognizer.recognize_plate_crop(
            fused_image,
            reference.time_ms,
            reference.plate_box,
            country_hints,
            options.ocr_models()[:2],
        )
        for candidate in fused_candidates:
            if candidate.source.startswith('ocr:'):
                candidate.source = f'fused-image:{candidate.source.split(":", 1)[1]}'
            candidate.diagnostics = (candidate.diagnostics or {}) | {
                'supportFrames': support,
                'meanAlignmentScore': sum(alignment_scores) / len(alignment_scores),
            }

        return fused_candidates, {
            'applied': True,
            'supportFrames': support,
            'meanAlignmentScore': sum(alignment_scores) / len(alignment_scores),
        }

    def _align_plate_to_reference(self, reference_image: Any, candidate_image: Any) -> tuple[Any | None, float]:
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


def apply_reliability_selection(
    candidates: list[PlateCandidate],
    samples: list[FrameSample],
    country_hints: list[str],
    options: AnalysisOptions,
    interval_mode: bool,
) -> tuple[list[PlateCandidate], str | None, dict[str, Any]]:
    if not candidates:
        return [], None, {
            'acceptedCandidateId': None,
            'suggestedCandidateId': None,
            'fallbackCandidateId': None,
            'reviewRequired': True,
            'usedFallback': False,
            'reasons': ['no-candidate'],
        }

    ordered_candidates = list(candidates)
    top_candidate = ordered_candidates[0]
    fallback_candidate = _best_sample_candidate(samples, country_hints)
    accepted_margin = max(0.0, top_candidate.confidence - (ordered_candidates[1].confidence if len(ordered_candidates) > 1 else 0.0))

    review_reasons = [] if not options.enable_reliability_gates else _review_reasons(
        top_candidate,
        accepted_margin,
        country_hints,
        options,
        interval_mode,
    )
    suggested_candidate = top_candidate
    used_fallback = False
    if review_reasons and fallback_candidate is not None and fallback_candidate.id != top_candidate.id:
        top_score = _candidate_reliability_score(top_candidate, country_hints)
        fallback_score = _candidate_reliability_score(fallback_candidate, country_hints)
        format_advantage = _plate_format_score(fallback_candidate.text, country_hints) - _plate_format_score(top_candidate.text, country_hints)
        if fallback_score >= top_score + 0.05 or format_advantage >= 0.2:
            suggested_candidate = fallback_candidate
            used_fallback = True
            review_reasons = [] if not options.enable_reliability_gates else _review_reasons(
                suggested_candidate,
                max(0.0, suggested_candidate.confidence - top_candidate.confidence),
                country_hints,
                options,
                interval_mode,
            )

    if all(candidate.id != suggested_candidate.id for candidate in ordered_candidates):
        ordered_candidates.insert(0, suggested_candidate)
    else:
        ordered_candidates.sort(key=lambda candidate: 0 if candidate.id == suggested_candidate.id else 1)

    review_required = bool(review_reasons)
    accepted_candidate_id = None if review_required else suggested_candidate.id
    selection_diagnostics = {
        'acceptedCandidateId': accepted_candidate_id,
        'suggestedCandidateId': suggested_candidate.id,
        'fallbackCandidateId': fallback_candidate.id if fallback_candidate is not None else None,
        'topCandidateId': top_candidate.id,
        'reviewRequired': review_required,
        'usedFallback': used_fallback,
        'reasons': review_reasons,
        'acceptedMargin': accepted_margin,
        'suggestedConfidence': suggested_candidate.confidence,
        'supportFrameCount': _candidate_support_frame_count(suggested_candidate),
        'formatScore': _plate_format_score(suggested_candidate.text, country_hints),
    }

    for candidate in ordered_candidates:
        candidate.diagnostics = {
            **(candidate.diagnostics or {}),
            'selection': {
                'isAccepted': candidate.id == accepted_candidate_id,
                'isSuggested': candidate.id == suggested_candidate.id,
                'reviewRequired': review_required,
                'usedFallback': used_fallback and candidate.id == suggested_candidate.id,
                'reasons': review_reasons if candidate.id == suggested_candidate.id else [],
            },
        }
    return ordered_candidates[:8], accepted_candidate_id, selection_diagnostics


def _review_reasons(
    candidate: PlateCandidate,
    accepted_margin: float,
    country_hints: list[str],
    options: AnalysisOptions,
    interval_mode: bool,
) -> list[str]:
    reasons: list[str] = []
    if candidate.confidence < options.min_accepted_confidence:
        reasons.append('low-confidence')
    if accepted_margin < options.min_candidate_margin:
        reasons.append('low-margin')
    if interval_mode and _candidate_support_frame_count(candidate) < options.min_interval_support_frames:
        reasons.append('insufficient-support')
    if _uses_taiwan_hint(country_hints) and _plate_format_score(candidate.text, country_hints) < 0.65:
        reasons.append('format-mismatch')
    return reasons


def _best_sample_candidate(samples: list[FrameSample], country_hints: list[str]) -> PlateCandidate | None:
    best_candidate: PlateCandidate | None = None
    best_score = 0.0
    for sample in samples:
        for candidate in sample.candidates:
            score = _candidate_reliability_score(candidate, country_hints)
            if best_candidate is None or score > best_score:
                best_candidate = candidate
                best_score = score
    return best_candidate


def _candidate_reliability_score(candidate: PlateCandidate, country_hints: list[str]) -> float:
    quality_score = candidate.quality.overall_score if candidate.quality is not None else 0.0
    support_score = min(_candidate_support_frame_count(candidate), 4) / 4.0
    format_score = _plate_format_score(candidate.text, country_hints)
    return (
        (candidate.confidence * 0.58)
        + (quality_score * 0.20)
        + (support_score * 0.12)
        + (format_score * 0.10)
    )


def _candidate_support_frame_count(candidate: PlateCandidate) -> int:
    diagnostics = candidate.diagnostics or {}
    support_frames = diagnostics.get('supportFrames')
    if isinstance(support_frames, list):
        return len({int(frame) for frame in support_frames if isinstance(frame, (int, float))})
    if isinstance(support_frames, (int, float)):
        return max(1, int(support_frames))
    return 1 if candidate.frame_time_ms is not None else 0


def _plate_format_score(text: str | None, country_hints: list[str]) -> float:
    normalized = normalize_plate_text(text)
    if not normalized:
        return 0.0
    if _uses_taiwan_hint(country_hints):
        if len(normalized) < 5 or len(normalized) > 7:
            return 0.2
        if any(character in {'I', 'O', 'Q'} for character in normalized):
            return 0.55
        if normalized[:2].isalpha() and normalized[-4:].isdigit():
            return 1.0
        if normalized[:3].isalpha() and normalized[-4:].isdigit() and len(normalized) == 7:
            return 0.94
        if normalized[:4].isalpha() and normalized[-3:].isdigit() and len(normalized) == 7:
            return 0.9
        if normalized[:3].isdigit() and normalized[-4:].isalpha() and len(normalized) == 7:
            return 0.82
        if any(character.isalpha() for character in normalized) and any(character.isdigit() for character in normalized):
            return 0.68
        return 0.35
    return 1.0 if 5 <= len(normalized) <= 8 else 0.5


def _uses_taiwan_hint(country_hints: list[str]) -> bool:
    return any(str(hint).upper() in {'TW', 'TWN', 'TAIWAN'} for hint in country_hints)
