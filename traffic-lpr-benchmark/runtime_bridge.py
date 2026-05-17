from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from workspace import default_runtime_root, discover_python


class RuntimeInvokeError(RuntimeError):
    pass


def run_benchmark_suite(
    suite_payload: dict[str, Any],
    runtime_root: Path | None = None,
    python_executable: str | None = None,
) -> dict[str, Any]:
    resolved_runtime_root = (runtime_root or default_runtime_root()).resolve()
    resolved_python = python_executable or discover_python(resolved_runtime_root)
    request_payload = {
        'cases': suite_payload.get('cases') or [],
    }

    completed = subprocess.run(
        [resolved_python, '-m', 'traffic_lpr_runtime', 'benchmark-run'],
        cwd=resolved_runtime_root,
        input=json.dumps(request_payload),
        text=True,
        capture_output=True,
        check=False,
    )

    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or 'Unknown benchmark runtime failure.'
        try:
            parsed = json.loads(detail)
            if isinstance(parsed, dict):
                detail = str(parsed.get('error') or parsed.get('runtime', {}).get('detail') or detail)
        except json.JSONDecodeError:
            pass
        raise RuntimeInvokeError(detail)

    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeInvokeError(f'Runtime returned invalid JSON: {error}') from error

    if not isinstance(result, dict):
        raise RuntimeInvokeError('Runtime returned a non-object benchmark result.')
    return result
