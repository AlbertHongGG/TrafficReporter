from __future__ import annotations

import secrets
from datetime import datetime
from pathlib import Path


def resolve_repo_root(runtime_root: Path) -> Path:
    resolved_runtime_root = runtime_root.resolve()
    if (resolved_runtime_root / 'pyproject.toml').exists() and resolved_runtime_root.name == 'traffic-lpr-runtime':
        return resolved_runtime_root.parent

    for candidate in (resolved_runtime_root, *resolved_runtime_root.parents):
        runtime_candidate = candidate / 'traffic-lpr-runtime'
        if runtime_candidate.is_dir() and (runtime_candidate / 'pyproject.toml').exists():
            return candidate

    return resolved_runtime_root


def runtime_data_root(runtime_root: Path) -> Path:
    return resolve_repo_root(runtime_root) / '.runtime'


def runs_root(runtime_root: Path) -> Path:
    return runtime_data_root(runtime_root) / 'runs'


def cache_root(runtime_root: Path) -> Path:
    return runtime_data_root(runtime_root) / 'cache'


def benchmark_workspace_root(runtime_root: Path) -> Path:
    return cache_root(runtime_root) / 'benchmark'


def benchmark_suite_root(runtime_root: Path) -> Path:
    return benchmark_workspace_root(runtime_root) / 'suites'


def benchmark_import_root(runtime_root: Path) -> Path:
    return benchmark_workspace_root(runtime_root) / 'imports'


def benchmark_dataset_cache_root(runtime_root: Path) -> Path:
    return benchmark_workspace_root(runtime_root) / 'datasets'


def vendor_cache_root(runtime_root: Path) -> Path:
    return cache_root(runtime_root) / 'vendor'


def build_run_id(now: datetime | None = None) -> str:
    timestamp = (now or datetime.now()).strftime('%y%m%d-%H%M%S')
    return f'{timestamp}-{secrets.token_hex(4)}'


def run_root(runtime_root: Path, run_id: str) -> Path:
    return runs_root(runtime_root) / run_id


def run_child(runtime_root: Path, run_id: str, *parts: str) -> Path:
    root = run_root(runtime_root, run_id)
    if parts:
        return root.joinpath(*parts)
    return root


def ensure_runtime_layout(runtime_root: Path) -> Path:
    data_root = runtime_data_root(runtime_root)
    for child in (
        data_root,
        runs_root(runtime_root),
        cache_root(runtime_root),
        benchmark_workspace_root(runtime_root),
        benchmark_suite_root(runtime_root),
        benchmark_import_root(runtime_root),
        benchmark_dataset_cache_root(runtime_root),
        vendor_cache_root(runtime_root),
    ):
        child.mkdir(parents=True, exist_ok=True)
    return data_root