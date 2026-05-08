from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import quantiles
from typing import Any
from zipfile import ZipFile

import cv2
from huggingface_hub import hf_hub_download


CCPD_REPO_ID = 'zenitsu09/ccpd-subset-30k'
CCPD_ARCHIVE_NAME = 'ccpd_subset_30k.zip'
PROVINCES = [
    '皖', '沪', '津', '渝', '冀', '晋', '蒙', '辽', '吉', '黑', '苏', '浙', '京', '闽', '赣', '鲁', '豫', '鄂', '湘', '粤', '桂', '琼', '川', '贵', '云', '藏', '陕', '甘', '青', '宁', '新', '警', '学', 'O'
]
ALPHABETS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K', 'L', 'M', 'N', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z', 'O']
ADS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K', 'L', 'M', 'N', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'O']


@dataclass(frozen=True, slots=True)
class CcpdSample:
    archive_name: str
    subset: str
    x1: int
    y1: int
    x2: int
    y2: int
    expected_text: str
    raw_plate_text: str
    brightness: int
    blur: int


def main() -> int:
    parser = argparse.ArgumentParser(description='Prepare a public hard-case benchmark manifest from the CCPD public subset.')
    parser.add_argument('--per-category', type=int, default=25, help='How many unique cases to keep per hard-case bucket.')
    parser.add_argument('--seed', type=int, default=7, help='Deterministic sampling seed.')
    parser.add_argument('--runtime-root', type=Path, default=Path(__file__).resolve().parents[1], help='traffic-lpr-runtime project root.')
    parser.add_argument('--output-manifest', type=Path, default=None, help='Path for the generated benchmark manifest JSON.')
    parser.add_argument('--output-images', type=Path, default=None, help='Directory where sampled images will be extracted.')
    parser.add_argument('--cache-dir', type=Path, default=None, help='Directory for the downloaded Hugging Face dataset archive.')
    args = parser.parse_args()

    runtime_root = args.runtime_root.resolve()
    cache_dir = (args.cache_dir or (runtime_root / '.runtime' / 'public-datasets' / 'hf-cache')).resolve()
    output_manifest = (args.output_manifest or (runtime_root / 'benchmarks' / 'public-ccpd-hardcases.json')).resolve()
    output_images = (args.output_images or (runtime_root / '.runtime' / 'public-datasets' / 'ccpd-hardcases')).resolve()

    archive_path = Path(
        hf_hub_download(
            repo_id=CCPD_REPO_ID,
            repo_type='dataset',
            filename=CCPD_ARCHIVE_NAME,
            local_dir=cache_dir,
        )
    ).resolve()

    with ZipFile(archive_path) as archive:
        samples = [_parse_ccpd_name(Path(name).name) for name in archive.namelist() if name.lower().endswith('.jpg')]
        samples = [sample for sample in samples if sample is not None]
        thresholds = _build_thresholds(samples)
        selected = _select_samples(samples, per_category=args.per_category, seed=args.seed, thresholds=thresholds)
        manifest = _materialize_manifest(archive, selected, output_images, thresholds)

    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'manifestPath': str(output_manifest), 'imageRoot': str(output_images), 'summary': manifest['summary']}, ensure_ascii=False))
    return 0


def _parse_ccpd_name(file_name: str) -> CcpdSample | None:
    stem = Path(file_name).stem
    parts = stem.split('-')
    if len(parts) < 7:
        return None

    try:
        x1, y1 = (int(value) for value in parts[2].split('_')[0].split(','))
        x2, y2 = (int(value) for value in parts[2].split('_')[1].split(','))
        plate_indices = [int(value) for value in parts[4].split('_')]
        brightness = int(parts[5])
        blur = int(parts[6].split('_', 1)[0])
        subset = stem.rsplit('_', 2)[1]
    except (IndexError, ValueError):
        return None

    raw_plate_text = _decode_plate_text(plate_indices)
    expected_text = _normalize_expected_text(raw_plate_text)
    if not expected_text:
        return None

    return CcpdSample(
        archive_name=file_name,
        subset=subset,
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
        expected_text=expected_text,
        raw_plate_text=raw_plate_text,
        brightness=brightness,
        blur=blur,
    )


def _decode_plate_text(indices: list[int]) -> str:
    if len(indices) < 2:
        return ''
    province = PROVINCES[indices[0]] if 0 <= indices[0] < len(PROVINCES) else ''
    alpha = ALPHABETS[indices[1]] if 0 <= indices[1] < len(ALPHABETS) else ''
    suffix = ''.join(ADS[index] for index in indices[2:] if 0 <= index < len(ADS))
    return f'{province}{alpha}{suffix}'


def _normalize_expected_text(text: str) -> str:
    return ''.join(character for character in text.upper() if character.isdigit() or ('A' <= character <= 'Z'))


def _build_thresholds(samples: list[CcpdSample]) -> dict[str, int]:
    brightness = sorted(sample.brightness for sample in samples)
    blur = sorted(sample.blur for sample in samples)
    return {
        'lowBrightness': _quantile(brightness, 0.10),
        'highBrightness': _quantile(brightness, 0.90),
        'highBlur': _quantile(blur, 0.90),
    }


def _quantile(values: list[int], probability: float) -> int:
    index = int((len(values) - 1) * probability)
    return int(values[index])


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
            marker_rect = {
                'x': max(0.0, min(sample.x1 / max(width, 1), 1.0)),
                'y': max(0.0, min(sample.y1 / max(height, 1), 1.0)),
                'width': max(0.0, min((sample.x2 - sample.x1) / max(width, 1), 1.0)),
                'height': max(0.0, min((sample.y2 - sample.y1) / max(height, 1), 1.0)),
            }
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
                    'markerRect': marker_rect,
                    'targetVehicleKind': 'vehicle',
                    'selectedTargetBox': None,
                    'countryHints': [],
                    'expectedText': sample.expected_text,
                    'tags': sorted(set(case_tags)),
                    'analysisOptions': {
                        'persistArtifacts': False,
                        'trackerMode': 'legacy',
                        'fusionMode': 'aligned-char',
                        'restorationMode': 'mambairv2',
                        'enableRectification': True,
                        'enableEnhancement': True,
                        'enableRecognizerComparison': True,
                    },
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