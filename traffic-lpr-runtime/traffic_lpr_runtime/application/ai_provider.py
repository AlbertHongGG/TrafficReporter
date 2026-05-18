from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class VisionChatImage:
    frame_id: str
    label: str
    image_base64: str


class VisionLlmProvider(Protocol):
    kind: str

    def describe(self) -> dict[str, object]: ...

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        images: list[VisionChatImage],
        timeout_s: int = 1200,
        request_metadata: dict[str, Any] | None = None,
    ) -> dict[str, object]: ...