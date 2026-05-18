from __future__ import annotations

import os
from pathlib import Path

from traffic_lpr_runtime.application.ai_provider import VisionLlmProvider
from traffic_lpr_runtime.domain.errors import RuntimeFailure
from traffic_lpr_runtime.infrastructure.ai_logging import JsonFileAiCallLogger, LoggingVisionLlmProvider
from traffic_lpr_runtime.infrastructure.ollama_provider import OllamaVisionProvider


DEFAULT_AI_PROVIDER = 'ollama'


def build_ai_provider(*, runtime_root: Path) -> VisionLlmProvider:
    provider_name = (os.environ.get('TRAFFIC_AI_PROVIDER') or DEFAULT_AI_PROVIDER).strip().lower() or DEFAULT_AI_PROVIDER
    if provider_name == 'ollama':
        provider: VisionLlmProvider = OllamaVisionProvider()
    else:
        raise RuntimeFailure(f'Unsupported AI provider: {provider_name}.')

    return LoggingVisionLlmProvider(
        inner=provider,
        logger=JsonFileAiCallLogger(runtime_root / '.runtime' / 'ai-logs'),
    )