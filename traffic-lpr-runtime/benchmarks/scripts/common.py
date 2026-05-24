from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


RUNTIME_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if str(RUNTIME_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_PACKAGE_ROOT))

from traffic_lpr_runtime.infrastructure.runtime_layout import benchmark_workspace_root


CCPD_REPO_ID = 'zenitsu09/ccpd-subset-30k'
CCPD_ARCHIVE_NAME = 'ccpd_subset_30k.zip'
UC3M_ARCHIVE_CONTENT_URL = 'https://zenodo.org/api/records/17152029/files/UC3M-LP.zip/content'
PROVINCES = [
    '皖', '沪', '津', '渝', '冀', '晋', '蒙', '辽', '吉', '黑', '苏', '浙', '京', '闽', '赣', '鲁', '豫', '鄂', '湘', '粤', '桂', '琼', '川', '贵', '云', '藏', '陕', '甘', '青', '宁', '新', '警', '学', 'O'
]
ALPHABETS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K', 'L', 'M', 'N', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z', 'O']
ADS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K', 'L', 'M', 'N', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'O']
HARD_CASE_CATEGORIES = ['blur', 'angle', 'challenge', 'small-plate', 'weather', 'low-light', 'high-exposure']
PLATE_TEXT_PATTERN = re.compile(r'^[A-Z0-9]{5,8}$')


@dataclass(frozen=True, slots=True)
class BenchmarkPaths:
    runtime_root: Path
    benchmark_root: Path
    script_root: Path
    manifest_root: Path
    template_root: Path
    public_manifest_root: Path
    public_multisource_manifest_root: Path
    local_manifest_root: Path
    runtime_benchmark_root: Path
    cache_root: Path
    dataset_root: Path


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
    case_mode: str = 'frame'
    target_bbox: tuple[int, int, int, int] | None = None
    anchor_time_ms: int | None = None
    interval_ms: tuple[int, int] | None = None
    sample_every_ms: int | None = None
    max_samples: int | None = None
    source_fps: float | None = None
    country_hints: list[str] = field(default_factory=list)
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


def resolve_benchmark_paths(runtime_root: Path) -> BenchmarkPaths:
    benchmark_root = runtime_root / 'benchmarks'
    manifest_root = benchmark_root / 'manifests'
    runtime_benchmark_root = benchmark_workspace_root(runtime_root)
    return BenchmarkPaths(
        runtime_root=runtime_root,
        benchmark_root=benchmark_root,
        script_root=benchmark_root / 'scripts',
        manifest_root=manifest_root,
        template_root=manifest_root / 'templates',
        public_manifest_root=manifest_root / 'public',
        public_multisource_manifest_root=manifest_root / 'public' / 'multisource',
        local_manifest_root=runtime_benchmark_root / 'manifests' / 'local',
        runtime_benchmark_root=runtime_benchmark_root,
        cache_root=runtime_benchmark_root / 'cache',
        dataset_root=runtime_benchmark_root / 'datasets',
    )


def default_frame_analysis_options() -> dict[str, Any]:
    return {
        'persistArtifacts': False,
        'trackerMode': 'legacy',
        'fusionMode': 'aligned-char',
        'restorationMode': 'mambairv2',
        'enableRectification': True,
        'enableEnhancement': True,
        'enableRecognizerComparison': True,
    }


def default_interval_analysis_options() -> dict[str, Any]:
    return {
        'persistArtifacts': False,
        'trackerMode': 'botsort',
        'fusionMode': 'aligned-char',
        'restorationMode': 'mambairv2',
        'enableRectification': True,
        'enableEnhancement': True,
        'enableRecognizerComparison': True,
    }


def build_marker_rect(bbox: tuple[int, int, int, int] | None, width: int, height: int) -> dict[str, float] | None:
    if bbox is None:
        return None
    x1, y1, x2, y2 = bbox
    return {
        'x': max(0.0, min(x1 / max(width, 1), 1.0)),
        'y': max(0.0, min(y1 / max(height, 1), 1.0)),
        'width': max(0.0, min((x2 - x1) / max(width, 1), 1.0)),
        'height': max(0.0, min((y2 - y1) / max(height, 1), 1.0)),
    }


class DirectoryArchive:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def read(self, member_name: str) -> bytes:
        return (self._root / member_name).read_bytes()

    def close(self) -> None:
        return None


def parse_ccpd_name(file_name: str) -> CcpdSample | None:
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

    raw_plate_text = decode_plate_text(plate_indices)
    expected_text = normalize_expected_text(raw_plate_text)
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


def decode_plate_text(indices: list[int]) -> str:
    if len(indices) < 2:
        return ''
    province = PROVINCES[indices[0]] if 0 <= indices[0] < len(PROVINCES) else ''
    alpha = ALPHABETS[indices[1]] if 0 <= indices[1] < len(ALPHABETS) else ''
    suffix = ''.join(ADS[index] for index in indices[2:] if 0 <= index < len(ADS))
    return f'{province}{alpha}{suffix}'


def normalize_expected_text(text: str) -> str:
    return ''.join(character for character in text.upper() if character.isdigit() or ('A' <= character <= 'Z'))


def quantile(values: list[int], probability: float) -> int:
    index = int((len(values) - 1) * probability)
    return int(values[index])


def quantile_float(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    index = int((len(values) - 1) * probability)
    return float(values[index])