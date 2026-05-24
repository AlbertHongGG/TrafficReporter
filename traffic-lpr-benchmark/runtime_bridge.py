from __future__ import annotations

import json
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from workspace import default_runtime_root, discover_python


RUNTIME_BROKER_PROTOCOL_VERSION = 1


class RuntimeInvokeError(RuntimeError):
    pass


def build_runtime_request_envelope(
    subcommand: str,
    payload: dict[str, Any],
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        'protocolVersion': RUNTIME_BROKER_PROTOCOL_VERSION,
        'subcommand': subcommand,
        'payload': payload,
    }
    if request_id:
        envelope['requestId'] = request_id
    return envelope


def unwrap_runtime_response(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RuntimeInvokeError('Runtime returned a non-object benchmark result.')

    protocol_version = payload.get('protocolVersion')
    if protocol_version is None:
        return payload
    if protocol_version != RUNTIME_BROKER_PROTOCOL_VERSION:
        raise RuntimeInvokeError(
            f'Runtime broker protocol mismatch: expected {RUNTIME_BROKER_PROTOCOL_VERSION}, received {protocol_version}.',
        )

    if payload.get('ok') is False:
        detail = payload.get('error') or (payload.get('runtime') or {}).get('detail') or 'Unknown benchmark runtime failure.'
        raise RuntimeInvokeError(str(detail))

    result = payload.get('result')
    if not isinstance(result, dict):
        raise RuntimeInvokeError('Runtime returned success without a benchmark result payload.')
    return result


def run_benchmark_suite(
    suite_payload: dict[str, Any],
    runtime_root: Path | None = None,
    python_executable: str | None = None,
    run_id: str | None = None,
    artifact_root: Path | None = None,
    request_id: str | None = None,
    progress_path: Path | None = None,
    checkpoint_path: Path | None = None,
    resume_from_checkpoint: bool = False,
    progress_reporter: Callable[[dict[str, Any]], None] | None = None,
    poll_interval_seconds: float = 1.0,
) -> dict[str, Any]:
    resolved_runtime_root = (runtime_root or default_runtime_root()).resolve()
    resolved_python = python_executable or discover_python(resolved_runtime_root)
    request_payload = {
        'cases': suite_payload.get('cases') or [],
    }
    resolved_progress_path = progress_path.resolve() if progress_path is not None else None
    resolved_checkpoint_path = checkpoint_path.resolve() if checkpoint_path is not None else None
    if resolved_progress_path is not None:
        request_payload['progressPath'] = str(resolved_progress_path)
    if resolved_checkpoint_path is not None:
        request_payload['checkpointPath'] = str(resolved_checkpoint_path)
    if run_id:
        request_payload['runId'] = run_id
    if artifact_root is not None:
        request_payload['artifactRoot'] = str(artifact_root.resolve())
    if resume_from_checkpoint:
        request_payload['resumeFromCheckpoint'] = True
    request_envelope = build_runtime_request_envelope('benchmark-run', request_payload, request_id=request_id or run_id)

    with tempfile.TemporaryFile(mode='w+t', encoding='utf-8') as stdout_file, tempfile.TemporaryFile(mode='w+t', encoding='utf-8') as stderr_file:
        completed = subprocess.Popen(
            [resolved_python, '-m', 'traffic_lpr_runtime', 'benchmark-run'],
            cwd=resolved_runtime_root,
            stdin=subprocess.PIPE,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
        )

        if completed.stdin is None:
            raise RuntimeInvokeError('Runtime bridge could not open stdin for benchmark execution.')
        completed.stdin.write(json.dumps(request_envelope))
        completed.stdin.close()

        last_progress_signature: tuple[Any, ...] | None = None
        while completed.poll() is None:
            if progress_reporter is not None and resolved_progress_path is not None:
                last_progress_signature = _emit_progress_update(resolved_progress_path, progress_reporter, last_progress_signature)
            time.sleep(max(poll_interval_seconds, 0.1))

        if progress_reporter is not None and resolved_progress_path is not None:
            _emit_progress_update(resolved_progress_path, progress_reporter, last_progress_signature)

        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read()
        stderr = stderr_file.read()

    if completed.returncode != 0:
        detail = stderr.strip() or stdout.strip() or 'Unknown benchmark runtime failure.'
        try:
            parsed = json.loads(detail)
            if isinstance(parsed, dict):
                detail = str(parsed.get('error') or parsed.get('runtime', {}).get('detail') or detail)
        except json.JSONDecodeError:
            pass
        raise RuntimeInvokeError(detail)

    try:
        result = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise RuntimeInvokeError(f'Runtime returned invalid JSON: {error}') from error
    return unwrap_runtime_response(result)


def _emit_progress_update(
    progress_path: Path,
    progress_reporter: Callable[[dict[str, Any]], None],
    last_progress_signature: tuple[Any, ...] | None,
) -> tuple[Any, ...] | None:
    if not progress_path.exists():
        return last_progress_signature

    try:
        payload = json.loads(progress_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return last_progress_signature
    if not isinstance(payload, dict):
        return last_progress_signature

    signature = (
        payload.get('completedCaseCount'),
        payload.get('currentCaseId'),
        payload.get('updatedAt'),
        payload.get('completed'),
    )
    if signature == last_progress_signature:
        return last_progress_signature

    progress_reporter(payload)
    return signature
