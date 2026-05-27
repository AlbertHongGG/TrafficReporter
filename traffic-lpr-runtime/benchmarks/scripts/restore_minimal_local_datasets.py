from __future__ import annotations

import json
import shutil
from pathlib import Path
from zipfile import ZipFile


def main() -> int:
    repo_root = Path(__file__).resolve().parents[3]
    dataset_root = repo_root / 'datasets'
    manifest_root = repo_root / '.runtime' / 'cache' / 'benchmark' / 'manifests' / 'local' / 'official'

    aolp_manifest = _load_json(manifest_root / 'aolp-readable-ocr' / 'all.json')
    lp2025_manifest = _load_json(manifest_root / 'lp2025-readable-ocr' / 'all.json')
    ufpr_manifest = _load_json(manifest_root / 'ufpr-moving-camera' / 'all.json')

    restored = {
        'aolp': _restore_aolp_minimal(dataset_root, aolp_manifest),
        'lp2025': _restore_lp2025_minimal(dataset_root, lp2025_manifest),
        'ufpr-alpr': _restore_ufpr_minimal(dataset_root, ufpr_manifest),
    }
    print(json.dumps({'datasetRoot': str(dataset_root.resolve()), 'restored': restored}, ensure_ascii=False, indent=2))
    return 0


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding='utf-8'))


def _restore_aolp_minimal(dataset_root: Path, manifest_payload: dict[str, object]) -> dict[str, object]:
    root = dataset_root / 'AOLP'
    if root.exists():
        shutil.rmtree(root)
    materialized_root = dataset_root.parent / '.runtime' / 'cache' / 'benchmark' / 'datasets' / 'official' / 'aolp-readable-ocr' / 'aolp'
    restored_members: list[str] = []
    for case in manifest_payload.get('cases') or []:
        if not isinstance(case, dict):
            continue
        metadata = case.get('metadata')
        if not isinstance(metadata, dict):
            continue
        relative_image_path = metadata.get('relativeImagePath')
        if not isinstance(relative_image_path, str) or not relative_image_path.strip():
            continue
        image_path = Path(relative_image_path)
        image_stem = image_path.stem
        subset_root = image_path.parent.parent
        source_path = materialized_root / image_path
        if not source_path.exists():
            raise FileNotFoundError(f'Missing materialized AOLP image: {source_path}')

        destination = root / image_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        restored_members.append(destination.relative_to(dataset_root).as_posix())

        bbox = metadata.get('bbox') if isinstance(metadata.get('bbox'), dict) else {}
        x1 = int(bbox.get('x1') or 0)
        y1 = int(bbox.get('y1') or 0)
        x2 = int(bbox.get('x2') or 0)
        y2 = int(bbox.get('y2') or 0)

        localization_path = root / subset_root / 'groundtruth_localization' / f'{image_stem}.txt'
        localization_path.parent.mkdir(parents=True, exist_ok=True)
        localization_path.write_text(f'{x1} {y1} {x2} {y2}\n', encoding='utf-8')
        restored_members.append(localization_path.relative_to(dataset_root).as_posix())

        recognition_path = root / subset_root / 'groundtruth_recognition' / f'{image_stem}.txt'
        recognition_path.parent.mkdir(parents=True, exist_ok=True)
        recognition_path.write_text(f"{str(case.get('expectedText') or '').strip()}\n", encoding='utf-8')
        restored_members.append(recognition_path.relative_to(dataset_root).as_posix())

    return {
        'root': str(root.resolve()),
        'fileCount': len(restored_members),
        'files': restored_members,
    }


def _restore_lp2025_minimal(dataset_root: Path, manifest_payload: dict[str, object]) -> dict[str, object]:
    root = dataset_root / 'LP2025'
    if root.exists():
        shutil.rmtree(root)
    materialized_root = dataset_root.parent / '.runtime' / 'cache' / 'benchmark' / 'datasets' / 'official' / 'lp2025-readable-ocr' / 'lp2025'
    restored_members: list[str] = []
    for case in manifest_payload.get('cases') or []:
        if not isinstance(case, dict):
            continue
        metadata = case.get('metadata')
        if not isinstance(metadata, dict):
            continue
        relative_image_path = metadata.get('relativeImagePath')
        if not isinstance(relative_image_path, str) or not relative_image_path.strip():
            continue
        image_path = Path(relative_image_path)
        source_path = materialized_root / image_path
        if not source_path.exists():
            raise FileNotFoundError(f'Missing materialized LP2025 image: {source_path}')

        destination = root / image_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        restored_members.append(destination.relative_to(dataset_root).as_posix())

        bbox = metadata.get('bbox') if isinstance(metadata.get('bbox'), dict) else {}
        x1 = int(bbox.get('x1') or 0)
        y1 = int(bbox.get('y1') or 0)
        x2 = int(bbox.get('x2') or 0)
        y2 = int(bbox.get('y2') or 0)
        raw_label = str(metadata.get('rawLabelText') or case.get('expectedText') or '').strip()
        label_line = f'{raw_label} {x1} {y1} {x2} {y1} {x2} {y2} {x1} {y2}\n'
        label_path = root / image_path.parents[1] / 'labels_gd' / f'{image_path.stem}.txt'
        label_path.parent.mkdir(parents=True, exist_ok=True)
        label_path.write_text(label_line, encoding='utf-8')
        restored_members.append(label_path.relative_to(dataset_root).as_posix())

    return {
        'root': str(root.resolve()),
        'fileCount': len(restored_members),
        'files': restored_members,
    }


def _restore_ufpr_minimal(dataset_root: Path, manifest_payload: dict[str, object]) -> dict[str, object]:
    root = dataset_root / 'UFPR-ALPR dataset'
    if root.exists():
        shutil.rmtree(root)

    required_members: set[str] = set()
    for case in manifest_payload.get('cases') or []:
        if not isinstance(case, dict):
            continue
        metadata = case.get('metadata')
        if not isinstance(metadata, dict):
            continue
        for frame_member in metadata.get('trackFrameMembers') or []:
            if not isinstance(frame_member, str) or not frame_member.strip():
                continue
            required_members.add(frame_member)
            required_members.add(Path(frame_member).with_suffix('.txt').as_posix())

    restored_members: list[str] = []
    with ZipFile(dataset_root / 'yj4Iu2-UFPR-ALPR.zip') as archive:
        available_members = set(archive.namelist())
        for member in sorted(required_members):
            archive_member = f'UFPR-ALPR dataset/{member}'
            if archive_member not in available_members:
                raise FileNotFoundError(f'Missing UFPR member in archive: {archive_member}')
            destination = root / member
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(archive_member))
            restored_members.append(destination.relative_to(dataset_root).as_posix())

    return {
        'root': str(root.resolve()),
        'fileCount': len(restored_members),
        'files': restored_members,
    }


if __name__ == '__main__':
    raise SystemExit(main())