from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable
from zipfile import ZipFile

import cv2
import numpy as np
from huggingface_hub import hf_hub_download
from remotezip import RemoteZip

from benchmark_catalog import build_dataset_source_catalog, build_official_suite_catalog
from common import (
    ArchiveSource,
    BenchmarkSourceSample,
    CCPD_ARCHIVE_NAME,
    CCPD_REPO_ID,
    DirectoryArchive,
    HARD_CASE_CATEGORIES,
    PLATE_TEXT_PATTERN,
    UC3M_ARCHIVE_CONTENT_URL,
    build_marker_rect,
    default_frame_analysis_options,
    default_interval_analysis_options,
    parse_ccpd_name,
    quantile,
    quantile_float,
    resolve_benchmark_paths,
    normalize_expected_text,
)


def main() -> int:
    parser = argparse.ArgumentParser(description='Prepare multi-source hard-case benchmark manifests from public and local datasets.')
    parser.add_argument('--datasets', nargs='+', default=['ccpd', 'uc3m-lp'], choices=['ccpd', 'uc3m-lp', 'aolp', 'ufpr-alpr', 'lp2025'], help='Datasets to include in the generated benchmark.')
    parser.add_argument('--per-category', type=int, default=20, help='How many unique cases to keep per hard-case category across sources.')
    parser.add_argument('--seed', type=int, default=7, help='Deterministic sampling seed.')
    parser.add_argument('--runtime-root', type=Path, default=Path(__file__).resolve().parents[2], help='traffic-lpr-runtime project root.')
    parser.add_argument('--output-manifest', type=Path, default=None, help='Path for the combined benchmark manifest JSON.')
    parser.add_argument('--output-images', type=Path, default=None, help='Directory where sampled images will be extracted.')
    parser.add_argument('--cache-dir', type=Path, default=None, help='Directory for downloaded dataset archives.')
    parser.add_argument('--split-output-dir', type=Path, default=None, help='Directory for development/holdout/challenge split manifests.')
    parser.add_argument('--uc3m-split', choices=['test', 'train', 'all'], default='test', help='Which UC3M split to sample from.')
    parser.add_argument('--aolp-root', type=Path, default=None, help='Path to the local AOLP dataset root.')
    parser.add_argument('--aolp-subsets', nargs='+', default=['ac', 'le', 'rp'], choices=['ac', 'le', 'rp'], help='Which AOLP subsets to include.')
    parser.add_argument('--lp2025-root', type=Path, default=None, help='Path to the local LP2025 dataset root.')
    parser.add_argument('--lp2025-split', choices=['train', 'val', 'test', 'all'], default='test', help='Which LP2025 split to sample from.')
    parser.add_argument('--ufpr-root', type=Path, default=None, help='Path to the local UFPR-ALPR dataset root.')
    parser.add_argument('--ufpr-split', choices=['training', 'testing', 'validation', 'all'], default='testing', help='Which UFPR split to sample from.')
    parser.add_argument('--ufpr-video-fps', type=int, default=10, help='Frame rate to use when materializing UFPR track videos for interval benchmarks.')
    args = parser.parse_args()

    runtime_root = args.runtime_root.resolve()
    repo_root = runtime_root.parent
    paths = resolve_benchmark_paths(runtime_root)
    cache_dir = (args.cache_dir or paths.cache_root).resolve()
    dataset_catalog = build_dataset_source_catalog(repo_root)
    official_suite_catalog = build_official_suite_catalog(repo_root)
    contains_local_datasets = any(dataset in {'aolp', 'ufpr-alpr', 'lp2025'} for dataset in args.datasets)
    default_manifest_root = (paths.local_manifest_root / 'multisource') if contains_local_datasets else paths.public_multisource_manifest_root
    output_manifest = (args.output_manifest or (default_manifest_root / 'all.json')).resolve()
    output_images = (args.output_images or (paths.dataset_root / ('local-multisource' if contains_local_datasets else 'multisource-hardcases'))).resolve()
    split_output_dir = (args.split_output_dir or default_manifest_root).resolve()
    aolp_root = _resolve_catalog_root(dataset_catalog, 'aolp', args.aolp_root)
    lp2025_root = _resolve_catalog_root(dataset_catalog, 'lp2025', args.lp2025_root)
    ufpr_root = _resolve_catalog_root(dataset_catalog, 'ufpr-alpr', args.ufpr_root)

    archive_sources: dict[str, ArchiveSource] = {}
    all_samples: list[BenchmarkSourceSample] = []
    summaries: dict[str, Any] = {}

    dataset_loaders = {
        'ccpd': lambda: _load_ccpd(cache_dir),
        'uc3m-lp': lambda: _load_uc3m(args.uc3m_split),
        'aolp': lambda: _load_aolp(aolp_root, [subset.lower() for subset in args.aolp_subsets]),
        'lp2025': lambda: _load_lp2025(lp2025_root, args.lp2025_split),
        'ufpr-alpr': lambda: _load_ufpr(ufpr_root, args.ufpr_split, args.ufpr_video_fps),
    }

    for dataset_name in args.datasets:
        archive_source, samples, summary = dataset_loaders[dataset_name]()
        archive_sources[dataset_name] = archive_source
        all_samples.extend(samples)
        summaries[dataset_name] = {
            **summary,
            'catalog': dataset_catalog[dataset_name].to_payload(),
        }

    selected = _select_balanced_samples(all_samples, per_category=args.per_category, seed=args.seed)
    manifest = _materialize_manifest(archive_sources, selected, output_images)
    split_manifests = _build_split_manifests(manifest, split_output_dir, args.seed)

    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'manifestPath': str(output_manifest),
        'imageRoot': str(output_images),
        'splits': split_manifests,
        'summary': manifest['summary'],
        'sources': summaries,
        'catalog': {
            'selectedSources': {
                dataset_name: dataset_catalog[dataset_name].to_payload()
                for dataset_name in args.datasets
            },
            'officialSuites': [
                suite.to_payload()
                for suite in official_suite_catalog
            ],
        },
    }, ensure_ascii=False))
    return 0


def _resolve_catalog_root(
    dataset_catalog: dict[str, Any],
    dataset_name: str,
    override: Path | None,
) -> Path:
    policy = dataset_catalog[dataset_name]
    resolved = policy.resolve_root(override)
    if resolved is None:
        raise FileNotFoundError(f'No root candidates were configured for dataset {dataset_name}.')
    return resolved


def _load_ccpd(cache_dir: Path) -> tuple[ArchiveSource, list[BenchmarkSourceSample], dict[str, Any]]:
    archive_path = Path(
        hf_hub_download(
            repo_id=CCPD_REPO_ID,
            repo_type='dataset',
            filename=CCPD_ARCHIVE_NAME,
            local_dir=cache_dir / 'hf-hub',
        )
    ).resolve()

    with ZipFile(archive_path) as archive:
        parsed = [parse_ccpd_name(Path(name).name) for name in archive.namelist() if name.lower().endswith('.jpg')]
    samples = [sample for sample in parsed if sample is not None]
    thresholds = _build_ccpd_thresholds(samples)

    prepared: list[BenchmarkSourceSample] = []
    for sample in samples:
        tags = ['public-dataset', 'ccpd', 'china', sample.subset]
        if sample.subset == 'weather':
            tags.append('weather')
        if sample.subset in {'tilt', 'rotate'}:
            tags.append('angle')
        if sample.subset == 'challenge':
            tags.append('challenge')
        if sample.subset == 'fn':
            tags.append('small-plate')
        if sample.subset == 'blur' or sample.blur >= thresholds['highBlur']:
            tags.append('blur')
        if sample.subset == 'db' or sample.brightness <= thresholds['lowBrightness']:
            tags.append('low-light')
        if sample.brightness >= thresholds['highBrightness']:
            tags.append('high-exposure')
        if sum(1 for category in ['blur', 'angle', 'small-plate', 'low-light', 'high-exposure', 'weather'] if category in tags) >= 2:
            tags.append('challenge')

        prepared.append(BenchmarkSourceSample(
            dataset_key='ccpd',
            dataset_name='CCPD subset 30k',
            archive_member=sample.archive_name,
            expectation_kind='readable',
            expected_text=sample.expected_text,
            bbox=(sample.x1, sample.y1, sample.x2, sample.y2),
            split=sample.subset,
            brightness=float(sample.brightness),
            blur_score=float(sample.blur),
            plate_area_ratio=None,
            angle_degrees=18.0 if sample.subset in {'tilt', 'rotate'} else None,
            tags=sorted(set(tags)),
            metadata={
                'dataset': 'CCPD subset 30k',
                'rawPlateText': sample.raw_plate_text,
                'subset': sample.subset,
                'brightness': sample.brightness,
                'blur': sample.blur,
                'bbox': {'x1': sample.x1, 'y1': sample.y1, 'x2': sample.x2, 'y2': sample.y2},
            },
        ))

    summary = {
        'dataset': 'CCPD subset 30k',
        'sampleCount': len(prepared),
        'thresholds': thresholds,
    }
    return ArchiveSource(kind='local', location=str(archive_path)), prepared, summary


def _load_aolp(root: Path, subsets: list[str]) -> tuple[ArchiveSource, list[BenchmarkSourceSample], dict[str, Any]]:
    if not root.exists():
        raise FileNotFoundError(f'AOLP dataset root was not found: {root}')

    raw_samples: list[BenchmarkSourceSample] = []
    subset_counts: Counter[str] = Counter()
    skipped = 0

    for subset in subsets:
        subset_code = subset.upper()
        subset_dir = root / f'Subset_{subset_code}'
        image_dir = subset_dir / 'Image'
        localization_dir = subset_dir / 'groundtruth_localization'
        recognition_dir = subset_dir / 'groundtruth_recognition'
        if not image_dir.exists() or not localization_dir.exists() or not recognition_dir.exists():
            nested_subset_dir = subset_dir / f'Subset_{subset_code}'
            nested_image_dir = nested_subset_dir / 'Image'
            nested_localization_dir = nested_subset_dir / 'groundtruth_localization'
            nested_recognition_dir = nested_subset_dir / 'groundtruth_recognition'
            if nested_image_dir.exists() and nested_localization_dir.exists() and nested_recognition_dir.exists():
                subset_dir = nested_subset_dir
                image_dir = nested_image_dir
                localization_dir = nested_localization_dir
                recognition_dir = nested_recognition_dir
        if not image_dir.exists() or not localization_dir.exists() or not recognition_dir.exists():
            raise FileNotFoundError(f'AOLP subset is incomplete: {subset_dir}')

        image_paths = sorted(
            image_dir.glob('*.jpg'),
            key=lambda path: (0, int(path.stem)) if path.stem.isdigit() else (1, path.stem),
        )
        for image_path in image_paths:
            image = cv2.imread(str(image_path))
            if image is None:
                skipped += 1
                continue

            localization_path = localization_dir / f'{image_path.stem}.txt'
            recognition_path = recognition_dir / f'{image_path.stem}.txt'
            if not localization_path.exists() or not recognition_path.exists():
                skipped += 1
                continue

            bbox = _parse_aolp_bbox(localization_path.read_text(encoding='utf-8', errors='ignore'), image.shape[1], image.shape[0])
            expected_text = normalize_expected_text(recognition_path.read_text(encoding='utf-8', errors='ignore'))
            if bbox is None or not expected_text or not PLATE_TEXT_PATTERN.match(expected_text):
                skipped += 1
                continue

            brightness = _compute_brightness(image)
            blur_score = _compute_blur_score(image, bbox)
            plate_area_ratio = _compute_plate_area_ratio(bbox, image.shape[1], image.shape[0])
            relative_image_path = image_path.relative_to(root).as_posix()
            subset_tag = f'subset-{subset.lower()}'
            subset_counts[subset_tag] += 1
            raw_samples.append(BenchmarkSourceSample(
                dataset_key='aolp',
                dataset_name='AOLP',
                archive_member=relative_image_path,
                expectation_kind='readable',
                expected_text=expected_text,
                bbox=bbox,
                split=subset_tag,
                brightness=brightness,
                blur_score=blur_score,
                plate_area_ratio=plate_area_ratio,
                angle_degrees=None,
                tags=['local-dataset', 'aolp', 'taiwan', subset_tag],
                country_hints=['TW'],
                metadata={
                    'dataset': 'AOLP',
                    'subset': subset_tag,
                    'bbox': {'x1': bbox[0], 'y1': bbox[1], 'x2': bbox[2], 'y2': bbox[3]},
                    'relativeImagePath': relative_image_path,
                },
            ))

    thresholds = _build_image_thresholds(raw_samples)
    for sample in raw_samples:
        _add_image_hard_case_tags(sample, thresholds)

    summary = {
        'dataset': 'AOLP',
        'sampleCount': len(raw_samples),
        'subsetCounts': dict(subset_counts),
        'skippedSamples': skipped,
        'thresholds': thresholds,
        'sourceRoot': str(root),
    }
    return ArchiveSource(kind='filesystem', location=str(root)), raw_samples, summary


def _load_lp2025(root: Path, split: str) -> tuple[ArchiveSource, list[BenchmarkSourceSample], dict[str, Any]]:
    if not root.exists():
        raise FileNotFoundError(f'LP2025 dataset root was not found: {root}')

    split_names = ['train', 'val', 'test'] if split == 'all' else [split]
    raw_samples: list[BenchmarkSourceSample] = []
    split_counts: Counter[str] = Counter()
    expectation_counts: Counter[str] = Counter()
    skipped_images = 0
    skipped_labels = 0

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
    }
    return ArchiveSource(kind='filesystem', location=str(root)), raw_samples, summary


def _load_ufpr(root: Path, split: str, video_fps: int) -> tuple[ArchiveSource, list[BenchmarkSourceSample], dict[str, Any]]:
    if not root.exists():
        raise FileNotFoundError(f'UFPR-ALPR dataset root was not found: {root}')

    split_names = ['training', 'testing', 'validation'] if split == 'all' else [split]
    raw_samples: list[BenchmarkSourceSample] = []
    split_counts: Counter[str] = Counter()
    camera_counts: Counter[str] = Counter()
    skipped_tracks = 0
    total_frames = 0

    for split_name in split_names:
        split_dir = root / split_name
        if not split_dir.exists():
            raise FileNotFoundError(f'UFPR split was not found: {split_dir}')
        track_dirs = sorted((path for path in split_dir.iterdir() if path.is_dir()), key=lambda path: path.name)
        for track_dir in track_dirs:
            sample = _build_ufpr_track_sample(root, split_name, track_dir, video_fps)
            if sample is None:
                skipped_tracks += 1
                continue
            raw_samples.append(sample)
            split_counts[split_name] += 1
            total_frames += int(sample.metadata.get('frameCount') or 0)
            camera_label = str(sample.metadata.get('camera') or 'unknown')
            camera_counts[camera_label] += 1

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
    }
    return ArchiveSource(kind='filesystem', location=str(root)), raw_samples, summary


def _build_ufpr_track_sample(
    dataset_root: Path,
    split_name: str,
    track_dir: Path,
    video_fps: int,
) -> BenchmarkSourceSample | None:
    frame_paths = sorted(track_dir.glob('*.png'), key=lambda path: path.name)
    if not frame_paths:
        return None

    frame_step_ms = max(1, int(round(1000.0 / max(video_fps, 1))))
    frame_entries: list[dict[str, Any]] = []
    plate_votes: Counter[str] = Counter()

    for index, image_path in enumerate(frame_paths):
        image = cv2.imread(str(image_path))
        if image is None:
            continue

        annotation_path = image_path.with_suffix('.txt')
        if not annotation_path.exists():
            continue
        parsed = _parse_ufpr_annotation(annotation_path.read_text(encoding='utf-8', errors='ignore'), image.shape[1], image.shape[0])
        if parsed is None:
            continue

        brightness = _compute_brightness(image)
        blur_score = _compute_blur_score(image, parsed['plate_bbox'])
        plate_area_ratio = _compute_plate_area_ratio(parsed['plate_bbox'], image.shape[1], image.shape[0])
        angle_degrees = parsed['angle_degrees']
        time_ms = index * frame_step_ms
        anchor_score = (
            blur_score
            + (plate_area_ratio * 3200.0)
            - (abs(brightness - 128.0) * 0.15)
            - ((angle_degrees or 0.0) * 1.2)
        )
        frame_member = image_path.relative_to(dataset_root).as_posix()
        plate_votes[parsed['expected_text']] += 1
        frame_entries.append({
            'timeMs': time_ms,
            'frameMember': frame_member,
            'plateBBox': parsed['plate_bbox'],
            'vehicleBBox': parsed['vehicle_bbox'],
            'brightness': brightness,
            'blurScore': blur_score,
            'plateAreaRatio': plate_area_ratio,
            'angleDegrees': angle_degrees,
            'expectedText': parsed['expected_text'],
            'camera': parsed['camera'],
            'vehicleType': parsed['vehicle_type'],
            'make': parsed['make'],
            'model': parsed['model'],
            'year': parsed['year'],
            'charBoxes': parsed['char_boxes'],
            'anchorScore': anchor_score,
        })

    if not frame_entries:
        return None

    expected_text = plate_votes.most_common(1)[0][0]
    anchor_frame = max(frame_entries, key=lambda entry: float(entry['anchorScore']))
    brightness_values = sorted(float(entry['brightness']) for entry in frame_entries)
    blur_values = sorted(float(entry['blurScore']) for entry in frame_entries)
    plate_area_values = sorted(float(entry['plateAreaRatio']) for entry in frame_entries)
    angle_values = sorted(float(entry['angleDegrees']) for entry in frame_entries if entry['angleDegrees'] is not None)
    camera_label = str(anchor_frame['camera'] or 'unknown')
    vehicle_type = str(anchor_frame['vehicleType'] or 'vehicle').lower()
    track_id = track_dir.name

    return BenchmarkSourceSample(
        dataset_key='ufpr-alpr',
        dataset_name='UFPR-ALPR',
        archive_member=track_dir.relative_to(dataset_root).as_posix(),
        expectation_kind='readable',
        expected_text=expected_text,
        bbox=anchor_frame['plateBBox'],
        split=split_name,
        brightness=quantile_float(brightness_values, 0.50),
        blur_score=quantile_float(blur_values, 0.20),
        plate_area_ratio=quantile_float(plate_area_values, 0.20),
        angle_degrees=quantile_float(angle_values, 0.80) if angle_values else None,
        tags=[
            'local-dataset',
            'ufpr-alpr',
            'brazil',
            'moving-camera',
            split_name,
            f'camera-{_slug_token(camera_label)}',
            vehicle_type if vehicle_type in {'car', 'motorcycle', 'truck', 'bus'} else 'vehicle',
        ],
        case_mode='interval',
        target_bbox=anchor_frame['vehicleBBox'],
        anchor_time_ms=int(anchor_frame['timeMs']),
        interval_ms=(int(frame_entries[0]['timeMs']), int(frame_entries[-1]['timeMs'])),
        sample_every_ms=frame_step_ms,
        max_samples=len(frame_entries),
        source_fps=float(video_fps),
        country_hints=['BR'],
        metadata={
            'dataset': 'UFPR-ALPR',
            'trackId': track_id,
            'split': split_name,
            'camera': camera_label,
            'vehicleType': vehicle_type,
            'vehicleMake': anchor_frame['make'],
            'vehicleModel': anchor_frame['model'],
            'vehicleYear': anchor_frame['year'],
            'frameRate': video_fps,
            'frameStepMs': frame_step_ms,
            'frameCount': len(frame_entries),
            'trackFrameMembers': [str(entry['frameMember']) for entry in frame_entries],
            'groundTruthFrames': [
                {
                    'timeMs': int(entry['timeMs']),
                    'frameMember': str(entry['frameMember']),
                    'expectedText': str(entry['expectedText']),
                    'plateBox': {
                        'x1': int(entry['plateBBox'][0]),
                        'y1': int(entry['plateBBox'][1]),
                        'x2': int(entry['plateBBox'][2]),
                        'y2': int(entry['plateBBox'][3]),
                    },
                    'targetBox': {
                        'x1': int(entry['vehicleBBox'][0]),
                        'y1': int(entry['vehicleBBox'][1]),
                        'x2': int(entry['vehicleBBox'][2]),
                        'y2': int(entry['vehicleBBox'][3]),
                    },
                    'charBoxes': entry['charBoxes'],
                }
                for entry in frame_entries
            ],
            'anchorFrame': {
                'timeMs': int(anchor_frame['timeMs']),
                'frameMember': str(anchor_frame['frameMember']),
            },
        },
    )


def _load_uc3m(split: str) -> tuple[ArchiveSource, list[BenchmarkSourceSample], dict[str, Any]]:
    with RemoteZip(UC3M_ARCHIVE_CONTENT_URL) as archive:
        split_members = _read_uc3m_split_members(archive, split)
        image_members = {Path(name).stem: name for name in archive.namelist() if name.lower().endswith('.jpg')}
        json_members = [name for name in archive.namelist() if name.lower().endswith('.json') and f'/{split}/' in name.replace('\\', '/').lower()]

        raw_samples: list[BenchmarkSourceSample] = []
        skipped = 0
        for json_member in json_members:
            annotation = json.loads(archive.read(json_member).decode('utf-8'))
            image_stem = _resolve_uc3m_image_stem(annotation, json_member)
            if image_stem is None or image_stem not in split_members:
                continue
            image_member = image_members.get(image_stem)
            if image_member is None:
                skipped += 1
                continue

            image = _decode_zip_image(archive, image_member)
            if image is None:
                skipped += 1
                continue
            parsed = _parse_uc3m_annotation(annotation, image.shape[1], image.shape[0])
            if parsed is None:
                skipped += 1
                continue
            expected_text, bbox, angle_degrees = parsed
            brightness = _compute_brightness(image)
            blur_score = _compute_blur_score(image, bbox)
            plate_area_ratio = _compute_plate_area_ratio(bbox, image.shape[1], image.shape[0])
            raw_samples.append(BenchmarkSourceSample(
                dataset_key='uc3m-lp',
                dataset_name='UC3M-LP',
                archive_member=image_member,
                expectation_kind='readable',
                expected_text=expected_text,
                bbox=bbox,
                split=_resolve_uc3m_split(image_member),
                brightness=brightness,
                blur_score=blur_score,
                plate_area_ratio=plate_area_ratio,
                angle_degrees=angle_degrees,
                tags=['public-dataset', 'uc3m-lp', 'europe', 'spain'],
                metadata={
                    'dataset': 'UC3M-LP',
                    'annotationMember': json_member,
                    'split': _resolve_uc3m_split(image_member),
                    'bbox': {'x1': bbox[0], 'y1': bbox[1], 'x2': bbox[2], 'y2': bbox[3]},
                    'angleDegrees': angle_degrees,
                    'imageStem': image_stem,
                },
            ))

    thresholds = _build_image_thresholds(raw_samples)
    for sample in raw_samples:
        _add_image_hard_case_tags(sample, thresholds)

    summary = {
        'dataset': 'UC3M-LP',
        'sampleCount': len(raw_samples),
        'skippedSamples': skipped,
        'split': split,
        'thresholds': thresholds,
        'archiveAccess': 'remote-range',
    }
    return ArchiveSource(kind='remote', location=UC3M_ARCHIVE_CONTENT_URL), raw_samples, summary


def _parse_aolp_bbox(raw_text: str, image_width: int, image_height: int) -> tuple[int, int, int, int] | None:
    values = [int(round(float(part))) for part in raw_text.replace(',', ' ').split() if part.strip()]
    if len(values) < 4:
        return None
    x1, x2 = sorted((values[0], values[2]))
    y1, y2 = sorted((values[1], values[3]))
    return _clamp_bbox((x1, y1, x2, y2), image_width, image_height)


def _parse_lp2025_annotations(raw_text: str, image_width: int, image_height: int) -> list[dict[str, Any]]:
    annotations: list[dict[str, Any]] = []
    for label_index, raw_line in enumerate(raw_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 9:
            continue
        raw_label = parts[0]
        try:
            points = [
                (float(parts[index]), float(parts[index + 1]))
                for index in range(1, 9, 2)
            ]
        except ValueError:
            continue

        expectation_kind, expected_text = _parse_lp2025_label_token(raw_label)
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        bbox = _clamp_bbox((int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))), image_width, image_height)
        annotations.append({
            'label_index': label_index,
            'raw_label': raw_label,
            'expectation_kind': expectation_kind,
            'expected_text': expected_text,
            'bbox': bbox,
            'angle_degrees': _polygon_tilt_degrees(points),
        })
    return annotations


def _parse_lp2025_label_token(raw_label: str) -> tuple[str, str | None]:
    normalized_label = raw_label.strip()
    if not normalized_label:
        return 'unreadable', None

    upper_label = normalized_label.upper()
    if upper_label in {'_', 'NONE', 'NULL', 'N/A', 'NA'}:
        return 'unreadable', None

    expected_text = normalize_expected_text(normalized_label)
    if not expected_text:
        return 'unreadable', None
    return 'readable', expected_text


def _parse_ufpr_annotation(raw_text: str, image_width: int, image_height: int) -> dict[str, Any] | None:
    camera = ''
    vehicle_bbox: tuple[int, int, int, int] | None = None
    vehicle_type = 'vehicle'
    make = ''
    model = ''
    year = ''
    expected_text = ''
    corner_points: list[tuple[float, float]] = []
    char_boxes: list[dict[str, int]] = []

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith('camera:'):
            camera = line.split(':', 1)[1].strip()
            continue
        if line.startswith('position_vehicle:'):
            values = [int(part) for part in line.split(':', 1)[1].replace(',', ' ').split() if part.strip()]
            if len(values) >= 4:
                x, y, width, height = values[:4]
                vehicle_bbox = _clamp_bbox((x, y, x + width, y + height), image_width, image_height)
            continue
        if line.startswith('type:'):
            vehicle_type = line.split(':', 1)[1].strip().lower() or 'vehicle'
            continue
        if line.startswith('make:'):
            make = line.split(':', 1)[1].strip()
            continue
        if line.startswith('model:'):
            model = line.split(':', 1)[1].strip()
            continue
        if line.startswith('year:'):
            year = line.split(':', 1)[1].strip()
            continue
        if line.startswith('plate:'):
            expected_text = normalize_expected_text(line.split(':', 1)[1].strip())
            continue
        if line.startswith('corners:'):
            for token in line.split(':', 1)[1].split():
                if ',' not in token:
                    continue
                x_value, y_value = token.split(',', 1)
                try:
                    corner_points.append((float(x_value), float(y_value)))
                except ValueError:
                    continue
            continue
        if line.lower().startswith('char '):
            values = [int(part) for part in line.split(':', 1)[1].replace(',', ' ').split() if part.strip()]
            if len(values) >= 4:
                x, y, width, height = values[:4]
                char_boxes.append({'x': x, 'y': y, 'width': width, 'height': height})

    if vehicle_bbox is None or not expected_text or not corner_points:
        return None

    xs = [point[0] for point in corner_points]
    ys = [point[1] for point in corner_points]
    plate_bbox = _clamp_bbox((int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))), image_width, image_height)
    return {
        'camera': camera,
        'vehicle_bbox': vehicle_bbox,
        'vehicle_type': vehicle_type,
        'make': make,
        'model': model,
        'year': year,
        'expected_text': expected_text,
        'plate_bbox': plate_bbox,
        'angle_degrees': _polygon_tilt_degrees(corner_points),
        'char_boxes': char_boxes,
    }


def _build_image_thresholds(samples: list[BenchmarkSourceSample]) -> dict[str, float]:
    brightness = sorted(sample.brightness for sample in samples)
    blur_score = sorted(sample.blur_score for sample in samples)
    plate_area_ratio = sorted(sample.plate_area_ratio for sample in samples if sample.plate_area_ratio is not None)
    angles = sorted(sample.angle_degrees for sample in samples if sample.angle_degrees is not None)
    return {
        'lowBrightness': quantile_float(brightness, 0.15),
        'highBrightness': quantile_float(brightness, 0.85),
        'lowBlurScore': quantile_float(blur_score, 0.15),
        'smallPlateRatio': quantile_float(plate_area_ratio, 0.15) if plate_area_ratio else 0.0,
        'angleDegrees': quantile_float(angles, 0.75) if angles else 12.0,
    }


def _add_image_hard_case_tags(sample: BenchmarkSourceSample, thresholds: dict[str, float]) -> None:
    if sample.blur_score <= thresholds['lowBlurScore']:
        sample.tags.append('blur')
    if sample.plate_area_ratio is not None and sample.plate_area_ratio <= thresholds['smallPlateRatio']:
        sample.tags.append('small-plate')
    if sample.brightness <= thresholds['lowBrightness']:
        sample.tags.append('low-light')
    if sample.brightness >= thresholds['highBrightness']:
        sample.tags.append('high-exposure')
    if sample.angle_degrees is not None and sample.angle_degrees >= thresholds['angleDegrees']:
        sample.tags.append('angle')
    if sum(1 for category in ['blur', 'angle', 'small-plate', 'low-light', 'high-exposure', 'weather'] if category in sample.tags) >= 2:
        sample.tags.append('challenge')
    sample.tags = sorted(set(sample.tags))


def _slug_token(value: str) -> str:
    normalized = ''.join(character.lower() if character.isalnum() else '-' for character in value).strip('-')
    return normalized or 'unknown'


def _resolve_uc3m_image_stem(annotation: dict[str, Any], json_member: str) -> str | None:
    image_path = annotation.get('imagePath')
    if isinstance(image_path, str) and image_path.strip():
        return Path(image_path).stem
    return Path(json_member).stem


def _read_uc3m_split_members(archive: Any, split: str) -> set[str]:
    wanted = ['train', 'test'] if split == 'all' else [split]
    stems: set[str] = set()
    archive_names = archive.namelist()
    for split_name in wanted:
        manifest_name = next(
            (name for name in archive_names if name.lower().endswith(f'/{split_name}.txt') or name.lower() == f'{split_name}.txt'),
            None,
        )
        if manifest_name is None:
            continue
        content = archive.read(manifest_name).decode('utf-8').splitlines()
        for line in content:
            normalized = line.strip().replace('\\', '/').replace('.jpg', '').replace('.json', '')
            if not normalized:
                continue
            stems.add(Path(normalized).stem)
    return stems


def _resolve_uc3m_split(member_name: str) -> str:
    parts = Path(member_name).parts
    for part in parts:
        lowered = part.lower()
        if lowered in {'train', 'test'}:
            return lowered
    return 'unknown'


def _decode_zip_image(archive: Any, member_name: str) -> Any | None:
    buffer = np.frombuffer(archive.read(member_name), dtype=np.uint8)
    return cv2.imdecode(buffer, cv2.IMREAD_COLOR)


def _parse_uc3m_annotation(annotation: dict[str, Any], image_width: int, image_height: int) -> tuple[str, tuple[int, int, int, int], float | None] | None:
    direct_parse = _parse_uc3m_lps_annotation(annotation, image_width, image_height)
    if direct_parse is not None:
        return direct_parse

    expected_text = _find_plate_text(annotation)
    bbox, angle_degrees = _find_plate_bbox(annotation, image_width, image_height)
    if not expected_text or bbox is None:
        return None
    return expected_text, bbox, angle_degrees


def _parse_uc3m_lps_annotation(annotation: dict[str, Any], image_width: int, image_height: int) -> tuple[str, tuple[int, int, int, int], float | None] | None:
    lps = annotation.get('lps')
    if not isinstance(lps, list) or not lps:
        return None

    candidates: list[tuple[int, str, tuple[int, int, int, int], float | None]] = []
    for plate in lps:
        if not isinstance(plate, dict):
            continue
        raw_text = plate.get('lp_id')
        normalized_text = normalize_expected_text(str(raw_text)) if raw_text is not None else ''
        if not normalized_text or not PLATE_TEXT_PATTERN.match(normalized_text):
            continue
        bbox, angle_degrees = _bbox_from_annotation(plate, image_width, image_height)
        if bbox is None:
            continue
        candidates.append((_bbox_area(bbox), normalized_text, bbox, angle_degrees))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    _, normalized_text, bbox, angle_degrees = candidates[0]
    return normalized_text, bbox, angle_degrees


def _find_plate_text(value: Any) -> str | None:
    candidates: list[tuple[int, str]] = []
    for item in _iter_objects(value):
        if not isinstance(item, dict):
            continue
        for key, raw_value in item.items():
            if not isinstance(raw_value, str):
                continue
            lowered_key = key.lower()
            if lowered_key in {'imagepath', 'image_path', 'filename', 'file_name', 'path'}:
                continue
            normalized = normalize_expected_text(raw_value)
            if not normalized or not PLATE_TEXT_PATTERN.match(normalized):
                continue
            priority = 1
            if lowered_key in {'lp_id', 'text', 'plate', 'plate_text', 'platetext', 'license_plate', 'licenseplate', 'ocr'}:
                priority = 4
            elif lowered_key in {'value', 'description', 'label'}:
                priority = 2
            candidates.append((priority, normalized))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
    return candidates[0][1]


def _find_plate_bbox(value: Any, image_width: int, image_height: int) -> tuple[tuple[int, int, int, int] | None, float | None]:
    candidates: list[tuple[int, tuple[int, int, int, int], float | None]] = []
    for item in _iter_objects(value):
        if not isinstance(item, dict):
            continue
        label_text = ' '.join(str(item.get(key, '')) for key in ('label', 'name', 'category', 'class', 'type')).lower()
        priority = 3 if any(token in label_text for token in ('plate', 'license', 'lp')) else 1
        bbox, angle_degrees = _bbox_from_annotation(item, image_width, image_height)
        if bbox is None:
            continue
        candidates.append((priority, bbox, angle_degrees))
    if not candidates:
        return None, None
    candidates.sort(key=lambda item: (item[0], _bbox_area(item[1])), reverse=True)
    _, bbox, angle_degrees = candidates[0]
    return bbox, angle_degrees


def _bbox_from_annotation(value: dict[str, Any], image_width: int, image_height: int) -> tuple[tuple[int, int, int, int] | None, float | None]:
    points = value.get('points') or value.get('poly_coord') or value.get('polygon') or value.get('vertices')
    if isinstance(points, list) and points:
        flattened: list[tuple[float, float]] = []
        for point in points:
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                try:
                    flattened.append((float(point[0]), float(point[1])))
                except (TypeError, ValueError):
                    continue
        if len(flattened) >= 2:
            xs = [point[0] for point in flattened]
            ys = [point[1] for point in flattened]
            bbox = _clamp_bbox((int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))), image_width, image_height)
            angle_degrees = None
            if len(flattened) >= 4:
                angle_degrees = _polygon_tilt_degrees(flattened)
            return bbox, angle_degrees

    if all(key in value for key in ('x', 'y', 'width', 'height')):
        try:
            x = int(float(value['x']))
            y = int(float(value['y']))
            width = int(float(value['width']))
            height = int(float(value['height']))
        except (TypeError, ValueError):
            return None, None
        return _clamp_bbox((x, y, x + width, y + height), image_width, image_height), None

    if all(key in value for key in ('x1', 'y1', 'x2', 'y2')):
        try:
            bbox = tuple(int(float(value[key])) for key in ('x1', 'y1', 'x2', 'y2'))
        except (TypeError, ValueError):
            return None, None
        return _clamp_bbox(bbox, image_width, image_height), None

    raw_bbox = value.get('bbox')
    if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) >= 4:
        try:
            x1, y1, x2, y2 = (int(float(raw_bbox[index])) for index in range(4))
        except (TypeError, ValueError):
            return None, None
        if x2 <= x1 or y2 <= y1:
            x1, y1, width, height = (int(float(raw_bbox[index])) for index in range(4))
            return _clamp_bbox((x1, y1, x1 + width, y1 + height), image_width, image_height), None
        return _clamp_bbox((x1, y1, x2, y2), image_width, image_height), None

    return None, None


def _iter_objects(value: Any) -> Iterable[Any]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _iter_objects(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_objects(nested)


def _compute_brightness(image: Any) -> float:
    grayscale = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(np.mean(grayscale))


def _compute_blur_score(image: Any, bbox: tuple[int, int, int, int]) -> float:
    crop = image[bbox[1]:bbox[3], bbox[0]:bbox[2]] if bbox else image
    if crop is None or getattr(crop, 'size', 0) == 0:
        crop = image
    grayscale = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(grayscale, cv2.CV_64F).var())


def _compute_plate_area_ratio(bbox: tuple[int, int, int, int], image_width: int, image_height: int) -> float:
    plate_area = max(0, bbox[2] - bbox[0]) * max(0, bbox[3] - bbox[1])
    image_area = max(image_width * image_height, 1)
    return float(plate_area / image_area)


def _clamp_bbox(bbox: tuple[int, int, int, int], image_width: int, image_height: int) -> tuple[int, int, int, int]:
    x1 = max(0, min(bbox[0], image_width - 1))
    y1 = max(0, min(bbox[1], image_height - 1))
    x2 = max(x1 + 1, min(bbox[2], image_width))
    y2 = max(y1 + 1, min(bbox[3], image_height))
    return x1, y1, x2, y2


def _bbox_area(bbox: tuple[int, int, int, int]) -> int:
    return max(0, bbox[2] - bbox[0]) * max(0, bbox[3] - bbox[1])


def _polygon_tilt_degrees(points: list[tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0

    longest_edge: tuple[tuple[float, float], tuple[float, float]] | None = None
    longest_edge_length = -1.0
    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        edge_length = (dx * dx) + (dy * dy)
        if edge_length > longest_edge_length:
            longest_edge_length = edge_length
            longest_edge = (start, end)

    if longest_edge is None:
        return 0.0

    (x1, y1), (x2, y2) = longest_edge
    radians = np.arctan2(y2 - y1, x2 - x1)
    degrees = abs(float(np.degrees(radians)))
    if degrees > 90.0:
        degrees = 180.0 - degrees
    return min(degrees, 90.0 - degrees)


def _build_ccpd_thresholds(samples: list[Any]) -> dict[str, int]:
    brightness = sorted(sample.brightness for sample in samples)
    blur = sorted(sample.blur for sample in samples)
    return {
        'lowBrightness': quantile(brightness, 0.10),
        'highBrightness': quantile(brightness, 0.90),
        'highBlur': quantile(blur, 0.90),
    }


def _build_uc3m_thresholds(samples: list[BenchmarkSourceSample]) -> dict[str, float]:
    brightness = sorted(sample.brightness for sample in samples)
    blur_score = sorted(sample.blur_score for sample in samples)
    plate_area_ratio = sorted(sample.plate_area_ratio for sample in samples if sample.plate_area_ratio is not None)
    angles = sorted(sample.angle_degrees for sample in samples if sample.angle_degrees is not None)
    return {
        'lowBrightness': quantile_float(brightness, 0.15),
        'highBrightness': quantile_float(brightness, 0.85),
        'lowBlurScore': quantile_float(blur_score, 0.15),
        'smallPlateRatio': quantile_float(plate_area_ratio, 0.15) if plate_area_ratio else 0.0,
        'angleDegrees': quantile_float(angles, 0.75) if angles else 12.0,
    }


def _select_balanced_samples(samples: list[BenchmarkSourceSample], per_category: int, seed: int) -> dict[str, list[BenchmarkSourceSample]]:
    rng = random.Random(seed)
    used_names: set[str] = set()
    selected: dict[str, list[BenchmarkSourceSample]] = {}

    for category in HARD_CASE_CATEGORIES:
        buckets: dict[str, list[BenchmarkSourceSample]] = defaultdict(list)
        for sample in samples:
            if category in sample.tags:
                buckets[sample.dataset_key].append(sample)
        for entries in buckets.values():
            rng.shuffle(entries)

        picked: list[BenchmarkSourceSample] = []
        source_order = sorted(buckets)
        while len(picked) < per_category and any(buckets.values()):
            progressed = False
            for dataset_key in source_order:
                pool = buckets[dataset_key]
                while pool and pool[0].unique_name in used_names:
                    pool.pop(0)
                if not pool:
                    continue
                sample = pool.pop(0)
                picked.append(sample)
                used_names.add(sample.unique_name)
                progressed = True
                if len(picked) >= per_category:
                    break
            if not progressed:
                break
        selected[category] = picked
    return selected


def _materialize_manifest(
    archive_sources: dict[str, ArchiveSource],
    selected: dict[str, list[BenchmarkSourceSample]],
    output_images: Path,
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    output_images.mkdir(parents=True, exist_ok=True)
    category_counts: dict[str, int] = {}
    dataset_counts: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()

    archives = {key: _open_archive(source) for key, source in archive_sources.items()}
    try:
        for category, samples in selected.items():
            category_counts[category] = len(samples)
            for index, sample in enumerate(samples, start=1):
                materialized = _materialize_source_asset(sample, archives[sample.dataset_key], output_images)
                if materialized is None:
                    continue
                destination, width, height = materialized
                dataset_counts[sample.dataset_key] += 1
                split_counts[sample.split] += 1
                case_tags = sorted(set(sample.tags + [category]))
                hardness = sample.hardness_score()
                metadata = dict(sample.metadata)
                metadata.setdefault('split', sample.split)
                metadata.update({'dominantCategory': category, 'hardnessScore': hardness, 'sourceMode': sample.case_mode, 'expectationKind': sample.expectation_kind})
                case_payload: dict[str, Any] = {
                    'id': f'{sample.dataset_key}-{category}-{index:03d}',
                    'sourcePath': destination.resolve().as_posix(),
                    'mode': sample.case_mode,
                    'timeMs': sample.anchor_time_ms or 0,
                    'markerRect': build_marker_rect(sample.bbox, width, height),
                    'targetVehicleKind': str(metadata.get('vehicleType') or 'vehicle'),
                    'selectedTargetBox': build_marker_rect(sample.target_bbox, width, height),
                    'countryHints': sample.country_hints or _default_country_hints(sample.dataset_key),
                    'tags': case_tags,
                    'metadata': metadata,
                }
                if sample.expectation_kind == 'unreadable':
                    case_payload['expectation'] = {'kind': 'unreadable'}
                elif sample.expected_text:
                    case_payload['expectedText'] = sample.expected_text
                ground_truth_plate_box = build_marker_rect(sample.bbox, width, height)
                if ground_truth_plate_box is not None:
                    case_payload['groundTruthPlateBox'] = ground_truth_plate_box
                ground_truth_target_box = build_marker_rect(sample.target_bbox, width, height)
                if ground_truth_target_box is not None:
                    case_payload['groundTruthTargetBox'] = ground_truth_target_box

                if sample.case_mode == 'interval':
                    interval_start, interval_end = sample.interval_ms or (0, 0)
                    case_payload.update({
                        'interval': {'startMs': interval_start, 'endMs': interval_end},
                        'anchorTimeMs': sample.anchor_time_ms or interval_start,
                        'sampleEveryMs': sample.sample_every_ms,
                        'maxSamples': sample.max_samples,
                        'analysisOptions': default_interval_analysis_options(),
                    })
                    ground_truth_frames = _build_ground_truth_frames(metadata.get('groundTruthFrames'), width, height)
                    if ground_truth_frames:
                        case_payload['groundTruthFrames'] = ground_truth_frames
                else:
                    case_payload.update({
                        'timeMs': 0,
                        'targetVehicleKind': 'vehicle',
                        'selectedTargetBox': None,
                        'analysisOptions': default_frame_analysis_options(),
                    })

                cases.append(case_payload)
    finally:
        for archive in archives.values():
            archive.close()

    return {
        'summary': {
            'datasets': sorted(dataset_counts),
            'caseCount': len(cases),
            'categoryCounts': category_counts,
            'datasetCounts': dict(dataset_counts),
            'splitCounts': dict(split_counts),
        },
        'cases': cases,
    }


def _materialize_source_asset(
    sample: BenchmarkSourceSample,
    archive: Any,
    output_images: Path,
) -> tuple[Path, int, int] | None:
    if sample.case_mode == 'interval':
        return _materialize_interval_source(sample, archive, output_images)
    return _materialize_frame_source(sample, archive, output_images)


def _materialize_frame_source(
    sample: BenchmarkSourceSample,
    archive: Any,
    output_images: Path,
) -> tuple[Path, int, int] | None:
    relative_member = Path(sample.archive_member)
    destination = output_images / sample.dataset_key / relative_member
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        destination.write_bytes(archive.read(sample.archive_member))

    image = cv2.imread(str(destination))
    if image is None:
        return None
    height, width = image.shape[:2]
    return destination, width, height


def _materialize_interval_source(
    sample: BenchmarkSourceSample,
    archive: Any,
    output_images: Path,
) -> tuple[Path, int, int] | None:
    frame_members = [str(member) for member in (sample.metadata.get('trackFrameMembers') or []) if member]
    if not frame_members:
        return None

    first_frame = _decode_archive_image(archive, frame_members[0])
    if first_frame is None:
        return None
    height, width = first_frame.shape[:2]

    track_id = str(sample.metadata.get('trackId') or Path(sample.archive_member).name)
    output_root = output_images / sample.dataset_key / 'tracks'
    output_root.mkdir(parents=True, exist_ok=True)
    mp4_path = output_root / f'{_slug_token(track_id)}.mp4'
    avi_path = output_root / f'{_slug_token(track_id)}.avi'
    destination = mp4_path if mp4_path.exists() or not avi_path.exists() else avi_path
    if not destination.exists():
        materialized_path = _write_interval_video(archive, frame_members, output_root, track_id, sample.source_fps or 10.0)
        if materialized_path is None:
            return None
        destination = materialized_path

    return destination, width, height


def _write_interval_video(
    archive: Any,
    frame_members: list[str],
    output_root: Path,
    track_id: str,
    fps: float,
) -> Path | None:
    if not frame_members:
        return None

    first_frame = _decode_archive_image(archive, frame_members[0])
    if first_frame is None:
        return None

    frame_height, frame_width = first_frame.shape[:2]
    stem = _slug_token(track_id)
    for extension, codec in (('mp4', 'mp4v'), ('avi', 'MJPG')):
        destination = output_root / f'{stem}.{extension}'
        writer = cv2.VideoWriter(
            str(destination),
            cv2.VideoWriter_fourcc(*codec),
            float(max(fps, 1.0)),
            (frame_width, frame_height),
        )
        if not writer.isOpened():
            writer.release()
            continue

        try:
            writer.write(first_frame)
            for frame_member in frame_members[1:]:
                frame = _decode_archive_image(archive, frame_member)
                if frame is None:
                    continue
                if frame.shape[1] != frame_width or frame.shape[0] != frame_height:
                    frame = cv2.resize(frame, (frame_width, frame_height), interpolation=cv2.INTER_LANCZOS4)
                writer.write(frame)
        finally:
            writer.release()

        if destination.exists() and destination.stat().st_size > 0:
            return destination

    return None


def _decode_archive_image(archive: Any, member_name: str) -> Any | None:
    buffer = np.frombuffer(archive.read(member_name), dtype=np.uint8)
    return cv2.imdecode(buffer, cv2.IMREAD_COLOR)


def _default_country_hints(dataset_key: str) -> list[str]:
    if dataset_key == 'aolp':
        return ['TW']
    if dataset_key == 'lp2025':
        return ['TW']
    if dataset_key == 'uc3m-lp':
        return ['ES', 'EU']
    if dataset_key == 'ufpr-alpr':
        return ['BR']
    return []


def _build_ground_truth_frames(entries: Any, width: int, height: int) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    if not isinstance(entries, list):
        return frames

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        frame_payload: dict[str, Any] = {
            'timeMs': int(entry.get('timeMs') or 0),
        }

        plate_bbox = _bbox_from_mapping(entry.get('plateBox'))
        target_bbox = _bbox_from_mapping(entry.get('targetBox'))
        if plate_bbox is not None:
            frame_payload['plateBox'] = build_marker_rect(plate_bbox, width, height)
        if target_bbox is not None:
            frame_payload['targetBox'] = build_marker_rect(target_bbox, width, height)
        frames.append(frame_payload)
    return frames


def _bbox_from_mapping(value: Any) -> tuple[int, int, int, int] | None:
    if not isinstance(value, dict):
        return None
    required_keys = ('x1', 'y1', 'x2', 'y2')
    if not all(key in value for key in required_keys):
        return None
    try:
        return tuple(int(value[key]) for key in required_keys)
    except (TypeError, ValueError):
        return None


def _open_archive(source: ArchiveSource) -> Any:
    if source.kind == 'local':
        return ZipFile(source.location)
    if source.kind == 'remote':
        return RemoteZip(source.location)
    if source.kind == 'filesystem':
        return DirectoryArchive(source.location)
    raise ValueError(f'Unsupported archive source kind: {source.kind}')


def _build_split_manifests(manifest: dict[str, Any], split_output_dir: Path, seed: int) -> dict[str, str]:
    split_output_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for case in manifest['cases']:
        dataset = str(case['metadata'].get('dataset', 'unknown'))
        category = str(case['metadata'].get('dominantCategory', 'challenge'))
        groups[(dataset, category)].append(case)

    splits = {'development': [], 'holdout': [], 'challenge': []}
    for cases in groups.values():
        rng.shuffle(cases)
        cases.sort(key=lambda case: float(case['metadata'].get('hardnessScore', 0.0)), reverse=True)
        challenge_count = max(1, len(cases) // 4) if len(cases) >= 3 else 0
        holdout_count = max(1, len(cases) // 5) if len(cases) >= 5 else 0
        challenge_cases = cases[:challenge_count]
        holdout_cases = cases[challenge_count:challenge_count + holdout_count]
        development_cases = cases[challenge_count + holdout_count:]
        splits['challenge'].extend(challenge_cases)
        splits['holdout'].extend(holdout_cases)
        splits['development'].extend(development_cases)

    outputs: dict[str, str] = {}
    for split_name, cases in splits.items():
        split_manifest = {
            'summary': {
                **manifest['summary'],
                'split': split_name,
                'caseCount': len(cases),
            },
            'cases': cases,
        }
        output_path = split_output_dir / f'{split_name}.json'
        output_path.write_text(json.dumps(split_manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        outputs[split_name] = str(output_path)
    return outputs


if __name__ == '__main__':
    raise SystemExit(main())