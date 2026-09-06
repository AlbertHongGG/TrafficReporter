from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from traffic_lpr_runtime.application.analysis_policy import AnalysisPolicyResolver
from traffic_lpr_runtime.application.diagnostics import IntervalAnalysisDiagnostics, RuntimeStageTiming
from traffic_lpr_runtime.application.pipeline_support import AnalysisOptions
from traffic_lpr_runtime.application.preprocessing import PlateObservation
from traffic_lpr_runtime.application.provenance import build_analysis_provenance
from traffic_lpr_runtime.application.review_state import build_review_state
from traffic_lpr_runtime.domain.errors import RuntimeFailure
from traffic_lpr_runtime.domain.models import FrameSample, PlateCandidate, TargetTrack, TrackedRegion
from traffic_lpr_runtime.domain.value_objects import NormalizedRect


@dataclass(frozen=True, slots=True)
class IntervalAnalysisDependencies:
    ensure_ready: Callable[[], None]
    status: Callable[[], dict[str, Any]]
    runtime_root: Callable[[], Path]
    frame_reader: Any
    track_target_across_interval: Callable[..., tuple[list[TrackedRegion], dict[str, Any]]]
    calibrate_interval_target_boxes: Callable[[list[TrackedRegion], int, NormalizedRect | None], dict[int, NormalizedRect]]
    analyze_plate_candidates: Callable[..., tuple[list[PlateCandidate], FrameSample, PlateObservation | None]]
    aggregate_candidates: Callable[[list[FrameSample], list[PlateObservation], list[str], AnalysisOptions, Path | None], tuple[list[PlateCandidate], dict[str, Any]]]
    apply_reliability_selection: Callable[[list[PlateCandidate], list[FrameSample], list[str], AnalysisOptions, bool], tuple[list[PlateCandidate], str | None, dict[str, Any]]]
    build_track_payload: Callable[[list[TrackedRegion], dict[str, Any]], list[TargetTrack]]


class IntervalAnalysisService:
    def __init__(self, dependencies: IntervalAnalysisDependencies, policy_resolver: AnalysisPolicyResolver | None = None) -> None:
        self._dependencies = dependencies
        self._policy_resolver = policy_resolver or AnalysisPolicyResolver()

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        from traffic_lpr_runtime.protocol import emit_runtime_progress
        from traffic_lpr_runtime.application.services.tracking.calibration import (
            _anchor_status,
            _build_tracking_summary,
            _resolve_analysis_target_box,
            _resolve_interval_anchor_box,
            _selected_target_track_id,
            _tracking_advisory_reasons,
            _tracking_identity_review_reasons,
        )
        from traffic_lpr_runtime.application.services.tracking.evidence_frames import (
            _resolve_temporal_support_budget,
            _resolve_temporal_support_reason,
            _select_interval_evidence_frames,
            _select_temporal_support_frames,
        )
        from traffic_lpr_runtime.application.services.fusion.review_decision import (
            _build_decision_trace,
            _build_sample_selection_payload,
            _merge_reasons,
            _request_run_id,
            _safe_int,
            _sequence_advisory_reasons,
            _sequence_hard_review_reasons,
        )

        def _emit_progress(progress: float, stage: str, detail: str, **kwargs: Any) -> None:
            emit_runtime_progress({
                'progress': progress,
                'stage': stage,
                'detail': detail,
                'done': False,
                'failed': False,
                **kwargs,
            })

        self._dependencies.ensure_ready()
        run_started = perf_counter()
        options = AnalysisOptions.from_payload(payload)
        analysis_policy = self._policy_resolver.resolve_interval(payload, options)
        payload = analysis_policy.apply_to_payload(payload)
        artifact_root = options.resolve_artifact_root(
            self._dependencies.runtime_root(),
            'interval',
            _request_run_id(payload),
        )
        interval = payload['interval']
        anchor_time_ms = int(payload['anchorTimeMs'])
        start_ms = int(interval['startMs'])
        end_ms = int(interval['endMs'])
        selected_target_box = NormalizedRect.from_payload(payload.get('selectedTargetBox'))
        if selected_target_box is None:
            raise RuntimeFailure('Range analysis requires a selected target on the anchor frame.')
        if anchor_time_ms < start_ms or anchor_time_ms > end_ms:
            raise RuntimeFailure('Range analysis requires the selected target anchor to stay inside the requested interval.')
        requested_frame_count = max(1, analysis_policy.max_samples)

        _emit_progress(0.1, 'Interval', 'Validating the anchor frame and starting interval tracking.')
        tracking_started = perf_counter()
        tracked_frames, track_diagnostics = self._dependencies.track_target_across_interval(
            payload['sourcePath'],
            interval,
            anchor_time_ms,
            payload.get('targetVehicleKind', 'vehicle'),
            selected_target_box,
            analysis_policy.sample_every_ms,
            analysis_policy.max_samples,
            options,
            isinstance(payload.get('groundTruthFrames'), list) and len(payload.get('groundTruthFrames') or []) > 0,
        )
        requested_tracking_frame_count = max(
            requested_frame_count,
            _safe_int(track_diagnostics.get('requestedTrackingFrameCount'), len(tracked_frames)),
            1,
        )
        canonical_target_track_id = _selected_target_track_id(payload, track_diagnostics)
        if canonical_target_track_id is not None:
            track_diagnostics = {
                **track_diagnostics,
                'canonicalTargetId': canonical_target_track_id,
            }
        calibrated_target_boxes = self._dependencies.calibrate_interval_target_boxes(
            tracked_frames,
            anchor_time_ms,
            selected_target_box,
        )
        resolved_anchor_box = _resolve_interval_anchor_box(
            tracked_frames,
            calibrated_target_boxes,
            anchor_time_ms,
            selected_target_box,
        )
        anchor_status = _anchor_status(selected_target_box, anchor_time_ms, start_ms, end_ms, resolved_anchor_box)
        anchor_ok = anchor_status == 'valid'
        tracking = _build_tracking_summary(
            track_diagnostics,
            len(tracked_frames),
            requested_tracking_frame_count,
            anchor_ok,
            anchor_status,
        )
        tracking_ms = (perf_counter() - tracking_started) * 1000.0
        _emit_progress(
            0.32,
            'Interval',
            'Interval tracking finished. Preparing sample analysis.',
            trackingTier=tracking['trackingTier'],
            coverageRatio=tracking['coverageRatio'],
        )
        if not anchor_ok and len(tracked_frames) == 0:
            raise RuntimeFailure('Range analysis lost the selected target at the anchor frame. Reselect the vehicle on the intended frame and retry.')

        sample_options = options.for_interval_sample(sample_count_hint=len(tracked_frames))
        evidence_frames = _select_interval_evidence_frames(tracked_frames, options)

        samples: list[FrameSample] = []
        observations: list[PlateObservation] = []
        observation_cache: dict[int, PlateObservation | None] = {}
        sample_count = len(evidence_frames)
        temporal_support_budget = _resolve_temporal_support_budget(len(tracked_frames), sample_count, sample_options)
        temporal_support_samples_used = 0
        sample_analysis_ms = 0.0
        temporal_support_ms = 0.0
        for index, tracked_frame in enumerate(evidence_frames, start=1):
            raw_tracking_box = tracked_frame.box
            calibrated_target_box = calibrated_target_boxes.get(tracked_frame.time_ms)
            analysis_target_box, analysis_box_source = _resolve_analysis_target_box(
                raw_tracking_box,
                calibrated_target_box,
                selected_target_box,
                tracked_frame.time_ms,
                anchor_time_ms,
            )
            sample_progress = 0.35 if sample_count == 0 else 0.35 + (0.35 * (index - 1) / sample_count)
            _emit_progress(
                sample_progress,
                'Interval',
                f'Analyzing tracked sample {index}/{sample_count}.',
                trackingTier=tracking['trackingTier'],
                coverageRatio=tracking['coverageRatio'],
            )
            sample_started = perf_counter()
            frame = self._dependencies.frame_reader.read_frame(payload['sourcePath'], tracked_frame.time_ms)
            _, sample, base_observation = self._dependencies.analyze_plate_candidates(
                frame,
                tracked_frame.time_ms,
                None,
                analysis_target_box,
                payload.get('countryHints') or [],
                sample_options,
                artifact_root / f'sample-{tracked_frame.time_ms}' if artifact_root else None,
            )
            sample_analysis_ms += (perf_counter() - sample_started) * 1000.0
            observation_cache[tracked_frame.time_ms] = base_observation

            temporal_support_reason = _resolve_temporal_support_reason(sample, tracked_frame, sample_options)
            temporal_support_skipped_reason: str | None = None
            temporal_support_applied = False
            final_observation = base_observation
            support_observations: list[PlateObservation] = []

            if temporal_support_reason is not None:
                if temporal_support_samples_used >= temporal_support_budget:
                    temporal_support_skipped_reason = 'budget-exhausted'
                else:
                    support_started = perf_counter()
                    for support_frame in _select_temporal_support_frames(tracked_frames, tracked_frame.time_ms, sample_options):
                        if support_frame.time_ms in observation_cache:
                            cached_support = observation_cache[support_frame.time_ms]
                            if cached_support is not None:
                                support_observations.append(cached_support)
                            continue
                        support_calibrated_box = calibrated_target_boxes.get(support_frame.time_ms)
                        support_target_box, _ = _resolve_analysis_target_box(
                            support_frame.box,
                            support_calibrated_box,
                            selected_target_box,
                            support_frame.time_ms,
                            anchor_time_ms,
                        )
                        support_frame_image = self._dependencies.frame_reader.read_frame(payload['sourcePath'], support_frame.time_ms)
                        _, _, cached_support = self._dependencies.analyze_plate_candidates(
                            support_frame_image,
                            support_frame.time_ms,
                            None,
                            support_target_box,
                            payload.get('countryHints') or [],
                            sample_options,
                            None,
                        )
                        observation_cache[support_frame.time_ms] = cached_support
                        if cached_support is not None:
                            support_observations.append(cached_support)

                    if support_observations:
                        _, sample, supported_observation = self._dependencies.analyze_plate_candidates(
                            frame,
                            tracked_frame.time_ms,
                            None,
                            analysis_target_box,
                            payload.get('countryHints') or [],
                            sample_options,
                            artifact_root / f'sample-{tracked_frame.time_ms}' if artifact_root else None,
                            support_observations,
                        )
                        final_observation = supported_observation or base_observation
                        temporal_support_samples_used += 1
                        temporal_support_applied = True
                    else:
                        temporal_support_skipped_reason = 'no-support-observations'

                    temporal_support_ms += (perf_counter() - support_started) * 1000.0

            if calibrated_target_box is not None:
                tracked_frame.diagnostics = {
                    **(tracked_frame.diagnostics or {}),
                    'analysisBox': analysis_target_box.to_payload() if analysis_target_box else None,
                    'analysisBoxSource': analysis_box_source,
                    'rawTrackingBox': raw_tracking_box.to_payload() if raw_tracking_box else None,
                    'calibratedBox': calibrated_target_box.to_payload(),
                }
                if analysis_box_source == 'calibrated':
                    tracked_frame.box = calibrated_target_box
            sample.selection = _build_sample_selection_payload(sample, tracked_frame)
            sample.diagnostics = {
                **(sample.diagnostics or {}),
                'analysisTargetBox': analysis_target_box.to_payload() if analysis_target_box else None,
                'analysisBoxSource': analysis_box_source,
                'rawTrackingBox': raw_tracking_box.to_payload() if raw_tracking_box else None,
                'tracking': tracked_frame.diagnostics,
                'temporalSupportDecision': {
                    'budget': temporal_support_budget,
                    'used': temporal_support_samples_used,
                    'requested': temporal_support_reason is not None,
                    'applied': temporal_support_applied,
                    'reason': temporal_support_reason,
                    'skippedReason': temporal_support_skipped_reason,
                    'supportFrameCount': len(support_observations),
                },
            }
            samples.append(sample)
            if final_observation is not None:
                observations.append(final_observation)

        fusion_started = perf_counter()
        candidates, fusion_diagnostics = self._dependencies.aggregate_candidates(
            samples,
            observations,
            payload.get('countryHints') or [],
            options,
            artifact_root,
        )
        sequence_summary = dict(fusion_diagnostics.get('sequence') or {})
        _emit_progress(0.78, 'Interval', 'Fusing candidates across interval samples.', trackingTier=tracking['trackingTier'], coverageRatio=tracking['coverageRatio'])
        candidates, accepted_candidate_id, selection_diagnostics = self._dependencies.apply_reliability_selection(
            candidates,
            samples,
            payload.get('countryHints') or [],
            options,
            True,
        )
        fusion_ms = (perf_counter() - fusion_started) * 1000.0
        identity_review_reasons = _tracking_identity_review_reasons(track_diagnostics)
        sequence_hard_review_reasons = _sequence_hard_review_reasons(sequence_summary, options)
        sequence_advisory_reasons = _sequence_advisory_reasons(sequence_summary, options)
        tracking_advisory_reasons = _tracking_advisory_reasons(track_diagnostics, tracking)
        selection_review_reasons = [reason for reason in selection_diagnostics.get('reasons') or [] if isinstance(reason, str)]
        hard_review_reasons = _merge_reasons(
            selection_review_reasons,
            [*identity_review_reasons, *sequence_hard_review_reasons],
        )
        if tracking['trackingTier'] == 'anchor-invalid':
            hard_review_reasons = _merge_reasons(
                hard_review_reasons,
                [str(tracking.get('degradedReason') or 'anchor validation drifted away from the selected target')],
            )
        advisory_reasons = _merge_reasons(
            sequence_advisory_reasons,
            tracking_advisory_reasons,
        )
        selection_diagnostics = {
            **selection_diagnostics,
            'acceptedCandidateId': accepted_candidate_id,
            'reviewRequired': bool(hard_review_reasons),
            'hardReviewReasons': hard_review_reasons,
            'advisoryReasons': advisory_reasons,
            'reasons': _merge_reasons(hard_review_reasons, advisory_reasons),
            'tracking': track_diagnostics,
            'sequence': sequence_summary,
        }
        if candidates:
            suggested_candidate = next(
                (candidate for candidate in candidates if candidate.id == selection_diagnostics.get('suggestedCandidateId')),
                candidates[0],
            )
            summary = (
                f'{len(samples)} samples, {len(candidates)} fused candidate(s), '
                f'best={suggested_candidate.text}, tracker={track_diagnostics.get("trackerMode", "legacy")}'
            )
            if selection_diagnostics.get('reviewRequired'):
                summary = f'{summary}, review needed.'
        else:
            summary = f'{len(samples)} samples, no confident plate candidate.'
        if tracking['trackingTier'] != 'full':
            coverage_percent = round(float(tracking['coverageRatio']) * 100)
            summary = f'{summary} Coverage {coverage_percent}% ({tracking["trackingTier"]}).'
        if sequence_summary.get('sequenceTier') and sequence_summary['sequenceTier'] != 'stable':
            summary = f'{summary} Sequence {sequence_summary["sequenceTier"]}.'

        _emit_progress(0.92, 'Interval', 'Finalizing the interval analysis result.', trackingTier=tracking['trackingTier'], coverageRatio=tracking['coverageRatio'])
        runtime_status = self._dependencies.status()
        job_status = 'degraded' if tracking['trackingTier'] != 'full' else 'completed'
        analysis_tracks = self._dependencies.build_track_payload(tracked_frames, track_diagnostics)
        analysis_track = analysis_tracks[0].to_payload() if analysis_tracks else None
        decision = _build_decision_trace(candidates, accepted_candidate_id, selection_diagnostics, samples, sequence_summary)
        total_ms = (perf_counter() - run_started) * 1000.0
        diagnostics = IntervalAnalysisDiagnostics(
            analysis_options=options.to_payload(),
            analysis_policy=analysis_policy,
            artifact_root=str(artifact_root) if artifact_root else None,
            tracker=track_diagnostics,
            tracking_summary=tracking,
            sequence=sequence_summary,
            fusion=fusion_diagnostics,
            selection=selection_diagnostics,
            timing=RuntimeStageTiming(
                tracking_ms=tracking_ms,
                sample_analysis_ms=sample_analysis_ms,
                temporal_support_ms=temporal_support_ms,
                fusion_ms=fusion_ms,
                total_ms=total_ms,
                temporal_support_budget=temporal_support_budget,
                temporal_support_samples_used=temporal_support_samples_used,
            ),
        )
        return {
            'targetTracks': [track.to_payload() for track in analysis_tracks],
            'analysisTrack': analysis_track,
            'samples': [sample.to_payload() for sample in samples],
            'candidates': [candidate.to_payload() for candidate in candidates],
            'acceptedCandidateId': accepted_candidate_id,
            'review': build_review_state(candidates, accepted_candidate_id, selection_diagnostics),
            'sequence': sequence_summary,
            'provenance': build_analysis_provenance('analyze-interval', payload, runtime_status, options.to_payload()),
            'decision': decision,
            'summary': summary,
            'runtime': runtime_status,
            'jobStatus': job_status,
            'tracking': tracking,
            'diagnostics': diagnostics.to_payload(),
        }