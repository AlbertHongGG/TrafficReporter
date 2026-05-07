from __future__ import annotations

import contextlib
import io
import json
import sys
import traceback
from pathlib import Path
from typing import Any

from traffic_lpr_runtime.application.runtime_application import build_default_application
from traffic_lpr_runtime.domain.errors import RuntimeFailure


def main() -> int:
    runtime_script = Path(__file__).resolve()
    subcommand = sys.argv[1] if len(sys.argv) > 1 else 'status'
    application = None
    stdout_noise = io.StringIO()

    try:
        raw_payload = '' if sys.stdin.isatty() else sys.stdin.buffer.read().decode('utf-8').strip()
        payload = json.loads(raw_payload) if raw_payload else {}
        with contextlib.redirect_stdout(stdout_noise):
            application = build_default_application(runtime_script)
            result = application.dispatch(subcommand, payload)
        _flush_stdout_noise(stdout_noise)
        sys.stdout.write(json.dumps(result))
        return 0
    except RuntimeFailure as error:
        _flush_stdout_noise(stdout_noise)
        detail = {
            'runtime': _runtime_status_payload(application) | {'detail': str(error)},
            'error': str(error),
        }
        sys.stderr.write(json.dumps(detail))
        return 1
    except Exception as error:
        _flush_stdout_noise(stdout_noise)
        failure: dict[str, Any] = {
            'runtime': _runtime_status_payload(application) | {'detail': 'Unexpected LPR runtime failure.'},
            'error': str(error),
            'traceback': traceback.format_exc(),
        }
        sys.stderr.write(json.dumps(failure))
        return 1


def _flush_stdout_noise(stdout_noise: io.StringIO) -> None:
    noise = stdout_noise.getvalue().strip()
    if not noise:
        return
    sys.stderr.write(noise)
    if not noise.endswith('\n'):
        sys.stderr.write('\n')
    stdout_noise.seek(0)
    stdout_noise.truncate(0)


def _runtime_status_payload(application: Any) -> dict[str, Any]:
    if application is None:
        return {
            'available': False,
            'pythonExecutable': sys.executable,
            'runtimeScript': None,
            'version': f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}',
            'missingPackages': [],
            'installedPackages': [],
            'detail': 'LPR runtime bootstrap failed before status could be collected.',
        }
    return application.status()
