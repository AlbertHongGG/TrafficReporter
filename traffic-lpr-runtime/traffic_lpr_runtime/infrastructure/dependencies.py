from __future__ import annotations

import contextlib
import importlib
import io
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from traffic_lpr_runtime.domain.errors import RuntimeFailure
from traffic_lpr_runtime.domain.models import RuntimeStatus


DEPENDENCY_NAMES = [
    ('opencv-python', 'cv2'),
    ('numpy', 'numpy'),
    ('ultralytics', 'ultralytics'),
    ('fast-alpr[onnx-gpu]', 'fast_alpr'),
]


@dataclass(slots=True)
class DependencyRegistry:
    runtime_script: Path
    cv2: Any | None
    numpy: Any | None
    torch: Any | None
    ultralytics: Any | None
    fast_alpr: Any | None

    @classmethod
    def load(cls, runtime_script: Path) -> 'DependencyRegistry':
        _prime_gpu_runtime()
        return cls(
            runtime_script=runtime_script,
            cv2=_safe_import('cv2'),
            numpy=_safe_import('numpy'),
            torch=_safe_import('torch'),
            ultralytics=_safe_import('ultralytics'),
            fast_alpr=_safe_import('fast_alpr'),
        )

    def runtime_root(self) -> Path:
        search_roots = (self.runtime_script.parent, *self.runtime_script.parents)
        for candidate in search_roots:
            if (candidate / 'pyproject.toml').exists():
                return candidate
        return self.runtime_script.parent

    def models_root(self) -> Path:
        models_root = self.runtime_root() / 'models'
        models_root.mkdir(parents=True, exist_ok=True)
        return models_root

    def torch_cuda_available(self) -> bool:
        if self.torch is None:
            return False

        try:
            return bool(self.torch.cuda.is_available())
        except Exception:
            return False

    def preferred_torch_device(self) -> str:
        return 'cuda:0' if self.torch_cuda_available() else 'cpu'

    def installed_packages(self) -> list[str]:
        installed: list[str] = []
        for package_name, module_name in DEPENDENCY_NAMES:
            if getattr(self, _module_attr_name(module_name)) is not None:
                installed.append(package_name)
        return installed

    def missing_packages(self) -> list[str]:
        missing: list[str] = []
        for package_name, module_name in DEPENDENCY_NAMES:
            if getattr(self, _module_attr_name(module_name)) is None:
                missing.append(package_name)
        return missing

    def ensure_ready(self) -> None:
        missing = self.missing_packages()
        if missing:
            raise RuntimeFailure(
                'Missing Python packages: ' + ', '.join(missing) + '. Install them inside traffic-lpr-runtime/.venv.'
            )

    def build_status(self) -> RuntimeStatus:
        missing = self.missing_packages()
        available = not missing
        detail = (
            'Local LPR runtime ready.'
            if available
            else 'Install the missing runtime packages to enable local LPR.'
        )
        version = f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'
        return RuntimeStatus(
            available=available,
            python_executable=sys.executable,
            runtime_script=str(self.runtime_script),
            version=version,
            missing_packages=missing,
            installed_packages=self.installed_packages(),
            detail=detail,
        )


def _module_attr_name(module_name: str) -> str:
    return module_name.replace('.', '_')


def _safe_import(module_name: str) -> Any | None:
    try:
        return importlib.import_module(module_name)
    except Exception:
        return None


def _prime_gpu_runtime() -> None:
    if sys.platform != 'win32':
        return

    search_paths = _candidate_gpu_dll_directories()
    if not search_paths:
        return

    current_path_entries = os.environ.get('PATH', '').split(os.pathsep)
    normalized_existing = {entry.lower() for entry in current_path_entries if entry}
    prepended_paths: list[str] = []

    for path in search_paths:
        path_str = str(path)
        normalized = path_str.lower()
        if normalized not in normalized_existing:
            prepended_paths.append(path_str)
            normalized_existing.add(normalized)

        if hasattr(os, 'add_dll_directory'):
            try:
                os.add_dll_directory(path_str)
            except OSError:
                continue

    if prepended_paths:
        os.environ['PATH'] = os.pathsep.join(prepended_paths + current_path_entries)

    onnxruntime = _safe_import('onnxruntime')
    preload = getattr(onnxruntime, 'preload_dlls', None) if onnxruntime is not None else None
    if callable(preload):
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                preload()
        except TypeError:
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    preload(cuda=True, cudnn=True, msvc=True)
            except Exception:
                return
        except Exception:
            return


def _candidate_gpu_dll_directories() -> list[Path]:
    directories: list[Path] = []

    for torch_lib_dir in _torch_gpu_library_dirs():
        directories.append(torch_lib_dir)

    python_root = Path(sys.prefix)
    for relative_path in [
        Path('Lib/site-packages/nvidia/cublas/bin'),
        Path('Lib/site-packages/nvidia/cuda_runtime/bin'),
        Path('Lib/site-packages/nvidia/cudnn/bin'),
        Path('Lib/site-packages/nvidia/cufft/bin'),
        Path('Lib/site-packages/nvidia/curand/bin'),
        Path('Lib/site-packages/nvidia/cusolver/bin'),
        Path('Lib/site-packages/nvidia/cusparse/bin'),
    ]:
        candidate = python_root / relative_path
        if candidate.exists():
            directories.append(candidate)

    for env_key, env_value in os.environ.items():
        if not env_key.startswith('CUDA_PATH'):
            continue
        if not env_value:
            continue
        candidate = Path(env_value) / 'bin'
        if candidate.exists():
            directories.append(candidate)

    seen: set[str] = set()
    unique_directories: list[Path] = []
    for directory in directories:
        normalized = str(directory).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_directories.append(directory)

    return unique_directories


def _torch_gpu_library_dirs() -> list[Path]:
    torch = _safe_import('torch')
    if torch is None:
        return []

    torch_root = Path(getattr(torch, '__file__', '')).resolve().parent
    if not torch_root.exists():
        return []

    torch_lib = torch_root / 'lib'
    if not torch_lib.exists():
        return []

    has_cuda_runtime = any(
        (torch_lib / library_name).exists()
        for library_name in [
            'cublas64_12.dll',
            'cublasLt64_12.dll',
            'cudnn64_9.dll',
            'cudnn_ops64_9.dll',
            'cudnn_cnn64_9.dll',
            'nvrtc64_120_0.dll',
        ]
    )
    return [torch_lib] if has_cuda_runtime else []
