from __future__ import annotations

from dataclasses import dataclass
from typing import Any


READABLE_EXPECTATION_KIND = 'readable'
UNREADABLE_EXPECTATION_KIND = 'unreadable'


def _normalize_optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def normalize_expectation_kind(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in {READABLE_EXPECTATION_KIND, UNREADABLE_EXPECTATION_KIND}:
        return normalized
    return None


def resolve_case_expectation(payload: dict[str, Any]) -> tuple[str, str | None]:
    expectation_payload = payload.get('expectation') if isinstance(payload.get('expectation'), dict) else None
    expected_text = _normalize_optional_text(payload.get('expectedText'))

    if expectation_payload is None:
        if expected_text is not None:
            return READABLE_EXPECTATION_KIND, expected_text
        return UNREADABLE_EXPECTATION_KIND, None

    expectation_kind = normalize_expectation_kind(expectation_payload.get('kind'))
    if expectation_kind == READABLE_EXPECTATION_KIND:
        return READABLE_EXPECTATION_KIND, _normalize_optional_text(expectation_payload.get('text')) or expected_text
    if expectation_kind == UNREADABLE_EXPECTATION_KIND:
        return UNREADABLE_EXPECTATION_KIND, None
    if expected_text is not None:
        return READABLE_EXPECTATION_KIND, expected_text
    return UNREADABLE_EXPECTATION_KIND, None


def format_case_expectation(expectation_kind: str, expected_text: str | None) -> str:
    if expectation_kind == UNREADABLE_EXPECTATION_KIND:
        return 'unreadable/no-read'
    return expected_text or '--'


@dataclass(slots=True)
class BenchmarkCase:
    id: str
    mode: str
    source_path: str
    expectation_kind: str
    expected_text: str | None
    payload: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> 'BenchmarkCase':
        expectation_kind, expected_text = resolve_case_expectation(payload)
        return cls(
            id=str(payload.get('id') or ''),
            mode=str(payload.get('mode') or ''),
            source_path=str(payload.get('sourcePath') or ''),
            expectation_kind=expectation_kind,
            expected_text=expected_text,
            payload=dict(payload),
        )

    def to_payload(self) -> dict[str, Any]:
        return dict(self.payload)

    @property
    def tags(self) -> list[str]:
        return [str(tag) for tag in self.payload.get('tags') or []]


@dataclass(slots=True)
class BenchmarkSuite:
    schema_version: int
    suite_id: str
    title: str | None
    analysis_profile_id: str | None
    source: dict[str, Any] | None
    cases: list[BenchmarkCase]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> 'BenchmarkSuite':
        return cls(
            schema_version=int(payload.get('schemaVersion') or 1),
            suite_id=str(payload.get('suiteId') or ''),
            title=str(payload['title']) if isinstance(payload.get('title'), str) else None,
            analysis_profile_id=str(payload['analysisProfileId']) if isinstance(payload.get('analysisProfileId'), str) else None,
            source=dict(payload.get('source') or {}) if isinstance(payload.get('source'), dict) else None,
            cases=[BenchmarkCase.from_payload(case) for case in (payload.get('cases') or []) if isinstance(case, dict)],
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            'schemaVersion': self.schema_version,
            'suiteId': self.suite_id,
            'title': self.title,
            'analysisProfileId': self.analysis_profile_id,
            'source': dict(self.source) if self.source is not None else None,
            'cases': [case.to_payload() for case in self.cases],
        }

    def mode_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for case in self.cases:
            counts[case.mode] = counts.get(case.mode, 0) + 1
        return counts

    def top_tags(self, limit: int = 10) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        for case in self.cases:
            for tag in case.tags:
                counts[tag] = counts.get(tag, 0) + 1
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]


@dataclass(slots=True)
class BenchmarkRunBundle:
    run_id: str
    generated_at: str
    suite_id: str
    suite_title: str | None
    suite_case_count: int
    result: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return {
            'runId': self.run_id,
            'generatedAt': self.generated_at,
            'suite': {
                'suiteId': self.suite_id,
                'title': self.suite_title,
                'caseCount': self.suite_case_count,
            },
            'result': dict(self.result),
        }
