from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class VisionChatImage:
    frame_id: str
    label: str
    image_base64: str


class VisionLlmProvider(Protocol):
    kind: str

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        images: list[VisionChatImage],
        timeout_s: int = 1200,
    ) -> dict[str, object]: ...