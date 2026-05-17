from __future__ import annotations

import time
from typing import Any


def build_analysis_provenance(
    command: str,
    payload: dict[str, Any],
    runtime_status: dict[str, Any],
) -> dict[str, Any]:
    return {
        'requestId': _optional_string(payload.get('requestId')),
        'command': command,
        'analysisProfileId': _optional_string(payload.get('analysisProfileId')),
        'developerDiagnosticsEnabled': bool(payload.get('enableDeveloperDiagnostics')),
        'runtimeVersion': _optional_string(runtime_status.get('version')),
        'emittedAtMs': time.time_ns() // 1_000_000,
    }


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None