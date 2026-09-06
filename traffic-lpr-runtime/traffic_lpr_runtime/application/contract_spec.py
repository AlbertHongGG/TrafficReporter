from __future__ import annotations

from typing import Any

from traffic_lpr_runtime.domain.errors import RuntimeFailure


class LprContractRegistry:
    """Self-contained runtime contract validator for dispatch validation."""

    def validate_request(self, subcommand: str, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            raise RuntimeFailure(f'{subcommand}.request must be an object.')
        if subcommand in {'scan-targets', 'analyze-frame', 'analyze-interval', 'ai-evidence'}:
            if 'sourcePath' not in payload or not isinstance(payload['sourcePath'], str):
                raise RuntimeFailure(f'{subcommand}.request.sourcePath is required.')

    def validate_response(self, subcommand: str, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            raise RuntimeFailure(f'{subcommand}.response must be an object.')
