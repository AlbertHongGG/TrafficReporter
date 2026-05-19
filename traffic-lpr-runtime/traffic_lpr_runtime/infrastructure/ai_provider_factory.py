from __future__ import annotations

from pathlib import Path

from traffic_lpr_runtime.application.ai_provider import VisionLlmProvider
from traffic_lpr_runtime.domain.errors import RuntimeFailure
from traffic_lpr_runtime.infrastructure.ai_logging import JsonFileAiCallLogger, LoggingVisionLlmProvider
from traffic_lpr_runtime.infrastructure.ollama_provider import OllamaVisionProvider
from traffic_lpr_runtime.infrastructure.runtime_settings import DEFAULT_AI_PROVIDER, get_runtime_settings


def build_ai_provider(*, runtime_root: Path) -> VisionLlmProvider:
    settings = get_runtime_settings()
    provider_name = settings.ai_provider
    if provider_name == 'ollama':
        provider: VisionLlmProvider = OllamaVisionProvider()
    else:
        raise RuntimeFailure(f'Unsupported AI provider: {provider_name}.')

    return LoggingVisionLlmProvider(
        inner=provider,
        logger=JsonFileAiCallLogger(runtime_root / '.runtime' / 'ai-logs'),
    )