from __future__ import annotations

from pathlib import Path
from typing import Any

from models import BenchmarkCase, BenchmarkSuite
from validation import ValidationError, load_json


def import_legacy_manifest(
    manifest_path: Path,
    suite_id: str,
    title: str | None = None,
    analysis_profile_id: str = 'balanced',
    limit: int | None = None,
) -> dict[str, Any]:
    legacy_payload = load_json(manifest_path)
    legacy_cases = legacy_payload.get('cases')
    if not isinstance(legacy_cases, list) or not legacy_cases:
        raise ValidationError(f'{manifest_path}: expected a legacy manifest with a non-empty cases array')

    suite_title = title or suite_id.replace('-', ' ').strip().title()
    migrated_cases: list[BenchmarkCase] = []
    for case in legacy_cases[:limit] if limit and limit > 0 else legacy_cases:
        if not isinstance(case, dict):
            raise ValidationError(f'{manifest_path}: all cases must be JSON objects')
        migrated_case = dict(case)
        migrated_case.setdefault('metadata', {})
        if isinstance(migrated_case['metadata'], dict):
            migrated_case['metadata'] = {
                **migrated_case['metadata'],
                'legacyManifestPath': str(manifest_path.resolve()),
            }
        migrated_case.setdefault('analysisProfileId', analysis_profile_id)
        migrated_cases.append(BenchmarkCase.from_payload(migrated_case))

    return BenchmarkSuite(
        schema_version=1,
        suite_id=suite_id,
        title=suite_title,
        analysis_profile_id=analysis_profile_id,
        source={
            'kind': 'legacy-manifest',
            'path': str(manifest_path.resolve()),
        },
        cases=migrated_cases,
    ).to_payload()
