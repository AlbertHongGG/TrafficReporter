from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from traffic_lpr_runtime.application.pipeline_support import AnalysisOptions


SHORT_INTERVAL_MAX_MS = 3500
SHORT_INTERVAL_SAMPLE_STEP_MS = 150
SHORT_INTERVAL_MIN_SAMPLE_BUDGET = 16
DEFAULT_INTERACTIVE_LATENCY_BUDGET_MS = 30_000
DEFAULT_AI_EVIDENCE_LATENCY_BUDGET_MS = 45_000


KNOWN_INTERVAL_INTENTS = {
    'interactive-short-range',
    'interactive-range',
    'interactive-dense-range',
    'ai-evidence-range',
}


@dataclass(frozen=True, slots=True)
class ResolvedIntervalAnalysisPolicy:
    intent: str
    duration_ms: int
    short_interval: bool
    requested_sample_every_ms: int | None
    requested_max_samples: int | None
    sample_every_ms: int
    max_samples: int
    latency_budget_ms: int
    analysis_profile_id: str | None
    rules: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            'intent': self.intent,
            'durationMs': self.duration_ms,
            'shortInterval': self.short_interval,
            'requestedSampleEveryMs': self.requested_sample_every_ms,
            'requestedMaxSamples': self.requested_max_samples,
            'sampleEveryMs': self.sample_every_ms,
            'maxSamples': self.max_samples,
            'latencyBudgetMs': self.latency_budget_ms,
            'analysisProfileId': self.analysis_profile_id,
            'rules': list(self.rules),
        }

    def apply_to_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            **payload,
            'analysisIntent': self.intent,
            'sampleEveryMs': self.sample_every_ms,
            'maxSamples': self.max_samples,
            'latencyBudgetMs': self.latency_budget_ms,
        }


class AnalysisPolicyResolver:
    def resolve_interval(self, payload: dict[str, Any], options: AnalysisOptions) -> ResolvedIntervalAnalysisPolicy:
        interval = payload.get('interval') or {}
        start_ms = _safe_int(interval.get('startMs'), 0)
        end_ms = _safe_int(interval.get('endMs'), start_ms)
        duration_ms = max(0, end_ms - start_ms)
        requested_sample_every_ms = _optional_positive_int(payload.get('sampleEveryMs'))
        requested_max_samples = _optional_positive_int(payload.get('maxSamples'))
        intent = _resolve_intent(payload, duration_ms)
        rules: list[str] = []

        if duration_ms <= SHORT_INTERVAL_MAX_MS:
            sample_every_ms = SHORT_INTERVAL_SAMPLE_STEP_MS
            max_samples = max(requested_max_samples or 0, SHORT_INTERVAL_MIN_SAMPLE_BUDGET)
            rules.append('short-interval-stable-grid')
            if (
                (requested_sample_every_ms is not None and requested_sample_every_ms != sample_every_ms)
                or (requested_max_samples is not None and requested_max_samples < SHORT_INTERVAL_MIN_SAMPLE_BUDGET)
            ):
                rules.append('caller-sampling-normalized')
            intent = 'interactive-short-range' if intent == 'interactive-range' else intent
        elif intent == 'interactive-dense-range':
            max_samples = max(requested_max_samples or 0, 24)
            sample_every_ms = requested_sample_every_ms or max(70, round(duration_ms / 28) or 70)
            rules.append('interactive-dense-range-grid')
        elif intent == 'ai-evidence-range':
            max_samples = max(requested_max_samples or 0, min(24, max(12, round(duration_ms / 500) + 1)))
            sample_every_ms = requested_sample_every_ms or max(120, round(duration_ms / max(max_samples, 1)) or 120)
            rules.append('ai-evidence-runtime-owned-grid')
        else:
            max_samples = max(requested_max_samples or 0, 14)
            sample_every_ms = requested_sample_every_ms or max(90, round(duration_ms / 14) or 90)
            rules.append('interactive-range-grid')

        max_samples = max(4, min(max_samples, 48))
        sample_every_ms = max(1, int(sample_every_ms))
        latency_budget_ms = _resolve_latency_budget(payload, intent)

        return ResolvedIntervalAnalysisPolicy(
            intent=intent,
            duration_ms=duration_ms,
            short_interval=duration_ms <= SHORT_INTERVAL_MAX_MS,
            requested_sample_every_ms=requested_sample_every_ms,
            requested_max_samples=requested_max_samples,
            sample_every_ms=sample_every_ms,
            max_samples=max_samples,
            latency_budget_ms=latency_budget_ms,
            analysis_profile_id=options.analysis_profile_id,
            rules=tuple(rules),
        )


def _resolve_intent(payload: dict[str, Any], duration_ms: int) -> str:
    raw_intent = str(payload.get('analysisIntent') or '').strip()
    if raw_intent in KNOWN_INTERVAL_INTENTS:
        return raw_intent
    if duration_ms <= SHORT_INTERVAL_MAX_MS:
        return 'interactive-short-range'
    return 'interactive-range'


def _resolve_latency_budget(payload: dict[str, Any], intent: str) -> int:
    explicit_budget = _optional_positive_int(payload.get('latencyBudgetMs'))
    if explicit_budget is not None:
        return max(1_000, min(explicit_budget, 300_000))
    if intent == 'ai-evidence-range':
        return DEFAULT_AI_EVIDENCE_LATENCY_BUDGET_MS
    return DEFAULT_INTERACTIVE_LATENCY_BUDGET_MS


def _optional_positive_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        return None
    return resolved if resolved > 0 else None


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback