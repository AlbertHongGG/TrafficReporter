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


LPR_RUNTIME_PROTOCOL_VERSION = 1


def main() -> int:
    runtime_script = Path(__file__).resolve()
    subcommand = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if subcommand == 'serve':
        return serve(runtime_script)

    application = None
    stdout_noise = io.StringIO()
    protocol_mode = subcommand == 'benchmark-run'
    request_id: Any = None

    try:
        raw_payload = '' if sys.stdin.isatty() else sys.stdin.buffer.read().decode('utf-8').strip()
        payload, protocol_mode, request_id = _unwrap_protocol_request(
            raw_payload,
            subcommand,
            require_protocol=protocol_mode,
        )
        with contextlib.redirect_stdout(stdout_noise):
            application = build_default_application(runtime_script)
            result = application.dispatch(subcommand, payload)
        _flush_stdout_noise(stdout_noise)
        sys.stdout.write(json.dumps(_wrap_protocol_success(result, request_id=request_id, protocol_mode=protocol_mode)))
        return 0
    except RuntimeFailure as error:
        _flush_stdout_noise(stdout_noise)
        detail = _wrap_protocol_error(
            str(error),
            _runtime_status_payload(application) | {'detail': str(error)},
            request_id=request_id,
            protocol_mode=protocol_mode,
        )
        sys.stderr.write(json.dumps(detail))
        return 1
    except Exception as error:
        _flush_stdout_noise(stdout_noise)
        failure = _wrap_protocol_error(
            str(error),
            _runtime_status_payload(application) | {'detail': 'Unexpected LPR runtime failure.'},
            request_id=request_id,
            protocol_mode=protocol_mode,
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

        request_id: Any = None
        response: dict[str, Any]

        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise RuntimeFailure('Runtime worker request must be a JSON object.')
            subcommand = str(request.get('subcommand') or 'status')
            payload, _, request_id = _unwrap_protocol_request(line, subcommand, require_protocol=True)
            with contextlib.redirect_stdout(stdout_noise):
                result = application.dispatch(subcommand, payload)
            _flush_stdout_noise(stdout_noise)
            response = _wrap_protocol_success(result, request_id=request_id, protocol_mode=True)
        except RuntimeFailure as error:
            _flush_stdout_noise(stdout_noise)
            response = _wrap_protocol_error(
                str(error),
                _runtime_status_payload(application) | {'detail': str(error)},
                request_id=request_id,
                protocol_mode=True,
            )
        except Exception as error:
            _flush_stdout_noise(stdout_noise)
            response = _wrap_protocol_error(
                str(error),
                _runtime_status_payload(application) | {'detail': 'Unexpected LPR runtime failure.'},
                request_id=request_id,
                protocol_mode=True,
                traceback_text=traceback.format_exc(),
            )

        sys.stdout.write(json.dumps(response) + '\n')
        sys.stdout.flush()

    return 0


def _unwrap_protocol_request(
    raw_payload: str,
    subcommand: str,
    *,
    require_protocol: bool,
) -> tuple[dict[str, Any], bool, Any]:
    payload = json.loads(raw_payload) if raw_payload else {}
    if not isinstance(payload, dict):
        raise RuntimeFailure('Runtime request must be a JSON object.')

    protocol_version = payload.get('protocolVersion')
    if protocol_version is None:
        if require_protocol:
            raise RuntimeFailure('Missing runtime protocolVersion in broker request.')
        return payload, False, payload.get('requestId')
    if protocol_version != LPR_RUNTIME_PROTOCOL_VERSION:
        raise RuntimeFailure(
            f'Unsupported runtime protocolVersion {protocol_version}; expected {LPR_RUNTIME_PROTOCOL_VERSION}.',
        )

    envelope_subcommand = payload.get('subcommand')
    if isinstance(envelope_subcommand, str) and envelope_subcommand and envelope_subcommand != subcommand:
        raise RuntimeFailure(
            f'Runtime broker subcommand mismatch: expected {subcommand}, received {envelope_subcommand}.',
        )

    envelope_payload = payload.get('payload')
    if envelope_payload is None:
        envelope_payload = {}
    if not isinstance(envelope_payload, dict):
        raise RuntimeFailure('Runtime broker payload must be a JSON object.')
    return envelope_payload, True, payload.get('requestId')


def _wrap_protocol_success(result: dict[str, Any], *, request_id: Any, protocol_mode: bool) -> dict[str, Any]:
    if not protocol_mode:
        return result
    return {
        'protocolVersion': LPR_RUNTIME_PROTOCOL_VERSION,
        'requestId': request_id,
        'ok': True,
        'result': result,
    }


def _wrap_protocol_error(
    error_message: str,
    runtime_payload: dict[str, Any],
    *,
    request_id: Any,
    protocol_mode: bool,
    traceback_text: str | None = None,
) -> dict[str, Any]:
    detail: dict[str, Any] = {
        'runtime': runtime_payload,
        'error': error_message,
    }
    if traceback_text:
        detail['traceback'] = traceback_text
    if not protocol_mode:
        return detail
    return {
        'protocolVersion': LPR_RUNTIME_PROTOCOL_VERSION,
        'requestId': request_id,
        'ok': False,
        **detail,
    }


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
