from __future__ import annotations

import secrets
from datetime import datetime
from pathlib import Path
from typing import Any


class RuntimeStorageLayout:
    """Object-oriented runtime storage layout manager for canonical repo-level storage."""

    def __init__(self, runtime_root: Path, repo_root: Path | None = None) -> None:
        self._runtime_root = runtime_root.resolve()
        self._repo_root = repo_root.resolve() if repo_root is not None else self._resolve_repo_root(self._runtime_root)

    @classmethod
    def from_root(cls, root: Path) -> RuntimeStorageLayout:
        resolved = root.resolve()
        repo_root = cls._resolve_repo_root(resolved)
        runtime_root = resolved if resolved.name == 'traffic-lpr-runtime' else (repo_root / 'traffic-lpr-runtime')
        return cls(runtime_root=runtime_root, repo_root=repo_root)

    @classmethod
    def discover(cls, start_path: Path | None = None) -> RuntimeStorageLayout:
        target = (start_path or Path(__file__)).resolve()
        candidates = [target, *target.parents]
        for candidate in candidates:
            if (candidate / 'pyproject.toml').exists() and candidate.name == 'traffic-lpr-runtime':
                return cls.from_root(candidate)
            if (candidate / 'traffic-lpr-runtime' / 'pyproject.toml').exists():
                return cls.from_root(candidate / 'traffic-lpr-runtime')
        return cls.from_root(Path.cwd())

    @staticmethod
    def _resolve_repo_root(start_root: Path) -> Path:
        resolved = start_root.resolve()
        if (resolved / 'pyproject.toml').exists() and resolved.name == 'traffic-lpr-runtime':
            return resolved.parent

        for candidate in (resolved, *resolved.parents):
            runtime_candidate = candidate / 'traffic-lpr-runtime'
            if runtime_candidate.is_dir() and (runtime_candidate / 'pyproject.toml').exists():
                return candidate

        return resolved

    @property
    def runtime_root(self) -> Path:
        return self._runtime_root

    @property
    def repo_root(self) -> Path:
        return self._repo_root

    @property
    def data_root(self) -> Path:
        return self._repo_root / '.runtime'

    @property
    def runs_root(self) -> Path:
        return self.data_root / 'runs'

    @property
    def cache_root(self) -> Path:
        return self.data_root / 'cache'

    @property
    def vendor_cache_root(self) -> Path:
        return self.cache_root / 'vendor'

    @property
    def models_root(self) -> Path:
        models_dir = self._runtime_root / 'models'
        models_dir.mkdir(parents=True, exist_ok=True)
        return models_dir

    def ensure_layout(self) -> Path:
        data_root = self.data_root
        for child in (
            data_root,
            self.runs_root,
            self.cache_root,
            self.vendor_cache_root,
            self.models_root,
        ):
            child.mkdir(parents=True, exist_ok=True)
        return data_root

    def generate_run_id(self, now: datetime | None = None) -> str:
        timestamp = (now or datetime.now()).strftime('%y%m%d-%H%M%S')
        return f'{timestamp}-{secrets.token_hex(4)}'

    def run_root(self, run_id: str) -> Path:
        return self.runs_root / run_id

    def run_child(self, run_id: str, *parts: str) -> Path:
        root = self.run_root(run_id)
        if parts:
            return root.joinpath(*parts)
        return root

    def resolve_artifact_dir(
        self,
        options: Any,
        suffix: str | None = None,
        run_id: str | None = None,
    ) -> Path | None:
        if not getattr(options, 'persist_artifacts', False):
            return None

        artifact_dir = getattr(options, 'artifact_dir', None)
        if artifact_dir:
            root = Path(artifact_dir)
        else:
            resolved_run_id = run_id or self.generate_run_id()
            root = self.run_child(resolved_run_id, 'analysis')
            debug_tag = getattr(options, 'debug_tag', None)
            if debug_tag:
                root = root / debug_tag

        if suffix:
            root = root / suffix
        root.mkdir(parents=True, exist_ok=True)
        return root
