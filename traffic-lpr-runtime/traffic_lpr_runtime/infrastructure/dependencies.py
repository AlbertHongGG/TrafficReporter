from __future__ import annotations

import importlib
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
    ('fast-plate-ocr[onnx-gpu]', 'fast_plate_ocr'),
]


@dataclass(slots=True)
class DependencyRegistry:
    runtime_script: Path
    cv2: Any | None
    numpy: Any | None
    ultralytics: Any | None
    fast_alpr: Any | None
    fast_plate_ocr: Any | None

    @classmethod
    def load(cls, runtime_script: Path) -> 'DependencyRegistry':
        return cls(
            runtime_script=runtime_script,
            cv2=_safe_import('cv2'),
            numpy=_safe_import('numpy'),
            ultralytics=_safe_import('ultralytics'),
            fast_alpr=_safe_import('fast_alpr'),
            fast_plate_ocr=_safe_import('fast_plate_ocr'),
        )

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
