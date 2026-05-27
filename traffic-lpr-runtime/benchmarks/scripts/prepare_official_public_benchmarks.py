from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from benchmark_catalog import build_dataset_source_catalog, build_official_suite_catalog
from common import ArchiveSource, BenchmarkSourceSample, resolve_benchmark_paths
from prepare_multisource_benchmark import _load_ccpd, _load_uc3m, _materialize_manifest
from prepare_official_local_benchmarks import (
    OfficialCurationPolicy,
    _build_selection_status,
    _group_selected_samples,
    _load_curation_policies,
    _selected_archive_members,
    _select_official_samples,
    _write_json,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
BENCHMARK_TOOL_ROOT = REPO_ROOT / 'traffic-lpr-benchmark'
if str(BENCHMARK_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_TOOL_ROOT))

from legacy_import import import_legacy_manifest


class OfficialPublicSuiteDefinition:
    def __init__(
        self,
        *,
        suite_id: str,
        dataset_id: str,
        title: str,
        loader: Callable[[], tuple[ArchiveSource, list[BenchmarkSourceSample], dict[str, Any]]],
    ) -> None:
        self.suite_id = suite_id
        self.dataset_id = dataset_id
        self.title = title
        self.loader = loader


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Materialize official public benchmark manifests and benchmark suites into the shared runtime cache.'
    )
    parser.add_argument('--runtime-root', type=Path, default=Path(__file__).resolve().parents[2], help='traffic-lpr-runtime project root.')
    parser.add_argument('--analysis-profile', default='precision', help='Analysis profile id to stamp onto imported benchmark suites.')
    parser.add_argument('--per-category', type=int, default=3, help='Fallback number of cases to keep per hard-case category inside each official public suite.')
    parser.add_argument('--max-cases', type=int, default=24, help='Fallback maximum number of cases to keep per official public suite after category selection.')
    parser.add_argument('--uc3m-split', choices=['train', 'val', 'test', 'all'], default='test', help='UC3M split to use for the official readable OCR suite.')
    parser.add_argument('--uc3m-scan-limit', type=int, default=800, help='Maximum number of UC3M annotation JSON files to scan when preparing the official public suite.')
    parser.add_argument('--suite-id', choices=['all', 'ccpd-readable-ocr', 'uc3m-readable-ocr'], default='all', help='Optional single official public suite to generate.')
    parser.add_argument('--cache-dir', type=Path, default=None, help='Optional override for the benchmark cache root used by public dataset downloads.')
    args = parser.parse_args()

    runtime_root = args.runtime_root.resolve()
    repo_root = runtime_root.parent
    paths = resolve_benchmark_paths(runtime_root)
    cache_root = args.cache_dir.resolve() if args.cache_dir is not None else paths.cache_root.resolve()
    manifest_root = (paths.runtime_benchmark_root / 'manifests' / 'public' / 'official').resolve()
    suite_root = (paths.runtime_benchmark_root / 'suites' / 'official').resolve()
    dataset_root = (paths.dataset_root / 'official').resolve()
    catalog = build_dataset_source_catalog(repo_root)
    official_suites = {policy.suite_id: policy for policy in build_official_suite_catalog(repo_root)}
    curation_policies = _load_curation_policies(runtime_root / 'benchmarks' / 'config' / 'official_public_curation.json')

    suite_definitions_by_id = {
        'ccpd-readable-ocr': OfficialPublicSuiteDefinition(
            suite_id='ccpd-readable-ocr',
            dataset_id='ccpd',
            title='Official CCPD Readable OCR Gate',
            loader=lambda: _load_ccpd(cache_root),
        ),
        'uc3m-readable-ocr': OfficialPublicSuiteDefinition(
            suite_id='uc3m-readable-ocr',
            dataset_id='uc3m-lp',
            title='Official UC3M Readable OCR Gate',
            loader=lambda: _load_uc3m(args.uc3m_split, args.uc3m_scan_limit),
        ),
    }
    selected_suite_ids = tuple(suite_definitions_by_id) if args.suite_id == 'all' else (args.suite_id,)
    suite_definitions = tuple(suite_definitions_by_id[suite_id] for suite_id in selected_suite_ids)

    prepared_suites: dict[str, dict[str, Any]] = {}

    for definition in suite_definitions:
        suite_output_root = dataset_root / definition.suite_id
        manifest_path = manifest_root / definition.suite_id / 'all.json'
        suite_path = suite_root / f'{definition.suite_id}.json'
        source_policy = catalog[definition.dataset_id]
        official_policy = official_suites.get(definition.suite_id)

        print(f'[official-benchmark] loading suite={definition.suite_id} dataset={definition.dataset_id}', flush=True)
        archive_source, raw_samples, loader_summary = definition.loader()
        print(
            f'[official-benchmark] loaded suite={definition.suite_id} rawSamples={len(raw_samples)}',
            flush=True,
        )

        curation_policy = curation_policies.get(definition.suite_id, OfficialCurationPolicy())
        candidate_samples = [sample for sample in raw_samples if sample.expectation_kind == 'readable']
        eligible_samples = [sample for sample in candidate_samples if curation_policy.allows(sample)]
        selected_samples = _select_official_samples(
            eligible_samples,
            per_category=curation_policy.resolve_per_category(args.per_category),
            max_cases=curation_policy.resolve_target_case_count(args.max_cases),
            curation_policy=curation_policy,
        )
        selection_status = _build_selection_status(
            candidate_samples=candidate_samples,
            eligible_samples=eligible_samples,
            selected_samples=selected_samples,
            curation_policy=curation_policy,
        )
        if selection_status['underfilled']:
            print(
                f"[official-benchmark] warning suite={definition.suite_id} selected={selection_status['selectedCaseCount']} minimum={selection_status['minimumCaseCount']} eligible={selection_status['eligibleCaseCount']}",
                flush=True,
            )
        print(
            f'[official-benchmark] selected suite={definition.suite_id} cases={len(selected_samples)}',
            flush=True,
        )

        manifest_payload = _materialize_manifest(
            {definition.dataset_id: archive_source},
            _group_selected_samples(selected_samples),
            suite_output_root,
        )
        manifest_payload['summary'].update(
            {
                'suiteId': definition.suite_id,
                'title': definition.title,
                'officialPolicy': official_policy.to_payload() if official_policy is not None else None,
                'loaderSummary': loader_summary,
                'selectionStatus': selection_status,
                'curationPolicy': curation_policy.to_payload(),
                'sourceKind': source_policy.source_kind,
                'retentionClass': source_policy.retention_class,
            }
        )
        _write_json(manifest_path, manifest_payload)
        suite_payload = import_legacy_manifest(
            manifest_path=manifest_path,
            suite_id=definition.suite_id,
            title=definition.title,
            analysis_profile_id=args.analysis_profile,
        )
        _write_json(suite_path, suite_payload)
        print(
            f'[official-benchmark] wrote suite={definition.suite_id} manifest={manifest_path.resolve()}',
            flush=True,
        )

        prepared_suites[definition.suite_id] = {
            'datasetId': definition.dataset_id,
            'sourceKind': archive_source.kind,
            'resolvedSourceRoot': _source_location(archive_source),
            'manifestPath': str(manifest_path.resolve()),
            'suitePath': str(suite_path.resolve()),
            'materializedRoot': str(suite_output_root.resolve()),
            'caseCount': len(manifest_payload.get('cases') or []),
            'materializedSourcePaths': [str(case.get('sourcePath')) for case in manifest_payload.get('cases') or []],
            'selectedArchiveMembers': _selected_archive_members(selected_samples),
            'loaderSummary': loader_summary,
            'selectionStatus': selection_status,
            'curationPolicy': curation_policy.to_payload(),
        }

    output = {
        'cacheRoot': str(cache_root),
        'manifestRoot': str(manifest_root.resolve()),
        'suiteRoot': str(suite_root.resolve()),
        'preparedSuites': prepared_suites,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def _source_location(source: ArchiveSource) -> str:
    if source.kind in {'local', 'filesystem'}:
        return str(Path(source.location).resolve())
    return source.location


if __name__ == '__main__':
    raise SystemExit(main())