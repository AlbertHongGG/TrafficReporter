from __future__ import annotations

import re

from traffic_lpr_runtime.domain.text import normalize_plate_text


class TaiwanPlatePrior:
    """Evaluates Taiwan license plate prior probabilities based on formatting heuristics."""

    TAIWAN_REGION_CODES = {'TW', 'TWN', 'TAIWAN'}

    @classmethod
    def is_applicable(cls, country_hints: list[str] | None, country_code: str | None) -> bool:
        if country_code and country_code.upper() in cls.TAIWAN_REGION_CODES:
            return True
        if country_hints:
            return any(hint.upper() in cls.TAIWAN_REGION_CODES for hint in country_hints if hint)
        return False

    @staticmethod
    def preferred_country_hint(country_hints: list[str] | None) -> str | None:
        return country_hints[0] if country_hints else None

    @staticmethod
    def calculate_prior(text: str) -> float:
        normalized = normalize_plate_text(text)
        if not normalized:
            return 0.65
        if re.fullmatch(r'[A-Z]{2,4}[0-9]{2,4}', normalized):
            return 1.12
        if re.fullmatch(r'[0-9]{2,4}[A-Z]{2,4}', normalized):
            return 1.08
        if (
            5 <= len(normalized) <= 7
            and any(char.isalpha() for char in normalized)
            and any(char.isdigit() for char in normalized)
        ):
            return 1.03
        return 0.88
