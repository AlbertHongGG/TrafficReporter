from __future__ import annotations

import argparse
import json
import os
import shutil
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pyzipper


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Restore full local AOLP, LP2025, and UFPR dataset roots from the preserved benchmark archives.'
    )
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[3], help='Repository root containing datasets/.')
    parser.add_argument('--datasets', nargs='+', choices=['aolp', 'lp2025', 'ufpr-alpr'], default=['aolp', 'lp2025', 'ufpr-alpr'], help='Which local datasets to restore from their archives.')
    parser.add_argument('--aolp-outer-password', default=None, help='Password for the outer AOLP.zip archive. Defaults to AOLP_OUTER_PASSWORD env var.')
    parser.add_argument('--aolp-inner-password', default=None, help='Password for the nested AOLP subset archives. Defaults to AOLP_INNER_PASSWORD env var, then AOLP_OUTER_PASSWORD.')
    parser.add_argument('--lp2025-password', default=None, help='Password for LP2025.zip. Defaults to LP2025_PASSWORD env var.')
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    dataset_root = repo_root / 'datasets'
    restored: dict[str, dict[str, object]] = {}

    if 'aolp' in args.datasets:
        outer_password = _resolve_password(args.aolp_outer_password, 'AOLP_OUTER_PASSWORD')
        inner_password = _resolve_password(args.aolp_inner_password, 'AOLP_INNER_PASSWORD') or outer_password
        if outer_password is None:
            raise ValueError('AOLP outer password is required. Pass --aolp-outer-password or set AOLP_OUTER_PASSWORD.')
        if inner_password is None:
            raise ValueError('AOLP inner password is required. Pass --aolp-inner-password or set AOLP_INNER_PASSWORD.')
        restored['aolp'] = _restore_aolp_full(dataset_root, outer_password, inner_password)

    if 'lp2025' in args.datasets:
        lp2025_password = _resolve_password(args.lp2025_password, 'LP2025_PASSWORD')
        if lp2025_password is None:
            raise ValueError('LP2025 password is required. Pass --lp2025-password or set LP2025_PASSWORD.')
        restored['lp2025'] = _restore_archive_tree(
            archive_path=dataset_root / 'LP2025.zip',
            password=lp2025_password,
            archive_root='LP2025/',
            destination_root=dataset_root / 'LP2025',
            strip_prefix='LP2025/',
        )

    if 'ufpr-alpr' in args.datasets:
        restored['ufpr-alpr'] = _restore_archive_tree(
            archive_path=dataset_root / 'yj4Iu2-UFPR-ALPR.zip',
            password=None,
            archive_root='UFPR-ALPR dataset/',
            destination_root=dataset_root / 'UFPR-ALPR dataset',
            strip_prefix='UFPR-ALPR dataset/',
        )

    print(json.dumps({'datasetRoot': str(dataset_root.resolve()), 'restored': restored}, ensure_ascii=False, indent=2))
    return 0


def _resolve_password(explicit: str | None, env_name: str) -> bytes | None:
    value = explicit if explicit is not None else os.environ.get(env_name)
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized.encode('utf-8')


def _restore_aolp_full(dataset_root: Path, outer_password: bytes, inner_password: bytes) -> dict[str, object]:
    destination_root = dataset_root / 'AOLP'
    if destination_root.exists():
        shutil.rmtree(destination_root)
    destination_root.mkdir(parents=True, exist_ok=True)
    outer_archive = dataset_root / 'AOLP.zip'
    with ZipFile(outer_archive) as archive:
        subset_members = sorted(name for name in archive.namelist() if name.lower().endswith('.zip'))
        for subset_member in subset_members:
            nested_bytes = archive.read(subset_member, pwd=outer_password)
            with pyzipper.AESZipFile(BytesIO(nested_bytes)) as nested_archive:
                nested_archive.setpassword(inner_password)
                for member_name in nested_archive.namelist():
                    if member_name.endswith('/'):
                        continue
                    if not _should_extract_aolp_member(member_name):
                        continue
                    destination = destination_root / Path(member_name)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(nested_archive.read(member_name))

    extracted_files = sum(1 for path in destination_root.rglob('*') if path.is_file())
    extracted_dirs = sum(1 for path in destination_root.rglob('*') if path.is_dir())

    return {
        'root': str(destination_root.resolve()),
        'fileCount': extracted_files,
        'directoryCount': extracted_dirs,
        'archivePath': str(outer_archive.resolve()),
    }


def _should_extract_aolp_member(member_name: str) -> bool:
    normalized = member_name.replace('\\', '/').lower()
    return '/image/' in normalized or '/groundtruth_localization/' in normalized or '/groundtruth_recognition/' in normalized


def _restore_archive_tree(
    *,
    archive_path: Path,
    password: bytes | None,
    archive_root: str,
    destination_root: Path,
    strip_prefix: str,
) -> dict[str, object]:
    if destination_root.exists():
        shutil.rmtree(destination_root)
    destination_root.mkdir(parents=True, exist_ok=True)

    extracted_files = 0
    extracted_dirs: set[str] = set()
    with ZipFile(archive_path) as archive:
        for member_name in archive.namelist():
            if not member_name.startswith(archive_root):
                continue
            relative_name = member_name[len(strip_prefix):]
            if not relative_name:
                continue
            if member_name.endswith('/'):
                extracted_dirs.add(relative_name.rstrip('/'))
                continue
            destination = destination_root / Path(relative_name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(member_name, pwd=password))
            extracted_files += 1

    return {
        'root': str(destination_root.resolve()),
        'fileCount': extracted_files,
        'directoryCount': len(extracted_dirs),
        'archivePath': str(archive_path.resolve()),
    }


if __name__ == '__main__':
    raise SystemExit(main())