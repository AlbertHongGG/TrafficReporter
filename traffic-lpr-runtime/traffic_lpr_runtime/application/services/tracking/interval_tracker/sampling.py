from __future__ import annotations

from traffic_lpr_runtime.application.services.analysis.sampling_strategy import (
    SHORT_INTERVAL_MAX_MS,
    SHORT_INTERVAL_MIN_SAMPLE_BUDGET,
    SHORT_INTERVAL_SAMPLE_STEP_MS,
)


def _resolve_evidence_sample_budget(
    sample_times: list[int],
    duration_ms: int,
    preserve_dense_schedule: bool,
    max_evidence_sample_count: int,
) -> int:
    adaptive_cap = max_evidence_sample_count
    if duration_ms >= 12000:
        adaptive_cap = min(adaptive_cap, 10)
    if duration_ms >= 20000:
        adaptive_cap = min(adaptive_cap, 8)

    if preserve_dense_schedule or len(sample_times) <= adaptive_cap:
        return len(sample_times)
    if duration_ms <= 4000:
        return min(len(sample_times), max(adaptive_cap, 8))
    return min(len(sample_times), adaptive_cap)


def _resolve_anchor_burst_count(
    duration_ms: int,
    evidence_budget: int,
    anchor_burst_count: int,
) -> int:
    resolved = max(1, anchor_burst_count)
    if duration_ms >= 12000 or evidence_budget <= 10:
        resolved = min(resolved, 3)
    if duration_ms >= 20000 or evidence_budget <= 8:
        resolved = min(resolved, 2)
    return max(1, resolved)


def _sparsify_evidence_sample_times(
    interval: dict[str, int],
    anchor_time_ms: int,
    sample_step_ms: int,
    budget: int,
    anchor_burst_count: int,
) -> list[int]:
    start_ms = int(interval['startMs'])
    end_ms = int(interval['endMs'])
    if budget <= 0:
        return []

    chosen: list[int] = []

    def choose(time_ms: int | None) -> None:
        if time_ms is None or time_ms in chosen or time_ms < start_ms or time_ms > end_ms:
            return
        chosen.append(time_ms)

    choose(anchor_time_ms)
    choose(start_ms)
    choose(end_ms)

    burst_step_ms = max(45, min(sample_step_ms, 90))
    for burst_index in range(1, max(1, anchor_burst_count) + 1):
        choose(anchor_time_ms - (burst_step_ms * burst_index))
        if len(chosen) >= budget:
            break
        choose(anchor_time_ms + (burst_step_ms * burst_index))
        if len(chosen) >= budget:
            break

    offset_ms = sample_step_ms
    while len(chosen) < budget and (anchor_time_ms - offset_ms >= start_ms or anchor_time_ms + offset_ms <= end_ms):
        choose(anchor_time_ms - offset_ms)
        if len(chosen) >= budget:
            break
        choose(anchor_time_ms + offset_ms)
        offset_ms += sample_step_ms

    return sorted(chosen)


class IntervalSamplingMixin:
    def resolve_sample_step_ms(
        self,
        interval: dict[str, int],
        requested_every_ms: int | None,
        requested_max_samples: int | None,
    ) -> int:
        start_ms = int(interval['startMs'])
        end_ms = int(interval['endMs'])
        duration_ms = max(0, end_ms - start_ms)
        max_samples = max(4, min(int(requested_max_samples or 18), 48))

        if duration_ms == 0:
            return max(120, int(requested_every_ms or 120))

        if duration_ms <= SHORT_INTERVAL_MAX_MS:
            return SHORT_INTERVAL_SAMPLE_STEP_MS

        return requested_every_ms or max(120, int(duration_ms / max_samples))

    def resolve_tracking_step_ms(
        self,
        interval: dict[str, int],
        evidence_step_ms: int,
    ) -> int:
        start_ms = int(interval['startMs'])
        end_ms = int(interval['endMs'])
        duration_ms = max(0, end_ms - start_ms)

        if duration_ms == 0:
            return max(50, min(evidence_step_ms, 100))

        base_step_ms = max(1, int(round(evidence_step_ms / 2)))
        rounded_step_ms = int(round(base_step_ms / 10.0) * 10) if base_step_ms >= 10 else base_step_ms
        if duration_ms >= 20000:
            min_step_ms, max_step_ms = 200, 320
        elif duration_ms >= 12000:
            min_step_ms, max_step_ms = 100, 180
        elif duration_ms >= 6000:
            min_step_ms, max_step_ms = 80, 140
        else:
            min_step_ms, max_step_ms = 50, 100
        return max(min_step_ms, min(max_step_ms, rounded_step_ms))

    def trajectory_times(
        self,
        interval: dict[str, int],
        trajectory_step_ms: int,
    ) -> list[int]:
        start_ms = int(interval['startMs'])
        end_ms = int(interval['endMs'])
        if start_ms >= end_ms:
            return [start_ms]

        times = list(range(start_ms, end_ms + 1, max(1, trajectory_step_ms)))
        if times[-1] != end_ms:
            times.append(end_ms)
        return times

    def sample_times(
        self,
        interval: dict[str, int],
        requested_every_ms: int | None,
        requested_max_samples: int | None,
    ) -> list[int]:
        start_ms = int(interval['startMs'])
        end_ms = int(interval['endMs'])
        duration_ms = max(0, end_ms - start_ms)
        max_samples = max(4, min(int(requested_max_samples or 18), 48))

        if duration_ms <= SHORT_INTERVAL_MAX_MS:
            max_samples = max(max_samples, SHORT_INTERVAL_MIN_SAMPLE_BUDGET)

        if duration_ms == 0:
            return [start_ms]

        sample_every_ms = self.resolve_sample_step_ms(interval, requested_every_ms, requested_max_samples)
        times = list(range(start_ms, end_ms + 1, sample_every_ms))
        if times[-1] != end_ms:
            times.append(end_ms)
        return times[:max_samples]
