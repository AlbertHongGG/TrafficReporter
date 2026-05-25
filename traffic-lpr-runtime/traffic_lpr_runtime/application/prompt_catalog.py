from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from string import Template
from typing import Any

from traffic_lpr_runtime.prompts.ai_evidence import (
    COARSE_SYSTEM_PROMPT,
    COARSE_USER_PROMPT_TEMPLATE,
    FINE_SYSTEM_PROMPT,
    FINE_USER_PROMPT_TEMPLATE,
    TARGET_SYSTEM_PROMPT,
    TARGET_USER_PROMPT_TEMPLATE,
)


@dataclass(frozen=True, slots=True)
class AiEvidencePromptStage:
    system_prompt: str
    user_prompt_template: str

    def render_user_prompt(self, **values: Any) -> str:
        return Template(self.user_prompt_template).substitute(**values)


@dataclass(frozen=True, slots=True)
class AiEvidencePromptCatalog:
    coarse: AiEvidencePromptStage
    fine: AiEvidencePromptStage
    target: AiEvidencePromptStage


@lru_cache(maxsize=1)
def load_ai_evidence_prompt_catalog() -> AiEvidencePromptCatalog:
    return AiEvidencePromptCatalog(
        coarse=AiEvidencePromptStage(
            system_prompt=COARSE_SYSTEM_PROMPT,
            user_prompt_template=COARSE_USER_PROMPT_TEMPLATE,
        ),
        fine=AiEvidencePromptStage(
            system_prompt=FINE_SYSTEM_PROMPT,
            user_prompt_template=FINE_USER_PROMPT_TEMPLATE,
        ),
        target=AiEvidencePromptStage(
            system_prompt=TARGET_SYSTEM_PROMPT,
            user_prompt_template=TARGET_USER_PROMPT_TEMPLATE,
        ),
    )