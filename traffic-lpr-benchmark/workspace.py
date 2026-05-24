from __future__ import annotations

import sys
from pathlib import Path


RUNTIME_PACKAGE_ROOT = Path(__file__).resolve().parent.parent / 'traffic-lpr-runtime'
if str(RUNTIME_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_PACKAGE_ROOT))

from traffic_lpr_runtime.infrastructure.runtime_layout import (
    benchmark_dataset_cache_root as shared_benchmark_dataset_cache_root,
    benchmark_import_root as shared_benchmark_import_root,
    benchmark_suite_root as shared_benchmark_suite_root,
    benchmark_workspace_root as shared_benchmark_workspace_root,
    ensure_runtime_layout,
    runs_root as shared_runs_root,
)


def tool_root() -> Path:
    return Path(__file__).resolve().parent


def repo_root() -> Path:
    return tool_root().parent


def default_runtime_root() -> Path:
    return repo_root() / 'traffic-lpr-runtime'


def default_workspace_root(runtime_root: Path | None = None) -> Path:
    return shared_benchmark_workspace_root((runtime_root or default_runtime_root()).resolve())


def default_suite_root(runtime_root: Path | None = None) -> Path:
    return shared_benchmark_suite_root((runtime_root or default_runtime_root()).resolve())


def default_import_root(runtime_root: Path | None = None) -> Path:
    return shared_benchmark_import_root((runtime_root or default_runtime_root()).resolve())


def default_dataset_cache_root(runtime_root: Path | None = None) -> Path:
    return shared_benchmark_dataset_cache_root((runtime_root or default_runtime_root()).resolve())


def default_run_root(runtime_root: Path | None = None) -> Path:
    return shared_runs_root((runtime_root or default_runtime_root()).resolve())


def ensure_workspace(root: Path | None = None, runtime_root: Path | None = None) -> Path:
    resolved_runtime_root = (runtime_root or default_runtime_root()).resolve()
    workspace_root = (root or default_workspace_root(resolved_runtime_root)).resolve()
    ensure_runtime_layout(resolved_runtime_root)
    for child in (
        workspace_root,
        workspace_root / 'suites',
        workspace_root / 'imports',
        workspace_root / 'datasets',
    ):
        child.mkdir(parents=True, exist_ok=True)
    return workspace_root


def discover_python(runtime_root: Path) -> str:
    runtime_root = runtime_root.resolve()
    candidates = []
    if sys.platform.startswith('win'):
        candidates.append(runtime_root / '.venv' / 'Scripts' / 'python.exe')
    else:
        candidates.append(runtime_root / '.venv' / 'bin' / 'python')
    candidates.append(Path(sys.executable))

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable
