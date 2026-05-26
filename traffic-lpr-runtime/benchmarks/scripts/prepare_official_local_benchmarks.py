from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

import cv2

from benchmark_catalog import build_dataset_source_catalog, build_official_suite_catalog
from common import ArchiveSource, BenchmarkSourceSample, HARD_CASE_CATEGORIES, resolve_benchmark_paths
from prepare_multisource_benchmark import (
    _add_image_hard_case_tags,
    _build_image_thresholds,
    _build_ufpr_track_sample,
    _compute_blur_score,
    _compute_brightness,
    _compute_plate_area_ratio,
    _load_aolp,
    _materialize_manifest,
    _parse_lp2025_annotations,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
BENCHMARK_TOOL_ROOT = REPO_ROOT / 'traffic-lpr-benchmark'
if str(BENCHMARK_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_TOOL_ROOT))

from legacy_import import import_legacy_manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Materialize official local benchmark manifests and benchmark suites into the shared runtime cache.'
    )
    parser.add_argument('--runtime-root', type=Path, default=Path(__file__).resolve().parents[2], help='traffic-lpr-runtime project root.')
    parser.add_argument('--analysis-profile', default='precision', help='Analysis profile id to stamp onto imported benchmark suites.')
    parser.add_argument('--per-category', type=int, default=1, help='How many cases to keep per hard-case category inside each official local suite.')
    parser.add_argument('--max-cases', type=int, default=4, help='Maximum number of cases to keep per official local suite after category selection.')
    parser.add_argument('--ufpr-split', choices=['training', 'testing', 'validation', 'all'], default='testing', help='UFPR split to use for the official moving-camera suite.')
    parser.add_argument('--lp2025-split', choices=['train', 'val', 'test', 'all'], default='test', help='LP2025 split to use for the official readable OCR suite.')
    parser.add_argument('--ufpr-video-fps', type=int, default=10, help='Frame rate for materialized UFPR interval videos.')
    parser.add_argument('--lp2025-scan-limit', type=int, default=600, help='Maximum number of LP2025 label instances to scan for the official local suites.')
    parser.add_argument('--ufpr-track-limit', type=int, default=60, help='Maximum number of UFPR tracks to scan for the official local suites.')
    args = parser.parse_args()

    runtime_root = args.runtime_root.resolve()
    repo_root = runtime_root.parent
    paths = resolve_benchmark_paths(runtime_root)
    manifest_root = (paths.local_manifest_root / 'official').resolve()
    suite_root = (paths.runtime_benchmark_root / 'suites' / 'official').resolve()
    dataset_root = (paths.dataset_root / 'official').resolve()
    catalog = build_dataset_source_catalog(repo_root)
    official_suites = {policy.suite_id: policy for policy in build_official_suite_catalog(repo_root)}

    prepared_suites: dict[str, dict[str, Any]] = {}
    smoke_cases: list[dict[str, Any]] = []

    suite_definitions = (
        OfficialLocalSuiteDefinition(
            suite_id='aolp-readable-ocr',
            dataset_id='aolp',
            title='Official AOLP Readable OCR Gate',
            loader=lambda roots: _load_aolp(roots['aolp'], ['ac', 'le', 'rp']),
            include_case=lambda sample: sample.expectation_kind == 'readable',
        ),
        OfficialLocalSuiteDefinition(
            suite_id='lp2025-readable-ocr',
            dataset_id='lp2025',
            title='Official LP2025 Readable OCR Gate',
            loader=lambda roots: _load_lp2025_fast(roots['lp2025'], args.lp2025_split, args.lp2025_scan_limit),
            include_case=lambda sample: sample.expectation_kind == 'readable',
        ),
        OfficialLocalSuiteDefinition(
            suite_id='ufpr-moving-camera',
            dataset_id='ufpr-alpr',
            title='Official UFPR Moving Camera Reliability Gate',
            loader=lambda roots: _load_ufpr_fast(roots['ufpr-alpr'], args.ufpr_split, args.ufpr_video_fps, args.ufpr_track_limit),
            include_case=lambda sample: sample.case_mode == 'interval',
        ),
    )

    resolved_roots = {
        dataset_id: policy.resolve_root()
        for dataset_id, policy in catalog.items()
    }

    for definition in suite_definitions:
        suite_output_root = dataset_root / definition.suite_id
        manifest_path = manifest_root / definition.suite_id / 'all.json'
        suite_path = suite_root / f'{definition.suite_id}.json'
        policy = official_suites.get(definition.suite_id)

        print(f'[official-benchmark] loading suite={definition.suite_id} dataset={definition.dataset_id}', flush=True)
        archive_source, raw_samples, loader_summary = definition.loader(resolved_roots)
        print(
            f'[official-benchmark] loaded suite={definition.suite_id} rawSamples={len(raw_samples)}',
            flush=True,
        )
        selected_samples = _select_official_samples(
            [sample for sample in raw_samples if definition.include_case(sample)],
            per_category=args.per_category,
            max_cases=args.max_cases,
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
                'officialPolicy': policy.to_payload() if policy is not None else None,
                'loaderSummary': loader_summary,
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

        smoke_case = manifest_payload['cases'][0] if manifest_payload.get('cases') else None
        if isinstance(smoke_case, dict):
            smoke_cases.append(_build_smoke_case(smoke_case))

        prepared_suites[definition.suite_id] = {
            'datasetId': definition.dataset_id,
            'resolvedSourceRoot': str((resolved_roots.get(definition.dataset_id) or Path('.')).resolve()) if resolved_roots.get(definition.dataset_id) is not None else None,
            'manifestPath': str(manifest_path.resolve()),
            'suitePath': str(suite_path.resolve()),
            'materializedRoot': str(suite_output_root.resolve()),
            'caseCount': len(manifest_payload.get('cases') or []),
            'materializedSourcePaths': [str(case.get('sourcePath')) for case in manifest_payload.get('cases') or []],
            'selectedArchiveMembers': _selected_archive_members(selected_samples),
            'loaderSummary': loader_summary,
        }

    local_dashcam_manifest_path = manifest_root / 'local-dashcam-tracking' / 'all.json'
    local_dashcam_suite_path = suite_root / 'local-dashcam-tracking.json'
    print('[official-benchmark] preparing suite=local-dashcam-tracking dataset=local-dashcam', flush=True)
    local_dashcam_payload = _prepare_local_dashcam_manifest(repo_root, official_suites.get('local-dashcam-tracking'))
    _write_json(local_dashcam_manifest_path, local_dashcam_payload)
    local_dashcam_suite = import_legacy_manifest(
        manifest_path=local_dashcam_manifest_path,
        suite_id='local-dashcam-tracking',
        title='Official Local Dashcam Tracking Gate',
        analysis_profile_id=args.analysis_profile,
    )
    _write_json(local_dashcam_suite_path, local_dashcam_suite)
    if local_dashcam_payload.get('cases'):
        smoke_cases.append(_build_smoke_case(local_dashcam_payload['cases'][0]))
    prepared_suites['local-dashcam-tracking'] = {
        'datasetId': 'local-dashcam',
        'resolvedSourceRoot': str((resolved_roots.get('local-dashcam') or Path('.')).resolve()) if resolved_roots.get('local-dashcam') is not None else None,
        'manifestPath': str(local_dashcam_manifest_path.resolve()),
        'suitePath': str(local_dashcam_suite_path.resolve()),
        'materializedRoot': None,
        'caseCount': len(local_dashcam_payload.get('cases') or []),
        'materializedSourcePaths': [str(case.get('sourcePath')) for case in local_dashcam_payload.get('cases') or []],
        'selectedArchiveMembers': [],
        'loaderSummary': local_dashcam_payload.get('summary') or {},
    }

    smoke_manifest_path = manifest_root / 'smoke' / 'all.json'
    smoke_suite_path = suite_root / 'official-local-smoke.json'
    print('[official-benchmark] preparing suite=official-local-smoke dataset=mixed-local', flush=True)
    smoke_manifest_payload = {
        'summary': {
            'suiteId': 'official-local-smoke',
            'title': 'Official Local Benchmark Smoke Suite',
            'caseCount': len(smoke_cases),
            'datasets': sorted({str(case.get('metadata', {}).get('dataset') or 'unknown') for case in smoke_cases}),
        },
        'cases': smoke_cases,
    }
    _write_json(smoke_manifest_path, smoke_manifest_payload)
    smoke_suite_payload = import_legacy_manifest(
        manifest_path=smoke_manifest_path,
        suite_id='official-local-smoke',
        title='Official Local Benchmark Smoke Suite',
        analysis_profile_id=args.analysis_profile,
    )
    _write_json(smoke_suite_path, smoke_suite_payload)
    print('[official-benchmark] completed suite=official-local-smoke', flush=True)

    prune_recommendations = []
    for dataset_id in ('aolp', 'lp2025', 'ufpr-alpr'):
        policy = catalog[dataset_id]
        resolved_root = policy.resolve_root()
        if resolved_root is None:
            continue
        matching_suite = next((suite for suite in prepared_suites.values() if suite['datasetId'] == dataset_id), None)
        materialized_root = Path(str(matching_suite['materializedRoot'])) if matching_suite and matching_suite.get('materializedRoot') else None
        prune_recommendations.append(
            {
                'datasetId': dataset_id,
                'retentionClass': policy.retention_class,
                'resolvedSourceRoot': str(resolved_root),
                'protectedArchives': [str(path.resolve()) for path in policy.protected_paths],
                'materializedRoot': str(materialized_root.resolve()) if materialized_root is not None else None,
                'safeToDeleteExtractedRoot': bool(materialized_root is not None and materialized_root.exists()),
                'reason': 'Official benchmark suites now reference materialized copies under .runtime/cache/benchmark/datasets/official/.',
            }
        )

    output = {
        'manifestRoot': str(manifest_root.resolve()),
        'suiteRoot': str(suite_root.resolve()),
        'preparedSuites': prepared_suites,
        'smokeManifestPath': str(smoke_manifest_path.resolve()),
        'smokeSuitePath': str(smoke_suite_path.resolve()),
        'pruneRecommendations': prune_recommendations,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


class OfficialLocalSuiteDefinition:
    def __init__(
        self,
        *,
        suite_id: str,
        dataset_id: str,
        title: str,
        loader: Callable[[dict[str, Path | None]], tuple[Any, list[BenchmarkSourceSample], dict[str, Any]]],
        include_case: Callable[[BenchmarkSourceSample], bool],
    ) -> None:
        self.suite_id = suite_id
        self.dataset_id = dataset_id
        self.title = title
        self.loader = loader
        self.include_case = include_case


def _load_lp2025_fast(root: Path | None, split: str, scan_limit: int) -> tuple[ArchiveSource, list[BenchmarkSourceSample], dict[str, Any]]:
    if root is None or not root.exists():
        raise FileNotFoundError(f'LP2025 dataset root was not found: {root}')

    split_names = ['train', 'val', 'test'] if split == 'all' else [split]
    raw_samples: list[BenchmarkSourceSample] = []
    split_counts: Counter[str] = Counter()
    expectation_counts: Counter[str] = Counter()
    skipped_images = 0
    skipped_labels = 0
    limit_reached = False

    for split_name in split_names:
        split_dir = root / split_name
        image_dir = split_dir / 'images'
        label_dir = split_dir / 'labels_gd'
        if not image_dir.exists() or not label_dir.exists():
            raise FileNotFoundError(f'LP2025 split is incomplete: {split_dir}')

        image_paths = sorted(
            image_dir.glob('*.jpg'),
            key=lambda path: (0, int(path.stem)) if path.stem.isdigit() else (1, path.stem),
        )
        for image_path in image_paths:
            if scan_limit > 0 and len(raw_samples) >= scan_limit:
                limit_reached = True
                break

            image = cv2.imread(str(image_path))
            if image is None:
                skipped_images += 1
                continue

            label_path = label_dir / f'{image_path.stem}.txt'
            if not label_path.exists():
                skipped_images += 1
                continue

            annotations = _parse_lp2025_annotations(label_path.read_text(encoding='utf-8', errors='ignore'), image.shape[1], image.shape[0])
            if not annotations:
                skipped_images += 1
                continue

            brightness = _compute_brightness(image)
            relative_image_path = image_path.relative_to(root).as_posix()
            for annotation in annotations:
                if scan_limit > 0 and len(raw_samples) >= scan_limit:
                    limit_reached = True
                    break
                bbox = annotation.get('bbox')
                if bbox is None:
                    skipped_labels += 1
                    continue
                blur_score = _compute_blur_score(image, bbox)
                plate_area_ratio = _compute_plate_area_ratio(bbox, image.shape[1], image.shape[0])
                expectation_kind = str(annotation['expectation_kind'])
                expected_text = annotation.get('expected_text')
                label_index = int(annotation['label_index'])
                tags = ['local-dataset', 'lp2025', 'taiwan', split_name]
                tags.append('unreadable' if expectation_kind == 'unreadable' else 'readable')
                split_counts[split_name] += 1
                expectation_counts[expectation_kind] += 1
                raw_samples.append(BenchmarkSourceSample(
                    dataset_key='lp2025',
                    dataset_name='LP2025',
                    archive_member=relative_image_path,
                    expectation_kind=expectation_kind,
                    expected_text=expected_text,
                    bbox=bbox,
                    split=split_name,
                    brightness=brightness,
                    blur_score=blur_score,
                    plate_area_ratio=plate_area_ratio,
                    angle_degrees=annotation.get('angle_degrees'),
                    tags=tags,
                    instance_id=f'{image_path.stem}-{label_index}',
                    country_hints=['TW'],
                    metadata={
                        'dataset': 'LP2025',
                        'split': split_name,
                        'relativeImagePath': relative_image_path,
                        'labelIndex': label_index,
                        'rawLabelText': annotation.get('raw_label'),
                        'expectationKind': expectation_kind,
                        'bbox': {'x1': bbox[0], 'y1': bbox[1], 'x2': bbox[2], 'y2': bbox[3]},
                    },
                ))
            if limit_reached:
                break
        if limit_reached:
            break

    thresholds = _build_image_thresholds(raw_samples)
    for sample in raw_samples:
        _add_image_hard_case_tags(sample, thresholds)

    summary = {
        'dataset': 'LP2025',
        'sampleCount': len(raw_samples),
        'split': split,
        'splitCounts': dict(split_counts),
        'expectationCounts': dict(expectation_counts),
        'skippedImages': skipped_images,
        'skippedLabels': skipped_labels,
        'thresholds': thresholds,
        'sourceRoot': str(root),
        'scanLimit': scan_limit,
        'scanLimitReached': limit_reached,
    }
    return ArchiveSource(kind='filesystem', location=str(root)), raw_samples, summary


def _load_ufpr_fast(root: Path | None, split: str, video_fps: int, track_limit: int) -> tuple[ArchiveSource, list[BenchmarkSourceSample], dict[str, Any]]:
    if root is None or not root.exists():
        raise FileNotFoundError(f'UFPR-ALPR dataset root was not found: {root}')

    split_names = ['training', 'testing', 'validation'] if split == 'all' else [split]
    raw_samples: list[BenchmarkSourceSample] = []
    split_counts: Counter[str] = Counter()
    camera_counts: Counter[str] = Counter()
    skipped_tracks = 0
    total_frames = 0
    limit_reached = False

    for split_name in split_names:
        split_dir = root / split_name
        if not split_dir.exists():
            raise FileNotFoundError(f'UFPR split was not found: {split_dir}')
        track_dirs = sorted((path for path in split_dir.iterdir() if path.is_dir()), key=lambda path: path.name)
        for track_dir in track_dirs:
            if track_limit > 0 and len(raw_samples) >= track_limit:
                limit_reached = True
                break
            sample = _build_ufpr_track_sample(root, split_name, track_dir, video_fps)
            if sample is None:
                skipped_tracks += 1
                continue
            raw_samples.append(sample)
            split_counts[split_name] += 1
            total_frames += int(sample.metadata.get('frameCount') or 0)
            camera_label = str(sample.metadata.get('camera') or 'unknown')
            camera_counts[camera_label] += 1
        if limit_reached:
            break

    thresholds = _build_image_thresholds(raw_samples)
    for sample in raw_samples:
        _add_image_hard_case_tags(sample, thresholds)

    summary = {
        'dataset': 'UFPR-ALPR',
        'trackCount': len(raw_samples),
        'frameCount': total_frames,
        'split': split,
        'splitCounts': dict(split_counts),
        'cameraCounts': dict(camera_counts),
        'skippedTracks': skipped_tracks,
        'thresholds': thresholds,
        'sourceRoot': str(root),
        'materializedVideoFps': video_fps,
        'trackLimit': track_limit,
        'trackLimitReached': limit_reached,
    }
    return ArchiveSource(kind='filesystem', location=str(root)), raw_samples, summary


def _select_official_samples(
    samples: list[BenchmarkSourceSample],
    *,
    per_category: int,
    max_cases: int,
) -> list[BenchmarkSourceSample]:
    selected: list[BenchmarkSourceSample] = []
    used_names: set[str] = set()

    for category in HARD_CASE_CATEGORIES:
        candidates = [sample for sample in samples if category in sample.tags and sample.unique_name not in used_names]
        candidates.sort(key=_sample_rank)
        for sample in candidates[:max(per_category, 0)]:
            selected.append(sample)
            used_names.add(sample.unique_name)
            if max_cases > 0 and len(selected) >= max_cases:
                return selected

    if max_cases <= 0:
        return selected

    fallback = [sample for sample in samples if sample.unique_name not in used_names]
    fallback.sort(key=_sample_rank)
    for sample in fallback:
        selected.append(sample)
        used_names.add(sample.unique_name)
        if len(selected) >= max_cases:
            break
    return selected


def _sample_rank(sample: BenchmarkSourceSample) -> tuple[float, str, str, str]:
    return (
        -sample.hardness_score(),
        str(sample.split),
        str(sample.archive_member),
        str(sample.instance_id or ''),
    )


def _group_selected_samples(samples: list[BenchmarkSourceSample]) -> dict[str, list[BenchmarkSourceSample]]:
    grouped: dict[str, list[BenchmarkSourceSample]] = defaultdict(list)
    for sample in samples:
        grouped[sample.dominant_category()].append(sample)
    return dict(grouped)


def _selected_archive_members(samples: list[BenchmarkSourceSample]) -> list[str]:
    return [sample.archive_member for sample in samples]


def _build_smoke_case(case_payload: dict[str, Any]) -> dict[str, Any]:
    cloned_case = copy.deepcopy(case_payload)
    analysis_options = dict(cloned_case.get('analysisOptions') or {})
    analysis_options['restorationMode'] = 'off'
    cloned_case['analysisOptions'] = analysis_options
    return cloned_case


def _prepare_local_dashcam_manifest(
    repo_root: Path,
    policy: Any,
) -> dict[str, Any]:
    template_path = repo_root / 'traffic-lpr-runtime' / 'benchmarks' / 'manifests' / 'templates' / 'local-dashcam-nce9762.json'
    payload = json.loads(template_path.read_text(encoding='utf-8'))
    payload['summary'] = {
        'suiteId': 'local-dashcam-tracking',
        'title': 'Official Local Dashcam Tracking Gate',
        'caseCount': len(payload.get('cases') or []),
        'officialPolicy': policy.to_payload() if policy is not None else None,
        'templatePath': str(template_path.resolve()),
    }
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    raise SystemExit(main())