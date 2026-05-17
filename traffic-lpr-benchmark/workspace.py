from __future__ import annotations

import sys
from pathlib import Path


def tool_root() -> Path:
    return Path(__file__).resolve().parent


def repo_root() -> Path:
    return tool_root().parent


def default_runtime_root() -> Path:
    return repo_root() / 'traffic-lpr-runtime'


def default_workspace_root() -> Path:
    return repo_root() / '.runtime' / 'benchmark-tool'


def default_suite_root() -> Path:
    return default_workspace_root() / 'suites'


def default_run_root() -> Path:
    return default_workspace_root() / 'runs'


def default_report_root() -> Path:
    return default_workspace_root() / 'reports'


def ensure_workspace(root: Path | None = None) -> Path:
    workspace_root = (root or default_workspace_root()).resolve()
    for child in (
        workspace_root,
        workspace_root / 'suites',
        workspace_root / 'runs',
        workspace_root / 'reports',
        workspace_root / 'imports',
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
