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
from traffic_lpr_runtime.protocol import (
    RuntimeRequestContext,
    build_runtime_error,
    build_runtime_progress,
    build_runtime_success,
    emit_runtime_progress,
    install_runtime_progress_sink,
    reset_runtime_progress_sink,
    unwrap_runtime_request,
)


LPR_RUNTIME_PROTOCOL_VERSION = 1


def main() -> int:
    runtime_script = Path(__file__).resolve()
    subcommand = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if subcommand == 'serve':
        return serve(runtime_script)

    application = None
    stdout_noise = io.StringIO()
    protocol_mode = subcommand == 'benchmark-run'
    request_context = RuntimeRequestContext(protocol_mode=False, protocol_version=None, request_id=None)

    try:
        raw_payload = '' if sys.stdin.isatty() else sys.stdin.buffer.read().decode('utf-8').strip()
        payload, request_context = unwrap_runtime_request(
            raw_payload,
            subcommand,
            require_protocol=protocol_mode,
            accepted_versions=(LPR_RUNTIME_PROTOCOL_VERSION,),
            error_factory=RuntimeFailure,
        )
        with contextlib.redirect_stdout(stdout_noise):
            application = build_default_application(runtime_script)
            result = application.dispatch(subcommand, payload)
        _flush_stdout_noise(stdout_noise)
        sys.stdout.write(json.dumps(build_runtime_success(result, request_context=request_context)))
        return 0
    except RuntimeFailure as error:
        _flush_stdout_noise(stdout_noise)
        detail = build_runtime_error(
            str(error),
            _runtime_status_payload(application) | {'detail': str(error)},
            request_context=request_context,
        )
        sys.stderr.write(json.dumps(detail))
        return 1
    except Exception as error:
        _flush_stdout_noise(stdout_noise)
        failure = build_runtime_error(
            str(error),
            _runtime_status_payload(application) | {'detail': 'Unexpected LPR runtime failure.'},
            request_context=request_context,
            traceback_text=traceback.format_exc(),
        )
        sys.stderr.write(json.dumps(failure))
        return 1


def serve(runtime_script: Path) -> int:
    stdout_noise = io.StringIO()

    try:
        with contextlib.redirect_stdout(stdout_noise):
            application = build_default_application(runtime_script)
    except Exception:
        _flush_stdout_noise(stdout_noise)
        sys.stderr.write(traceback.format_exc())
        return 1

    _flush_stdout_noise(stdout_noise)

    while True:
        raw_line = sys.stdin.buffer.readline()
        if not raw_line:
            break

        line = raw_line.decode('utf-8').strip()
        if not line:
            continue

        request_context = RuntimeRequestContext(protocol_mode=True, protocol_version=LPR_RUNTIME_PROTOCOL_VERSION, request_id=None)
        response: dict[str, Any]

        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise RuntimeFailure('Runtime worker request must be a JSON object.')
            subcommand = str(request.get('subcommand') or 'status')
            payload, request_context = unwrap_runtime_request(
                line,
                subcommand,
                require_protocol=True,
                accepted_versions=(LPR_RUNTIME_PROTOCOL_VERSION,),
                error_factory=RuntimeFailure,
            )
            token = install_runtime_progress_sink(
                lambda progress_payload: _write_progress(progress_payload, request_context),
            )
            try:
                with contextlib.redirect_stdout(stdout_noise):
                    emit_runtime_progress({
                        'progress': 0.02,
                        'stage': subcommand,
                        'detail': f'Starting {subcommand} request.',
                        'done': False,
                        'failed': False,
                    })
                    result = application.dispatch(subcommand, payload)
            finally:
                reset_runtime_progress_sink(token)
            _flush_stdout_noise(stdout_noise)
            response = build_runtime_success(result, request_context=request_context)
        except RuntimeFailure as error:
            _flush_stdout_noise(stdout_noise)
            response = build_runtime_error(
                str(error),
                _runtime_status_payload(application) | {'detail': str(error)},
                request_context=request_context,
            )
        except Exception as error:
            _flush_stdout_noise(stdout_noise)
            response = build_runtime_error(
                str(error),
                _runtime_status_payload(application) | {'detail': 'Unexpected LPR runtime failure.'},
                request_context=request_context,
                traceback_text=traceback.format_exc(),
            )

        sys.stdout.write(json.dumps(response) + '\n')
        sys.stdout.flush()

    return 0


def _write_progress(progress_payload: dict[str, Any], request_context: RuntimeRequestContext) -> None:
    stream = getattr(sys, '__stdout__', None) or sys.stdout
    stream.write(json.dumps(build_runtime_progress(progress_payload, request_context=request_context)) + '\n')
    stream.flush()

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
