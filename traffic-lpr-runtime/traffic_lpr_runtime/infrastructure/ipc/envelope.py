from __future__ import annotations

import contextvars
import json
from dataclasses import dataclass
from typing import Any, Callable, Sequence


LEGACY_RUNTIME_PROTOCOL_VERSION = 1
VNEXT_RUNTIME_PROTOCOL_VERSION = 2
SUPPORTED_RUNTIME_PROTOCOL_VERSIONS: tuple[int, ...] = (
    LEGACY_RUNTIME_PROTOCOL_VERSION,
    VNEXT_RUNTIME_PROTOCOL_VERSION,
)
DEFAULT_RUNTIME_PROTOCOL_VERSION = LEGACY_RUNTIME_PROTOCOL_VERSION
_runtime_progress_sink: contextvars.ContextVar[Callable[[dict[str, Any]], None] | None] = contextvars.ContextVar(
    'runtime_progress_sink',
    default=None,
)


@dataclass(frozen=True, slots=True)
class RuntimeRequestContext:
    protocol_mode: bool
    protocol_version: int | None
    request_id: Any
    idempotency_key: str | None = None


def build_runtime_request_envelope(
    subcommand: str,
    payload: dict[str, Any],
    *,
    request_id: Any = None,
    protocol_version: int = DEFAULT_RUNTIME_PROTOCOL_VERSION,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if protocol_version not in SUPPORTED_RUNTIME_PROTOCOL_VERSIONS:
        raise ValueError(f'Unsupported runtime protocolVersion {protocol_version}.')
    if not isinstance(payload, dict):
        raise TypeError('Runtime payload must be a JSON object.')

    envelope: dict[str, Any] = {
        'protocolVersion': protocol_version,
        'subcommand': subcommand,
        'payload': payload,
    }
    if request_id is not None:
        envelope['requestId'] = request_id
    if protocol_version >= VNEXT_RUNTIME_PROTOCOL_VERSION:
        resolved_idempotency_key = _optional_string(idempotency_key)
        if not resolved_idempotency_key:
            raise ValueError('Runtime protocol v2 requires a non-empty idempotencyKey.')
        envelope['idempotencyKey'] = resolved_idempotency_key
    elif idempotency_key is not None:
        envelope['idempotencyKey'] = idempotency_key
    return envelope


def unwrap_runtime_request(
    raw_payload: str,
    subcommand: str,
    *,
    require_protocol: bool,
    accepted_versions: Sequence[int] = SUPPORTED_RUNTIME_PROTOCOL_VERSIONS,
    error_factory: Callable[[str], Exception],
) -> tuple[dict[str, Any], RuntimeRequestContext]:
    payload = json.loads(raw_payload) if raw_payload else {}
    if not isinstance(payload, dict):
        raise error_factory('Runtime request must be a JSON object.')

    protocol_version = payload.get('protocolVersion')
    if protocol_version is None:
        if require_protocol:
            raise error_factory('Missing runtime protocolVersion in broker request.')
        return payload, RuntimeRequestContext(
            protocol_mode=False,
            protocol_version=None,
            request_id=payload.get('requestId'),
        )
    if protocol_version not in accepted_versions:
        supported_versions = ', '.join(str(version) for version in accepted_versions)
        raise error_factory(
            f'Unsupported runtime protocolVersion {protocol_version}; expected one of [{supported_versions}].',
        )

    envelope_subcommand = payload.get('subcommand')
    if isinstance(envelope_subcommand, str) and envelope_subcommand and envelope_subcommand != subcommand:
        raise error_factory(
            f'Runtime broker subcommand mismatch: expected {subcommand}, received {envelope_subcommand}.',
        )

    envelope_payload = payload.get('payload')
    if envelope_payload is None:
        envelope_payload = {}
    if not isinstance(envelope_payload, dict):
        raise error_factory('Runtime broker payload must be a JSON object.')

    idempotency_key = _optional_string(payload.get('idempotencyKey'))
    if protocol_version >= VNEXT_RUNTIME_PROTOCOL_VERSION and not idempotency_key:
        raise error_factory('Runtime protocol v2 requires a non-empty idempotencyKey.')

    return envelope_payload, RuntimeRequestContext(
        protocol_mode=True,
        protocol_version=int(protocol_version),
        request_id=payload.get('requestId'),
        idempotency_key=idempotency_key,
    )


def build_runtime_success(
    result: dict[str, Any],
    *,
    request_context: RuntimeRequestContext,
) -> dict[str, Any]:
    if not request_context.protocol_mode:
        return result

    payload: dict[str, Any] = {
        'protocolVersion': request_context.protocol_version or DEFAULT_RUNTIME_PROTOCOL_VERSION,
        'requestId': request_context.request_id,
        'ok': True,
        'result': result,
    }
    if request_context.idempotency_key is not None:
        payload['idempotencyKey'] = request_context.idempotency_key
    return payload


def build_runtime_error(
    error_message: str,
    runtime_payload: dict[str, Any],
    *,
    request_context: RuntimeRequestContext,
    traceback_text: str | None = None,
) -> dict[str, Any]:
    detail: dict[str, Any] = {
        'runtime': runtime_payload,
        'error': error_message,
    }
    if traceback_text:
        detail['traceback'] = traceback_text
    if not request_context.protocol_mode:
        return detail

    payload: dict[str, Any] = {
        'protocolVersion': request_context.protocol_version or DEFAULT_RUNTIME_PROTOCOL_VERSION,
        'requestId': request_context.request_id,
        'ok': False,
        **detail,
    }
    if request_context.idempotency_key is not None:
        payload['idempotencyKey'] = request_context.idempotency_key
    return payload


def build_runtime_progress(
    progress_payload: dict[str, Any],
    *,
    request_context: RuntimeRequestContext,
) -> dict[str, Any]:
    progress_request_id = _normalize_progress_request_id(
        progress_payload.get('requestId', request_context.request_id),
    )
    payload = {
        'protocolVersion': request_context.protocol_version or DEFAULT_RUNTIME_PROTOCOL_VERSION,
        'requestId': request_context.request_id,
        'kind': 'progress',
        'progress': {
            **progress_payload,
            'requestId': progress_request_id,
        },
    }
    if request_context.idempotency_key is not None:
        payload['idempotencyKey'] = request_context.idempotency_key
    return payload


def unwrap_runtime_response(
    payload: Any,
    *,
    accepted_versions: Sequence[int] = SUPPORTED_RUNTIME_PROTOCOL_VERSIONS,
    error_factory: Callable[[str], Exception],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise error_factory('Runtime returned a non-object result.')

    protocol_version = payload.get('protocolVersion')
    if protocol_version is None:
        return payload
    if protocol_version not in accepted_versions:
        supported_versions = ', '.join(str(version) for version in accepted_versions)
        raise error_factory(
            f'Runtime broker protocol mismatch: expected one of [{supported_versions}], received {protocol_version}.',
        )

    if payload.get('ok') is False:
        detail = payload.get('error') or (payload.get('runtime') or {}).get('detail') or 'Unknown runtime failure.'
        raise error_factory(str(detail))

    result = payload.get('result')
    if not isinstance(result, dict):
        raise error_factory('Runtime returned success without a result payload.')
    return result


def install_runtime_progress_sink(sink: Callable[[dict[str, Any]], None]) -> contextvars.Token[Callable[[dict[str, Any]], None] | None]:
    return _runtime_progress_sink.set(sink)


def reset_runtime_progress_sink(token: contextvars.Token[Callable[[dict[str, Any]], None] | None]) -> None:
    _runtime_progress_sink.reset(token)


def emit_runtime_progress(progress_payload: dict[str, Any]) -> None:
    sink = _runtime_progress_sink.get()
    if sink is not None:
        sink(progress_payload)


def _optional_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _normalize_progress_request_id(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    return str(value)


class IpcProgressSink:
    """Adapts the contextvar-based runtime progress sink to the domain ProgressSink Protocol."""

    def emit(
        self,
        progress: float,
        stage: str,
        detail: str,
        *,
        done: bool = False,
        failed: bool = False,
        **kwargs: Any,
    ) -> None:
        emit_runtime_progress({
            'progress': progress,
            'stage': stage,
            'detail': detail,
            'done': done,
            'failed': failed,
            **kwargs,
        })