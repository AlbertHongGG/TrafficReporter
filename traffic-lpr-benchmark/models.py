from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class BenchmarkCase:
    id: str
    mode: str
    source_path: str
    expected_text: str
    payload: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> 'BenchmarkCase':
        return cls(
            id=str(payload.get('id') or ''),
            mode=str(payload.get('mode') or ''),
            source_path=str(payload.get('sourcePath') or ''),
            expected_text=str(payload.get('expectedText') or ''),
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
