from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

RUNTIME_PACKAGE_ROOT = Path(__file__).resolve().parents[2].parent / 'traffic-lpr-runtime'
if str(RUNTIME_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_PACKAGE_ROOT))

from traffic_lpr_runtime.protocol import (
    LEGACY_RUNTIME_PROTOCOL_VERSION,
    build_runtime_request_envelope as shared_build_runtime_request_envelope,
    unwrap_runtime_response as shared_unwrap_runtime_response,
)

from .workspace import default_runtime_root, discover_python


RUNTIME_BROKER_PROTOCOL_VERSION = LEGACY_RUNTIME_PROTOCOL_VERSION


class RuntimeInvokeError(RuntimeError):
    pass


def build_runtime_request_envelope(
    subcommand: str,
    payload: dict[str, Any],
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    return shared_build_runtime_request_envelope(
        subcommand,
        payload,
        request_id=request_id,
        protocol_version=RUNTIME_BROKER_PROTOCOL_VERSION,
    )


def unwrap_runtime_response(payload: Any) -> dict[str, Any]:
    return shared_unwrap_runtime_response(
        payload,
        accepted_versions=(RUNTIME_BROKER_PROTOCOL_VERSION,),
        error_factory=RuntimeInvokeError,
    )


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