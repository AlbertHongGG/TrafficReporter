from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_AI_PROVIDER = 'ollama'
DEFAULT_OLLAMA_BASE_URL = 'https://lacresha-posological-steven.ngrok-free.dev'
DEFAULT_OLLAMA_MODEL = 'qwen3.6:35b'
DEFAULT_OLLAMA_TIMEOUT_S = 1200
DEFAULT_OLLAMA_RETRY_ATTEMPTS = 1
DEFAULT_OLLAMA_RETRY_DELAY_S = 1.0
DEFAULT_AI_EVIDENCE_MAX_KEYFRAMES = 8
DEFAULT_AI_EVIDENCE_COARSE_SAMPLE_EVERY_MS = 4000
DEFAULT_AI_EVIDENCE_FINE_SAMPLE_EVERY_MS = 500
DEFAULT_AI_EVIDENCE_FINE_WINDOW_PADDING_MS = 2000

_ENV_LOADED = False


@dataclass(frozen=True)
class OllamaSettings:
    base_url: str
    model: str
    timeout_s: int
    retry_attempts: int
    retry_delay_s: float


@dataclass(frozen=True)
class AiEvidenceSettings:
    max_keyframes: int
    coarse_sample_every_ms: int
    fine_sample_every_ms: int
    fine_window_padding_ms: int


@dataclass(frozen=True)
class RuntimeSettings:
    ai_provider: str
    ollama: OllamaSettings
    ai_evidence: AiEvidenceSettings


def load_runtime_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    candidates: list[Path] = []
    for candidate in [Path.cwd() / '.env', *[parent / '.env' for parent in Path(__file__).resolve().parents[:4]]]:
        resolved = candidate.resolve(strict=False)
        if resolved not in candidates:
            candidates.append(resolved)

    for candidate in candidates:
        _load_env_file(candidate)

    _ENV_LOADED = True


def get_runtime_settings() -> RuntimeSettings:
    load_runtime_env()
    return RuntimeSettings(
        ai_provider=_read_string('TRAFFIC_AI_PROVIDER', DEFAULT_AI_PROVIDER).strip().lower() or DEFAULT_AI_PROVIDER,
        ollama=OllamaSettings(
            base_url=_read_string('TRAFFIC_OLLAMA_URL', DEFAULT_OLLAMA_BASE_URL).rstrip('/') or DEFAULT_OLLAMA_BASE_URL,
            model=_read_string('TRAFFIC_OLLAMA_MODEL', DEFAULT_OLLAMA_MODEL),
            timeout_s=_read_int('TRAFFIC_OLLAMA_TIMEOUT_S', DEFAULT_OLLAMA_TIMEOUT_S, minimum=30),
            retry_attempts=_read_int('TRAFFIC_OLLAMA_RETRY_ATTEMPTS', DEFAULT_OLLAMA_RETRY_ATTEMPTS, minimum=0),
            retry_delay_s=_read_float('TRAFFIC_OLLAMA_RETRY_DELAY_S', DEFAULT_OLLAMA_RETRY_DELAY_S, minimum=0.0),
        ),
        ai_evidence=AiEvidenceSettings(
            max_keyframes=_read_int('TRAFFIC_AI_EVIDENCE_MAX_KEYFRAMES', DEFAULT_AI_EVIDENCE_MAX_KEYFRAMES, minimum=8),
            coarse_sample_every_ms=_read_int(
                'TRAFFIC_AI_EVIDENCE_COARSE_SAMPLE_EVERY_MS',
                DEFAULT_AI_EVIDENCE_COARSE_SAMPLE_EVERY_MS,
                minimum=1000,
            ),
            fine_sample_every_ms=_read_int(
                'TRAFFIC_AI_EVIDENCE_FINE_SAMPLE_EVERY_MS',
                DEFAULT_AI_EVIDENCE_FINE_SAMPLE_EVERY_MS,
                minimum=80,
            ),
            fine_window_padding_ms=_read_int(
                'TRAFFIC_AI_EVIDENCE_FINE_WINDOW_PADDING_MS',
                DEFAULT_AI_EVIDENCE_FINE_WINDOW_PADDING_MS,
                minimum=1000,
            ),
        ),
    )


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return

    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].strip()
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = _strip_quotes(value.strip())


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _read_string(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None:
        return default
    trimmed = value.strip()
    return trimmed or default


def _read_int(name: str, default: int, *, minimum: int) -> int:
    value = os.environ.get(name)
    try:
        parsed = int(value) if value is not None and value != '' else default
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


def _read_float(name: str, default: float, *, minimum: float) -> float:
    value = os.environ.get(name)
    try:
        parsed = float(value) if value is not None and value != '' else default
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)