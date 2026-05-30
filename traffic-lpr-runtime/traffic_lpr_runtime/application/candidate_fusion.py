from __future__ import annotations

from pathlib import Path
from typing import Any

from traffic_lpr_runtime.application.pipeline_support import AnalysisOptions
from traffic_lpr_runtime.application.preprocessing import PlateObservation
from traffic_lpr_runtime.domain.interfaces import PlateRecognizer
from traffic_lpr_runtime.domain.models import FrameSample, PlateCandidate
from traffic_lpr_runtime.domain.text import normalize_plate_text
from traffic_lpr_runtime.infrastructure.dependencies import DependencyRegistry


MAX_INTERVAL_FUSION_OBSERVATIONS = 6


def _ordered_top_sample_candidates(samples: list[FrameSample]) -> list[tuple[int, PlateCandidate | None, str]]:
    ordered: list[tuple[int, PlateCandidate | None, str]] = []
    for sample in sorted(samples, key=lambda item: item.time_ms):
        candidate = sample.candidates[0] if sample.candidates else None
        text = normalize_plate_text(candidate.text) if candidate is not None else ''
        ordered.append((sample.time_ms, candidate, text))
    return ordered


def _support_gap_count(support_frames: list[int], ordered_sample_times: list[int]) -> int:
    if not support_frames or not ordered_sample_times:
        return 0
    sample_index_by_time = {time_ms: index for index, time_ms in enumerate(ordered_sample_times)}
    sorted_indexes = sorted(
        sample_index_by_time[time_ms]
        for time_ms in support_frames
        if time_ms in sample_index_by_time
    )
    gap_count = 0
    for previous, current in zip(sorted_indexes, sorted_indexes[1:]):
        if current - previous > 1:
            gap_count += 1
    return gap_count


def _candidate_support_frames_payload(candidate: PlateCandidate) -> set[int]:
    diagnostics = candidate.diagnostics or {}
    support_frames = diagnostics.get('supportFrames')
    frames: set[int] = set()
    if isinstance(support_frames, list):
        frames.update(int(frame) for frame in support_frames if isinstance(frame, (int, float)))
    elif isinstance(support_frames, (int, float)):
        frames.add(int(support_frames))
    if candidate.frame_time_ms is not None:
        frames.add(int(candidate.frame_time_ms))
    return frames


def _sequence_tier(
    persistence_ratio: float,
    gap_count: int,
    prediction_switch_count: int,
    support_frame_count: int,
    character_consistency_mean: float,
) -> str:
    if support_frame_count <= 1 or persistence_ratio < 0.4:
        return 'fragmented'
    if gap_count > 1:
        return 'gapped'
    if prediction_switch_count > 0 or persistence_ratio < 0.72 or character_consistency_mean < 0.68:
        return 'drifting'
    return 'stable'


def _candidate_weight(candidate: PlateCandidate, source_weights: dict[str, float]) -> float:
    source_key = candidate.source.split(':', 1)[0]
    quality_weight = candidate.quality.overall_score if candidate.quality else 0.55
    diagnostics = candidate.diagnostics or {}
    taiwan_prior = float(diagnostics.get('taiwanPrior') or 1.0)
    weight = candidate.confidence * quality_weight * source_weights.get(source_key, 1.0) * taiwan_prior

    if source_key == 'fused-char':
        character_consistency_mean = float(diagnostics.get('characterConsistencyMean') or candidate.confidence or 0.0)
        char_fusion_reliability = max(0.25, min(1.0, character_consistency_mean))
        if diagnostics.get('matchesDominantSequence') is not True:
            char_fusion_reliability *= 0.6
        weight *= char_fusion_reliability

    return weight


def _best_frame_candidate(samples: list[FrameSample], source_weights: dict[str, float]) -> tuple[PlateCandidate | None, float]:
    best_candidate: PlateCandidate | None = None
    best_weight = 0.0
    for sample in samples:
        for rank, candidate in enumerate(sample.candidates):
            text = normalize_plate_text(candidate.text)
            if not text:
                continue
            rank_penalty = max(0.7, 1.0 - (rank * 0.12))
            weighted_score = _candidate_weight(candidate, source_weights) * rank_penalty
            if weighted_score > best_weight:
                best_candidate = candidate
                best_weight = weighted_score
    return best_candidate, best_weight


def _source_family(source: str) -> str:
    return source.split(':', 1)[0]


def _consensus_signal_names(
    text: str,
    dominant_text: str,
    char_fused_text: str,
    best_frame_text: str,
) -> list[str]:
    signals: list[str] = []
    if text and text == dominant_text:
        signals.append('dominant-sequence')
    if text and text == char_fused_text:
        signals.append('char-fused')
    if text and text == best_frame_text:
        signals.append('best-frame')
    return signals


def _consensus_weight_multiplier(
    consensus_signals: list[str],
    support_frame_count: int,
    source_count: int,
) -> float:
    if len(consensus_signals) < 2:
        return 1.0
    if support_frame_count < 2:
        return 1.0

    multiplier = 1.06 + (max(0, len(consensus_signals) - 2) * 0.04)
    if support_frame_count >= 2:
        multiplier += min(0.03, (support_frame_count - 1) * 0.008)
    if source_count >= 2:
        multiplier += min(0.03, (source_count - 1) * 0.008)
    return multiplier


def _looks_like_taiwan_long_plate(text: str) -> bool:
    normalized = normalize_plate_text(text)
    return len(normalized) == 7 and normalized[:3].isalpha() and normalized[-4:].isdigit()


def _looks_like_taiwan_short_plate(text: str) -> bool:
    normalized = normalize_plate_text(text)
    return len(normalized) == 6 and normalized[:2].isalpha() and normalized[-4:].isdigit()


def _sequence_confidence_cap(candidate: PlateCandidate, sequence_summary: dict[str, Any], options: AnalysisOptions) -> float:
    diagnostics = candidate.diagnostics or {}
    sequence_tier = str(diagnostics.get('sequenceTier') or sequence_summary.get('sequenceTier') or 'fragmented')
    support_ratio = float(diagnostics.get('sequenceSupportRatio') or 0.0)
    support_frame_count = int(diagnostics.get('supportFrameCount') or 0)
    character_consistency_mean = float(sequence_summary.get('characterConsistencyMean') or 0.0)
    dominant_text = normalize_plate_text(sequence_summary.get('dominantText'))
    candidate_text = normalize_plate_text(candidate.text)

    if sequence_tier == 'stable':
        return 1.0
    if sequence_tier == 'drifting':
        return min(0.86, max(options.min_accepted_confidence - 0.02, 0.62 + (support_ratio * 0.20)))
    if sequence_tier == 'gapped':
        return min(0.78, max(0.52, 0.56 + (support_ratio * 0.18)))

    fragmented_cap = min(0.66, max(0.42, 0.45 + (support_ratio * 0.18) + (character_consistency_mean * 0.10)))
    if support_frame_count <= 1:
        fragmented_cap = min(fragmented_cap, 0.54)
    if candidate_text and candidate_text != dominant_text:
        fragmented_cap = min(fragmented_cap, 0.58)
    return fragmented_cap


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
    runner_up_candidate = ordered_candidates[1] if len(ordered_candidates) > 1 else None
    fallback_candidate = _best_sample_candidate(samples, country_hints)
    accepted_margin = max(0.0, top_candidate.confidence - (runner_up_candidate.confidence if runner_up_candidate is not None else 0.0))

    review_reasons = [] if not options.enable_reliability_gates else _review_reasons(
        top_candidate,
        accepted_margin,
        country_hints,
        options,
        interval_mode,
    )
    suggested_candidate = top_candidate
    used_fallback = False
    if interval_mode and review_reasons and _plate_format_score(top_candidate.text, country_hints) < 0.65:
        interval_candidate = _best_interval_review_candidate(ordered_candidates, country_hints, options)
        if interval_candidate is not None and interval_candidate.id != suggested_candidate.id:
            suggested_candidate = interval_candidate
            review_reasons = [] if not options.enable_reliability_gates else _review_reasons(
                suggested_candidate,
                max(0.0, suggested_candidate.confidence - (runner_up_candidate.confidence if runner_up_candidate is not None else 0.0)),
                country_hints,
                options,
                interval_mode,
            )
    if review_reasons and fallback_candidate is not None and fallback_candidate.id != top_candidate.id:
        top_score = _candidate_reliability_score(top_candidate, country_hints)
        fallback_score = _candidate_reliability_score(fallback_candidate, country_hints)
        fallback_format_score = _plate_format_score(fallback_candidate.text, country_hints)
        format_advantage = fallback_format_score - _plate_format_score(top_candidate.text, country_hints)
        top_support_count = _candidate_support_frame_count(top_candidate)
        fallback_support_count = _candidate_support_frame_count(fallback_candidate)
        required_score_advantage = 0.05
        fallback_text = normalize_plate_text(fallback_candidate.text)
        suggested_text = normalize_plate_text(suggested_candidate.text)
        fallback_allowed = True
        if interval_mode and (fallback_format_score < 0.65 or fallback_text == suggested_text):
            fallback_allowed = False
        if interval_mode and fallback_support_count < top_support_count and format_advantage < 0.2:
            required_score_advantage = 0.18
        if fallback_allowed and (fallback_score >= top_score + required_score_advantage or format_advantage >= 0.2):
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
        'topCandidateText': top_candidate.text,
        'runnerUpCandidateId': runner_up_candidate.id if runner_up_candidate is not None else None,
        'runnerUpText': runner_up_candidate.text if runner_up_candidate is not None else None,
        'runnerUpConfidence': runner_up_candidate.confidence if runner_up_candidate is not None else None,
        'reviewRequired': review_required,
        'usedFallback': used_fallback,
        'reasons': review_reasons,
        'acceptedMargin': accepted_margin,
        'suggestedConfidence': suggested_candidate.confidence,
        'suggestedText': suggested_candidate.text,
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
    diagnostics = candidate.diagnostics or {}
    sequence_tier = str(diagnostics.get('sequenceTier') or '')
    sequence_support_ratio = float(diagnostics.get('sequenceSupportRatio') or 0.0)
    sequence_consistency = float(diagnostics.get('sequenceCharacterConsistencyMean') or 0.0)
    if interval_mode and sequence_tier in {'fragmented', 'gapped'}:
        reasons.append('unstable-sequence')
    if interval_mode and sequence_support_ratio < max(0.34, options.min_sequence_persistence * 0.5):
        reasons.append('weak-sequence-support')
    if interval_mode and sequence_consistency < 0.55:
        reasons.append('weak-character-consensus')
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


def _best_interval_review_candidate(
    candidates: list[PlateCandidate],
    country_hints: list[str],
    options: AnalysisOptions,
) -> PlateCandidate | None:
    plate_like_candidates = [
        candidate
        for candidate in candidates
        if _plate_format_score(candidate.text, country_hints) >= 0.65
    ]
    if not plate_like_candidates:
        return None

    return max(
        plate_like_candidates,
        key=lambda candidate: (
            _candidate_support_frame_count(candidate) >= options.min_interval_support_frames,
            _plate_format_score(candidate.text, country_hints),
            _candidate_support_frame_count(candidate),
            candidate.confidence,
            len(normalize_plate_text(candidate.text)),
        ),
    )


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
        if normalized[:3].isalpha() and normalized[-4:].isdigit() and len(normalized) == 7:
            return 1.0
        if normalized[:2].isalpha() and normalized[-4:].isdigit() and len(normalized) == 6:
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
