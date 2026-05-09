from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import cv2
from huggingface_hub import hf_hub_download

from common import (
    CCPD_ARCHIVE_NAME,
    CCPD_REPO_ID,
    CcpdSample,
    build_marker_rect,
    default_frame_analysis_options,
    parse_ccpd_name,
    quantile,
    resolve_benchmark_paths,
)


def main() -> int:
    parser = argparse.ArgumentParser(description='Prepare a public hard-case benchmark manifest from the CCPD public subset.')
    parser.add_argument('--per-category', type=int, default=25, help='How many unique cases to keep per hard-case bucket.')
    parser.add_argument('--seed', type=int, default=7, help='Deterministic sampling seed.')
    parser.add_argument('--runtime-root', type=Path, default=Path(__file__).resolve().parents[2], help='traffic-lpr-runtime project root.')
    parser.add_argument('--output-manifest', type=Path, default=None, help='Path for the generated benchmark manifest JSON.')
    parser.add_argument('--output-images', type=Path, default=None, help='Directory where sampled images will be extracted.')
    parser.add_argument('--cache-dir', type=Path, default=None, help='Directory for the downloaded Hugging Face dataset archive.')
    args = parser.parse_args()

    runtime_root = args.runtime_root.resolve()
    paths = resolve_benchmark_paths(runtime_root)
    cache_dir = (args.cache_dir or (paths.cache_root / 'hf-hub')).resolve()
    output_manifest = (args.output_manifest or (paths.public_manifest_root / 'ccpd-hardcases.json')).resolve()
    output_images = (args.output_images or (paths.dataset_root / 'ccpd-hardcases')).resolve()

    archive_path = Path(
        hf_hub_download(
            repo_id=CCPD_REPO_ID,
            repo_type='dataset',
            filename=CCPD_ARCHIVE_NAME,
            local_dir=cache_dir,
        )
    ).resolve()

    with ZipFile(archive_path) as archive:
        samples = [parse_ccpd_name(Path(name).name) for name in archive.namelist() if name.lower().endswith('.jpg')]
        samples = [sample for sample in samples if sample is not None]
        thresholds = _build_thresholds(samples)
        selected = _select_samples(samples, per_category=args.per_category, seed=args.seed, thresholds=thresholds)
        manifest = _materialize_manifest(archive, selected, output_images, thresholds)

    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'manifestPath': str(output_manifest), 'imageRoot': str(output_images), 'summary': manifest['summary']}, ensure_ascii=False))
    return 0


def _build_thresholds(samples: list[CcpdSample]) -> dict[str, int]:
    brightness = sorted(sample.brightness for sample in samples)
    blur = sorted(sample.blur for sample in samples)
    return {
        'lowBrightness': quantile(brightness, 0.10),
        'highBrightness': quantile(brightness, 0.90),
        'highBlur': quantile(blur, 0.90),
    }


def _select_samples(
    samples: list[CcpdSample],
    per_category: int,
    seed: int,
    thresholds: dict[str, int],
) -> dict[str, list[CcpdSample]]:
    rng = random.Random(seed)
    pools = {
        'blur': [sample for sample in samples if sample.subset == 'blur' or sample.blur >= thresholds['highBlur']],
        'angle': [sample for sample in samples if sample.subset in {'tilt', 'rotate'}],
        'challenge': [sample for sample in samples if sample.subset == 'challenge'],
        'small-plate': [sample for sample in samples if sample.subset == 'fn'],
        'weather': [sample for sample in samples if sample.subset == 'weather'],
        'low-light': [sample for sample in samples if sample.subset == 'db' or sample.brightness <= thresholds['lowBrightness']],
        'high-exposure': [sample for sample in samples if sample.brightness >= thresholds['highBrightness']],
    }

    selected: dict[str, list[CcpdSample]] = {}
    used_names: set[str] = set()
    for category, candidates in pools.items():
        shuffled = candidates[:]
        rng.shuffle(shuffled)
        picked: list[CcpdSample] = []
        for sample in shuffled:
            if sample.archive_name in used_names:
                continue
            picked.append(sample)
            used_names.add(sample.archive_name)
            if len(picked) >= per_category:
                break
        selected[category] = picked
    return selected


def _materialize_manifest(
    archive: ZipFile,
    selected: dict[str, list[CcpdSample]],
    output_images: Path,
    thresholds: dict[str, int],
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    output_images.mkdir(parents=True, exist_ok=True)
    category_counts: dict[str, int] = {}
    subset_counts: Counter[str] = Counter()

    for category, samples in selected.items():
        category_counts[category] = len(samples)
        for index, sample in enumerate(samples, start=1):
            destination = output_images / sample.archive_name
            if not destination.exists():
                destination.write_bytes(archive.read(sample.archive_name))

            frame = cv2.imread(str(destination))
            if frame is None:
                continue
            height, width = frame.shape[:2]
            subset_counts[sample.subset] += 1
            case_tags = ['public-dataset', 'ccpd', category, sample.subset]
            if sample.blur >= thresholds['highBlur']:
                case_tags.append('heavy-blur')
            if sample.brightness <= thresholds['lowBrightness']:
                case_tags.append('low-light')
            if sample.brightness >= thresholds['highBrightness']:
                case_tags.append('high-exposure')
            if sample.subset in {'tilt', 'rotate'}:
                case_tags.append('angle')

            cases.append(
                {
                    'id': f'ccpd-{category}-{index:03d}',
                    'mode': 'frame',
                    'sourcePath': destination.resolve().as_posix(),
                    'timeMs': 0,
                    'markerRect': build_marker_rect((sample.x1, sample.y1, sample.x2, sample.y2), width, height),
                    'targetVehicleKind': 'vehicle',
                    'selectedTargetBox': None,
                    'countryHints': [],
                    'expectedText': sample.expected_text,
                    'tags': sorted(set(case_tags)),
                    'analysisOptions': default_frame_analysis_options(),
                    'metadata': {
                        'dataset': 'CCPD subset 30k',
                        'rawPlateText': sample.raw_plate_text,
                        'subset': sample.subset,
                        'brightness': sample.brightness,
                        'blur': sample.blur,
                        'bbox': {'x1': sample.x1, 'y1': sample.y1, 'x2': sample.x2, 'y2': sample.y2},
                    },
                }
            )

    return {
        'summary': {
            'dataset': 'CCPD subset 30k',
            'caseCount': len(cases),
            'categoryCounts': category_counts,
            'subsetCounts': dict(subset_counts),
            'thresholds': thresholds,
        },
        'cases': cases,
    }


if __name__ == '__main__':
    raise SystemExit(main())