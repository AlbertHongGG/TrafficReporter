from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from zipfile import ZipFile

import cv2
import numpy as np
from huggingface_hub import hf_hub_download
from remotezip import RemoteZip


CCPD_REPO_ID = 'zenitsu09/ccpd-subset-30k'
CCPD_ARCHIVE_NAME = 'ccpd_subset_30k.zip'
UC3M_ARCHIVE_CONTENT_URL = 'https://zenodo.org/api/records/17152029/files/UC3M-LP.zip/content'
PROVINCES = [
    '皖', '沪', '津', '渝', '冀', '晋', '蒙', '辽', '吉', '黑', '苏', '浙', '京', '闽', '赣', '鲁', '豫', '鄂', '湘', '粤', '桂', '琼', '川', '贵', '云', '藏', '陕', '甘', '青', '宁', '新', '警', '学', 'O'
]
ALPHABETS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K', 'L', 'M', 'N', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z', 'O']
ADS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K', 'L', 'M', 'N', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'O']
PLATE_TEXT_PATTERN = re.compile(r'^[A-Z0-9]{5,8}$')
HARD_CASE_CATEGORIES = ['blur', 'angle', 'challenge', 'small-plate', 'weather', 'low-light', 'high-exposure']


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


@dataclass(frozen=True, slots=True)
class ArchiveSource:
    kind: str
    location: str


@dataclass(slots=True)
class BenchmarkSourceSample:
    dataset_key: str
    dataset_name: str
    archive_member: str
    expected_text: str
    bbox: tuple[int, int, int, int] | None
    split: str
    brightness: float
    blur_score: float
    plate_area_ratio: float | None
    angle_degrees: float | None
    tags: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def unique_name(self) -> str:
        return f'{self.dataset_key}:{self.archive_member}'

    def dominant_category(self) -> str:
        for category in HARD_CASE_CATEGORIES:
          if category in self.tags:
              return category
        return 'challenge'

    def hardness_score(self) -> float:
        score = 0.0
        if 'blur' in self.tags:
            score += 0.25
        if 'angle' in self.tags:
            score += 0.2
        if 'small-plate' in self.tags:
            score += 0.2
        if 'low-light' in self.tags or 'high-exposure' in self.tags:
            score += 0.15
        if 'weather' in self.tags:
            score += 0.15
        if 'challenge' in self.tags:
            score += 0.2
        return score


def main() -> int:
    parser = argparse.ArgumentParser(description='Prepare multi-source public hard-case benchmark manifests from CCPD and UC3M-LP.')
    parser.add_argument('--datasets', nargs='+', default=['ccpd', 'uc3m-lp'], choices=['ccpd', 'uc3m-lp'], help='Datasets to include in the generated public benchmark.')
    parser.add_argument('--per-category', type=int, default=20, help='How many unique cases to keep per hard-case category across sources.')
    parser.add_argument('--seed', type=int, default=7, help='Deterministic sampling seed.')
    parser.add_argument('--runtime-root', type=Path, default=Path(__file__).resolve().parents[1], help='traffic-lpr-runtime project root.')
    parser.add_argument('--output-manifest', type=Path, default=None, help='Path for the combined benchmark manifest JSON.')
    parser.add_argument('--output-images', type=Path, default=None, help='Directory where sampled images will be extracted.')
    parser.add_argument('--cache-dir', type=Path, default=None, help='Directory for downloaded dataset archives.')
    parser.add_argument('--split-output-dir', type=Path, default=None, help='Directory for development/holdout/challenge split manifests.')
    parser.add_argument('--uc3m-split', choices=['test', 'train', 'all'], default='test', help='Which UC3M split to sample from.')
    args = parser.parse_args()

    runtime_root = args.runtime_root.resolve()
    cache_dir = (args.cache_dir or (runtime_root / '.runtime' / 'public-datasets')).resolve()
    output_manifest = (args.output_manifest or (runtime_root / 'benchmarks' / 'public-multisource-hardcases.json')).resolve()
    output_images = (args.output_images or (runtime_root / '.runtime' / 'public-datasets' / 'multisource-hardcases')).resolve()
    split_output_dir = (args.split_output_dir or (runtime_root / 'benchmarks' / 'multisource-manifests')).resolve()

    archive_sources: dict[str, ArchiveSource] = {}
    all_samples: list[BenchmarkSourceSample] = []
    summaries: dict[str, Any] = {}

    if 'ccpd' in args.datasets:
        archive_source, samples, summary = _load_ccpd(cache_dir)
        archive_sources['ccpd'] = archive_source
        all_samples.extend(samples)
        summaries['ccpd'] = summary

    if 'uc3m-lp' in args.datasets:
        archive_source, samples, summary = _load_uc3m(args.uc3m_split)
        archive_sources['uc3m-lp'] = archive_source
        all_samples.extend(samples)
        summaries['uc3m-lp'] = summary

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
    }, ensure_ascii=False))
    return 0


def _load_ccpd(cache_dir: Path) -> tuple[ArchiveSource, list[BenchmarkSourceSample], dict[str, Any]]:
    archive_path = Path(
        hf_hub_download(
            repo_id=CCPD_REPO_ID,
            repo_type='dataset',
            filename=CCPD_ARCHIVE_NAME,
            local_dir=cache_dir / 'hf-cache',
        )
    ).resolve()

    with ZipFile(archive_path) as archive:
        parsed = [_parse_ccpd_name(Path(name).name) for name in archive.namelist() if name.lower().endswith('.jpg')]
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

    thresholds = _build_uc3m_thresholds(raw_samples)
    for sample in raw_samples:
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
        if sum(1 for category in ['blur', 'angle', 'small-plate', 'low-light', 'high-exposure'] if category in sample.tags) >= 2:
            sample.tags.append('challenge')
        sample.tags = sorted(set(sample.tags))

    summary = {
        'dataset': 'UC3M-LP',
        'sampleCount': len(raw_samples),
        'skippedSamples': skipped,
        'split': split,
        'thresholds': thresholds,
        'archiveAccess': 'remote-range',
    }
    return ArchiveSource(kind='remote', location=UC3M_ARCHIVE_CONTENT_URL), raw_samples, summary


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
        normalized_text = _normalize_expected_text(str(raw_text)) if raw_text is not None else ''
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
            normalized = _normalize_expected_text(raw_value)
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


def _build_ccpd_thresholds(samples: list[CcpdSample]) -> dict[str, int]:
    brightness = sorted(sample.brightness for sample in samples)
    blur = sorted(sample.blur for sample in samples)
    return {
        'lowBrightness': _quantile(brightness, 0.10),
        'highBrightness': _quantile(brightness, 0.90),
        'highBlur': _quantile(blur, 0.90),
    }


def _build_uc3m_thresholds(samples: list[BenchmarkSourceSample]) -> dict[str, float]:
    brightness = sorted(sample.brightness for sample in samples)
    blur_score = sorted(sample.blur_score for sample in samples)
    plate_area_ratio = sorted(sample.plate_area_ratio for sample in samples if sample.plate_area_ratio is not None)
    angles = sorted(sample.angle_degrees for sample in samples if sample.angle_degrees is not None)
    return {
        'lowBrightness': _quantile_float(brightness, 0.15),
        'highBrightness': _quantile_float(brightness, 0.85),
        'lowBlurScore': _quantile_float(blur_score, 0.15),
        'smallPlateRatio': _quantile_float(plate_area_ratio, 0.15) if plate_area_ratio else 0.0,
        'angleDegrees': _quantile_float(angles, 0.75) if angles else 12.0,
    }


def _quantile(values: list[int], probability: float) -> int:
    index = int((len(values) - 1) * probability)
    return int(values[index])


def _quantile_float(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    index = int((len(values) - 1) * probability)
    return float(values[index])


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
                destination = output_images / sample.dataset_key / Path(sample.archive_member).name
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists():
                    destination.write_bytes(archives[sample.dataset_key].read(sample.archive_member))

                image = cv2.imread(str(destination))
                if image is None:
                    continue
                height, width = image.shape[:2]
                marker_rect = _build_marker_rect(sample.bbox, width, height)
                dataset_counts[sample.dataset_key] += 1
                split_counts[sample.split] += 1
                case_tags = sorted(set(sample.tags + [category]))
                hardness = sample.hardness_score()
                metadata = dict(sample.metadata)
                metadata.update({'dominantCategory': category, 'hardnessScore': hardness})

                cases.append({
                    'id': f'{sample.dataset_key}-{category}-{index:03d}',
                    'mode': 'frame',
                    'sourcePath': destination.resolve().as_posix(),
                    'timeMs': 0,
                    'markerRect': marker_rect,
                    'targetVehicleKind': 'vehicle',
                    'selectedTargetBox': None,
                    'countryHints': ['tw', 'es', 'eu'] if sample.dataset_key == 'uc3m-lp' else [],
                    'expectedText': sample.expected_text,
                    'tags': case_tags,
                    'analysisOptions': {
                        'persistArtifacts': False,
                        'trackerMode': 'legacy',
                        'fusionMode': 'aligned-char',
                        'restorationMode': 'mambairv2',
                        'enableRectification': True,
                        'enableEnhancement': True,
                        'enableRecognizerComparison': True,
                    },
                    'metadata': metadata,
                })
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


def _open_archive(source: ArchiveSource) -> Any:
    if source.kind == 'local':
        return ZipFile(source.location)
    if source.kind == 'remote':
        return RemoteZip(source.location)
    raise ValueError(f'Unsupported archive source kind: {source.kind}')


def _build_marker_rect(bbox: tuple[int, int, int, int] | None, width: int, height: int) -> dict[str, float] | None:
    if bbox is None:
        return None
    x1, y1, x2, y2 = bbox
    return {
        'x': max(0.0, min(x1 / max(width, 1), 1.0)),
        'y': max(0.0, min(y1 / max(height, 1), 1.0)),
        'width': max(0.0, min((x2 - x1) / max(width, 1), 1.0)),
        'height': max(0.0, min((y2 - y1) / max(height, 1), 1.0)),
    }


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
        output_path = split_output_dir / f'public-multisource-{split_name}.json'
        output_path.write_text(json.dumps(split_manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        outputs[split_name] = str(output_path)
    return outputs


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


if __name__ == '__main__':
    raise SystemExit(main())