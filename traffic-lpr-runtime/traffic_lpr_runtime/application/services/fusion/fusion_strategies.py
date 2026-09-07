from __future__ import annotations

from pathlib import Path
from typing import Any

from traffic_lpr_runtime.application.services.fusion.candidate_scoring import (
    _best_frame_candidate,
    _candidate_support_frames_payload,
    _candidate_weight,
    _consensus_signal_names,
    _consensus_weight_multiplier,
    _source_family,
)
from traffic_lpr_runtime.application.services.fusion.plate_format import (
    _looks_like_taiwan_long_plate,
    _looks_like_taiwan_short_plate,
    _plate_format_score,
    _uses_taiwan_hint,
)
from traffic_lpr_runtime.application.services.fusion.sequence_analysis import (
    _ordered_top_sample_candidates,
    _sequence_confidence_cap,
    _sequence_tier,
    _support_gap_count,
)
from traffic_lpr_runtime.domain.analysis_options import AnalysisOptions
from traffic_lpr_runtime.application.services.preprocessing import PlateObservation
from traffic_lpr_runtime.domain.interfaces import PlateRecognizer
from traffic_lpr_runtime.domain.models import FrameSample, PlateCandidate
from traffic_lpr_runtime.domain.text import normalize_plate_text
from traffic_lpr_runtime.infrastructure.dependencies import DependencyRegistry


MAX_INTERVAL_FUSION_OBSERVATIONS = 6


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
            'fused-char-tw-long': 1.2,
            'fused-image': 1.16,
        }
        aggregated: dict[str, dict[str, Any]] = {}
        candidate_pool: list[PlateCandidate] = []
        ordered_sample_times = [sample.time_ms for sample in sorted(samples, key=lambda item: item.time_ms)]

        for sample in samples:
            for candidate in sample.candidates:
                candidate_pool.append(candidate)

        char_fused_candidate = self._fuse_by_character_position(samples, country_hints)
        if char_fused_candidate is not None:
            candidate_pool.append(char_fused_candidate)

        taiwan_long_fused_candidate = self._fuse_taiwan_long_plate(samples, country_hints)
        if taiwan_long_fused_candidate is not None:
            candidate_pool.append(taiwan_long_fused_candidate)

        legacy_candidate = self._legacy_vote_candidate(samples)
        if legacy_candidate is not None:
            candidate_pool.append(legacy_candidate)

        sequence_summary = self._build_sequence_summary(samples, char_fused_candidate)
        dominant_sequence_text = normalize_plate_text(sequence_summary.get('dominantText'))
        char_fused_text = normalize_plate_text(char_fused_candidate.text) if char_fused_candidate is not None else ''
        if char_fused_candidate is not None:
            char_fused_candidate.diagnostics = {
                **(char_fused_candidate.diagnostics or {}),
                'characterConsistencyMean': float(sequence_summary.get('characterConsistencyMean') or 0.0),
                'dominantSequenceText': sequence_summary.get('dominantText'),
                'matchesDominantSequence': bool(char_fused_text) and char_fused_text == dominant_sequence_text,
            }

        fused_image_candidates, fused_image_diagnostics = self._fuse_aligned_plate_images(
            observations,
            country_hints,
            options,
            artifact_root,
        )
        candidate_pool.extend(fused_image_candidates)

        has_long_taiwan_hypothesis = _uses_taiwan_hint(country_hints) and any(
            _looks_like_taiwan_long_plate(candidate.text)
            for candidate in candidate_pool
        )

        for candidate in candidate_pool:
            text = normalize_plate_text(candidate.text)
            if not text:
                continue
            weight = _candidate_weight(candidate, source_weights)
            if has_long_taiwan_hypothesis:
                if _looks_like_taiwan_long_plate(text):
                    weight *= 1.12
                elif _looks_like_taiwan_short_plate(text):
                    weight *= 0.52
                else:
                    weight *= 0.34

            current = aggregated.get(text)
            if current is None:
                support_frame_payload = _candidate_support_frames_payload(candidate)
                aggregated[text] = {
                    'weight': weight,
                    'supportFrames': support_frame_payload,
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
                            'supportFrames': sorted(support_frame_payload),
                            'sources': [candidate.source],
                            'sourceFamilies': [_source_family(candidate.source)],
                            'contributionCount': 1,
                        },
                    ),
                }
                continue

            current['weight'] += weight
            current['supportFrames'].update(_candidate_support_frames_payload(candidate))
            diagnostics = current['candidate'].diagnostics or {'supportFrames': [], 'sources': []}
            diagnostics['supportFrames'] = sorted(time for time in current['supportFrames'] if time is not None)
            diagnostics['sources'] = sorted({*diagnostics.get('sources', []), candidate.source})
            diagnostics['sourceFamilies'] = sorted({*diagnostics.get('sourceFamilies', []), _source_family(candidate.source)})
            diagnostics['contributionCount'] = int(diagnostics.get('contributionCount') or 0) + 1
            current['candidate'].diagnostics = diagnostics
            if candidate.confidence >= current['best_raw_confidence']:
                current['best_raw_confidence'] = candidate.confidence
                current['candidate'].frame_time_ms = candidate.frame_time_ms
                current['candidate'].country_code = candidate.country_code
                current['candidate'].box = candidate.box
                current['candidate'].quality = candidate.quality

        best_frame_candidate, best_frame_weight = _best_frame_candidate(samples, source_weights)
        best_frame_text = normalize_plate_text(best_frame_candidate.text) if best_frame_candidate is not None else ''
        if best_frame_candidate is not None and best_frame_weight >= max(options.min_accepted_confidence, 0.68):
            best_text = normalize_plate_text(best_frame_candidate.text)
            current = aggregated.get(best_text)
            support_frame_count = len(current['supportFrames']) if current is not None else 1
            consensus_signals = _consensus_signal_names(
                best_text,
                dominant_sequence_text,
                char_fused_text,
                best_frame_text,
            )
            sequence_persistence = float(sequence_summary.get('persistenceRatio') or 0.0)
            sequence_consistency = float(sequence_summary.get('characterConsistencyMean') or 0.0)
            allow_carry = support_frame_count >= 2 or (
                best_text == dominant_sequence_text
                and sequence_persistence >= options.min_sequence_persistence
                and sequence_consistency >= 0.68
            )
            carry_multiplier = 0.0
            if allow_carry:
                carry_multiplier = 0.58 if support_frame_count <= 1 else 0.72
                if len(consensus_signals) >= 2 and support_frame_count >= 2:
                    carry_multiplier += 0.12
                if len(consensus_signals) >= 3 and sequence_persistence >= options.min_sequence_persistence:
                    carry_multiplier += 0.06
            carry_weight = best_frame_weight * carry_multiplier

            if carry_weight <= 0.0:
                pass
            elif current is None:
                aggregated[best_text] = {
                    'weight': carry_weight,
                    'supportFrames': {best_frame_candidate.frame_time_ms} if best_frame_candidate.frame_time_ms is not None else set(),
                    'best_raw_confidence': best_frame_candidate.confidence,
                    'candidate': PlateCandidate(
                        id=f'candidate-{len(aggregated)}',
                        text=best_text,
                        confidence=carry_weight,
                        source='fused',
                        frame_time_ms=best_frame_candidate.frame_time_ms,
                        country_code=best_frame_candidate.country_code,
                        box=best_frame_candidate.box,
                        quality=best_frame_candidate.quality,
                        diagnostics={
                            'supportFrames': [best_frame_candidate.frame_time_ms] if best_frame_candidate.frame_time_ms is not None else [],
                            'sources': [best_frame_candidate.source],
                            'sourceFamilies': [_source_family(best_frame_candidate.source)],
                            'contributionCount': 1,
                            'bestFrameCarryThrough': True,
                            'bestFrameTimeMs': best_frame_candidate.frame_time_ms,
                            'bestFrameWeight': best_frame_weight,
                            'bestFrameCarryMultiplier': carry_multiplier,
                            'bestFrameConsensusSignals': consensus_signals,
                        },
                    ),
                }
            elif current is not None:
                current['weight'] += carry_weight
                diagnostics = current['candidate'].diagnostics or {'supportFrames': [], 'sources': []}
                diagnostics['bestFrameCarryThrough'] = True
                diagnostics['bestFrameTimeMs'] = best_frame_candidate.frame_time_ms
                diagnostics['bestFrameWeight'] = best_frame_weight
                diagnostics['bestFrameCarryMultiplier'] = carry_multiplier
                diagnostics['bestFrameConsensusSignals'] = consensus_signals
                diagnostics['sources'] = sorted({*diagnostics.get('sources', []), best_frame_candidate.source})
                diagnostics['sourceFamilies'] = sorted({*diagnostics.get('sourceFamilies', []), _source_family(best_frame_candidate.source)})
                diagnostics['contributionCount'] = int(diagnostics.get('contributionCount') or 0) + 1
                current['candidate'].diagnostics = diagnostics
                if best_frame_candidate.confidence >= current['best_raw_confidence']:
                    current['best_raw_confidence'] = best_frame_candidate.confidence
                    current['candidate'].frame_time_ms = best_frame_candidate.frame_time_ms
                    current['candidate'].country_code = best_frame_candidate.country_code
                    current['candidate'].box = best_frame_candidate.box
                    current['candidate'].quality = best_frame_candidate.quality

        for text, item in aggregated.items():
            diagnostics = item['candidate'].diagnostics or {}
            support_frames = [
                int(time_ms)
                for time_ms in (diagnostics.get('supportFrames') or [])
                if isinstance(time_ms, (int, float))
            ]
            source_families = [value for value in diagnostics.get('sourceFamilies') or [] if isinstance(value, str)]
            consensus_signals = _consensus_signal_names(
                text,
                dominant_sequence_text,
                char_fused_text,
                best_frame_text,
            )
            consensus_multiplier = _consensus_weight_multiplier(
                consensus_signals,
                len(set(support_frames)),
                len(set(source_families)),
            )
            item['weight'] *= consensus_multiplier
            item['candidate'].diagnostics = {
                **diagnostics,
                'supportFrames': sorted(set(support_frames)),
                'sourceFamilies': sorted(set(source_families)),
                'supportFrameCount': len(set(support_frames)),
                'sourceCount': len(set(source_families)),
                'consensusSignals': consensus_signals,
                'consensusMultiplier': consensus_multiplier,
            }

        ranked = sorted(aggregated.values(), key=lambda item: item['weight'], reverse=True)
        if not ranked:
            return [], {
                'fusionMode': options.fusion_mode,
                'candidatePoolSize': len(candidate_pool),
                'fusedImage': fused_image_diagnostics,
            }

        best_weight = max(item['weight'] for item in ranked) or 1.0
        runner_up_text = ranked[1]['candidate'].text if len(ranked) > 1 else None
        runner_up_weight = ranked[1]['weight'] if len(ranked) > 1 else 0.0
        fused_candidates: list[PlateCandidate] = []
        for index, item in enumerate(ranked[:8]):
            candidate = item['candidate']
            candidate.confidence = max(0.0, min(1.0, item['weight'] / best_weight))
            support_frames = [
                int(time_ms)
                for time_ms in ((candidate.diagnostics or {}).get('supportFrames') or [])
                if time_ms is not None
            ]
            support_ratio = len(support_frames) / max(len(ordered_sample_times), 1)
            gap_count = _support_gap_count(support_frames, ordered_sample_times)
            candidate.diagnostics = {
                **(candidate.diagnostics or {}),
                'sequenceSupportRatio': support_ratio,
                'sequenceGapCount': gap_count,
                'sequenceTier': (
                    sequence_summary['sequenceTier']
                    if candidate.text == sequence_summary.get('dominantText')
                    else _sequence_tier(
                        support_ratio,
                        gap_count,
                        int(sequence_summary.get('predictionSwitchCount') or 0),
                        len(support_frames),
                        float(sequence_summary.get('characterConsistencyMean') or 0.0),
                    )
                ),
                'sequencePersistenceRatio': sequence_summary['persistenceRatio'],
                'sequenceCharacterConsistency': sequence_summary['characterConsistency'],
                'sequenceCharacterConsistencyMean': sequence_summary.get('characterConsistencyMean'),
                'dominantSequenceText': sequence_summary.get('dominantText'),
                'aggregatedWeight': item['weight'],
                'normalizedWeight': candidate.confidence,
            }
            candidate.confidence = min(candidate.confidence, _sequence_confidence_cap(candidate, sequence_summary, options))
            candidate.diagnostics = {
                **(candidate.diagnostics or {}),
                'sequenceConfidenceCap': candidate.confidence,
            }
            if index == 0:
                candidate.diagnostics = {
                    **candidate.diagnostics,
                    'runnerUpText': runner_up_text,
                    'runnerUpWeight': runner_up_weight,
                    'marginToRunnerUp': max(0.0, item['weight'] - runner_up_weight),
                }
            fused_candidates.append(candidate)

        return fused_candidates, {
            'fusionMode': options.fusion_mode,
            'candidatePoolSize': len(candidate_pool),
            'charFusionApplied': char_fused_candidate is not None,
            'taiwanLongFusionApplied': taiwan_long_fused_candidate is not None,
            'legacyVoteApplied': legacy_candidate is not None,
            'fusedImage': fused_image_diagnostics,
            'sequence': sequence_summary,
            'candidateRanking': {
                'leaderText': ranked[0]['candidate'].text,
                'runnerUpText': runner_up_text,
                'leaderWeight': ranked[0]['weight'],
                'runnerUpWeight': runner_up_weight,
                'weightMargin': max(0.0, ranked[0]['weight'] - runner_up_weight),
            },
        }

    def _build_sequence_summary(
        self,
        samples: list[FrameSample],
        char_fused_candidate: PlateCandidate | None,
    ) -> dict[str, Any]:
        ordered_candidates = _ordered_top_sample_candidates(samples)
        readable_entries = [(time_ms, text) for time_ms, _, text in ordered_candidates if text]
        sample_count = len(ordered_candidates)
        support_frame_count = len(readable_entries)
        if support_frame_count == 0:
            return {
                'sequenceTier': 'fragmented',
                'dominantText': None,
                'persistenceRatio': 0.0,
                'supportFrameCount': 0,
                'sampleCount': sample_count,
                'supportFrameGapCount': 0,
                'predictionSwitchCount': 0,
                'characterConsistency': [],
                'characterConsistencyMean': 0.0,
            }

        support_text_counts: dict[str, int] = {}
        support_frames: list[int] = []
        prediction_switch_count = 0
        previous_text: str | None = None
        for time_ms, text in readable_entries:
            support_text_counts[text] = support_text_counts.get(text, 0) + 1
            support_frames.append(time_ms)
            if previous_text is not None and previous_text != text:
                prediction_switch_count += 1
            previous_text = text

        dominant_text = max(
            support_text_counts.items(),
            key=lambda item: (item[1], len(item[0]), item[0]),
        )[0]
        persistence_ratio = support_text_counts[dominant_text] / max(support_frame_count, 1)
        support_frame_gap_count = _support_gap_count(
            support_frames,
            [time_ms for time_ms, _, _ in ordered_candidates],
        )
        character_consistency = [
            float(value)
            for value in ((char_fused_candidate.diagnostics or {}).get('characterConsistency') or [])
            if isinstance(value, (int, float))
        ] if char_fused_candidate is not None else []
        character_consistency_mean = (
            sum(character_consistency) / len(character_consistency)
            if character_consistency
            else persistence_ratio
        )
        return {
            'sequenceTier': _sequence_tier(
                persistence_ratio,
                support_frame_gap_count,
                prediction_switch_count,
                support_frame_count,
                character_consistency_mean,
            ),
            'dominantText': dominant_text,
            'persistenceRatio': persistence_ratio,
            'supportFrameCount': support_frame_count,
            'sampleCount': sample_count,
            'supportFrameGapCount': support_frame_gap_count,
            'predictionSwitchCount': prediction_switch_count,
            'characterConsistency': character_consistency,
            'characterConsistencyMean': character_consistency_mean,
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

    def _fuse_by_character_position(self, samples: list[FrameSample], country_hints: list[str]) -> PlateCandidate | None:
        length_votes: dict[int, float] = {}
        best_candidate: PlateCandidate | None = None
        for sample in samples:
            for rank, candidate in enumerate(sample.candidates[:3]):
                text = normalize_plate_text(candidate.text)
                if not text:
                    continue
                rank_penalty = max(0.55, 1.0 - (rank * 0.18))
                format_score = _plate_format_score(text, country_hints)
                weight = candidate.confidence * (candidate.quality.overall_score if candidate.quality else 0.55) * rank_penalty * max(format_score, 0.35)
                if _uses_taiwan_hint(country_hints) and _looks_like_taiwan_long_plate(text):
                    weight *= 1.22
                elif _uses_taiwan_hint(country_hints) and _looks_like_taiwan_short_plate(text):
                    weight *= 0.9
                length_votes[len(text)] = length_votes.get(len(text), 0.0) + weight
                if best_candidate is None or candidate.confidence > best_candidate.confidence:
                    best_candidate = candidate

        if not length_votes or best_candidate is None:
            return None

        target_length = max(length_votes.items(), key=lambda item: item[1])[0]
        position_votes: list[dict[str, float]] = [dict() for _ in range(target_length)]
        support_frames: list[int] = []

        for sample in samples:
            for rank, candidate in enumerate(sample.candidates[:3]):
                text = normalize_plate_text(candidate.text)
                if not text or len(text) != target_length:
                    continue
                char_confidences = list((candidate.diagnostics or {}).get('charConfidences') or [])
                rank_penalty = max(0.55, 1.0 - (rank * 0.18))
                format_score = _plate_format_score(text, country_hints)
                sample_weight = candidate.confidence * (candidate.quality.overall_score if candidate.quality else 0.55) * rank_penalty * max(format_score, 0.35)
                if _uses_taiwan_hint(country_hints) and _looks_like_taiwan_long_plate(text):
                    sample_weight *= 1.22
                elif _uses_taiwan_hint(country_hints) and _looks_like_taiwan_short_plate(text):
                    sample_weight *= 0.9
                for index, character in enumerate(text[:target_length]):
                    character_weight = sample_weight * (float(char_confidences[index]) if index < len(char_confidences) else 1.0)
                    position_votes[index][character] = position_votes[index].get(character, 0.0) + character_weight
                if candidate.frame_time_ms is not None:
                    support_frames.append(candidate.frame_time_ms)

        if any(not votes for votes in position_votes):
            return None

        fused_text = ''.join(max(votes.items(), key=lambda item: item[1])[0] for votes in position_votes)
        character_consistency = [
            max(votes.values()) / max(sum(votes.values()), 1.0)
            for votes in position_votes
        ]
        confidence = sum(character_consistency) / len(position_votes)
        return PlateCandidate(
            id='fused-char-0',
            text=fused_text,
            confidence=confidence,
            source='fused-char',
            frame_time_ms=best_candidate.frame_time_ms,
            country_code=best_candidate.country_code,
            box=best_candidate.box,
            quality=best_candidate.quality,
            diagnostics={
                'supportFrames': sorted(set(support_frames)),
                'targetLength': target_length,
                'characterConsistency': character_consistency,
                'characterConsistencyMean': confidence,
            },
        )

    def _fuse_taiwan_long_plate(self, samples: list[FrameSample], country_hints: list[str]) -> PlateCandidate | None:
        if not _uses_taiwan_hint(country_hints):
            return None

        position_votes: list[dict[str, float]] = [dict() for _ in range(7)]
        support_frames: list[int] = []
        representative: PlateCandidate | None = None
        contribution_count = 0

        for sample in samples:
            for rank, candidate in enumerate(sample.candidates[:4]):
                text = normalize_plate_text(candidate.text)
                if not _looks_like_taiwan_long_plate(text):
                    continue
                char_confidences = list((candidate.diagnostics or {}).get('charConfidences') or [])
                rank_penalty = max(0.5, 1.0 - (rank * 0.16))
                quality_score = candidate.quality.overall_score if candidate.quality else 0.55
                sample_weight = candidate.confidence * quality_score * rank_penalty
                for index, character in enumerate(text[:7]):
                    character_confidence = float(char_confidences[index]) if index < len(char_confidences) else 0.65
                    position_votes[index][character] = position_votes[index].get(character, 0.0) + (sample_weight * max(character_confidence, 0.15))
                if candidate.frame_time_ms is not None:
                    support_frames.append(candidate.frame_time_ms)
                contribution_count += 1
                if representative is None or candidate.confidence > representative.confidence:
                    representative = candidate

        if representative is None or contribution_count < 2 or len(set(support_frames)) < 2:
            return None
        if any(not votes for votes in position_votes):
            return None

        fused_text = ''.join(max(votes.items(), key=lambda item: item[1])[0] for votes in position_votes)
        if not _looks_like_taiwan_long_plate(fused_text):
            return None
        character_consistency = [
            max(votes.values()) / max(sum(votes.values()), 1.0)
            for votes in position_votes
        ]
        confidence = sum(character_consistency) / len(character_consistency)
        return PlateCandidate(
            id='fused-char-tw-long-0',
            text=fused_text,
            confidence=confidence,
            source='fused-char-tw-long',
            frame_time_ms=representative.frame_time_ms,
            country_code=representative.country_code,
            box=representative.box,
            quality=representative.quality,
            diagnostics={
                'supportFrames': sorted(set(support_frames)),
                'targetLength': 7,
                'characterConsistency': character_consistency,
                'characterConsistencyMean': confidence,
                'contributionCount': contribution_count,
            },
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

        observations_to_fuse = sorted(
            observations,
            key=lambda observation: (
                observation.quality.overall_score if observation.quality else 0.0,
                float((observation.diagnostics or {}).get('selectionScore') or 0.0),
                -abs(observation.time_ms),
            ),
            reverse=True,
        )[:MAX_INTERVAL_FUSION_OBSERVATIONS]

        cv2 = self._dependencies.cv2
        reference = max(observations_to_fuse, key=lambda observation: observation.quality.overall_score if observation.quality else 0.0)
        reference_image = reference.working_image
        if reference_image is None or getattr(reference_image, 'size', 0) == 0:
            return [], {'applied': False, 'reason': 'empty-reference'}

        reference_height, reference_width = reference_image.shape[:2]
        accum = reference_image.astype('float32')
        total_weight = 1.0
        support = 1
        alignment_scores: list[float] = [1.0]
        support_times: list[int] = [reference.time_ms]

        for observation in observations_to_fuse:
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
            support_times.append(observation.time_ms)

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
                'supportFrames': sorted(set(support_times)),
                'supportFrameCount': support,
                'meanAlignmentScore': sum(alignment_scores) / len(alignment_scores),
            }

        return fused_candidates, {
            'applied': True,
            'supportFrames': support,
            'meanAlignmentScore': sum(alignment_scores) / len(alignment_scores),
            'requestedObservationCount': len(observations),
            'fusedObservationCount': len(observations_to_fuse),
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
