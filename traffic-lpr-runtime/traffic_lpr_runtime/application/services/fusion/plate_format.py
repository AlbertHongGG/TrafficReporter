from __future__ import annotations

from traffic_lpr_runtime.domain.text import normalize_plate_text


def _looks_like_taiwan_long_plate(text: str) -> bool:
    normalized = normalize_plate_text(text)
    return len(normalized) == 7 and normalized[:3].isalpha() and normalized[-4:].isdigit()


def _looks_like_taiwan_short_plate(text: str) -> bool:
    normalized = normalize_plate_text(text)
    return len(normalized) == 6 and normalized[:2].isalpha() and normalized[-4:].isdigit()


def _plate_format_score(text: str | None, country_hints: list[str]) -> float:
    normalized = normalize_plate_text(text)
    if not normalized:
        return 0.0
    if _uses_taiwan_hint(country_hints):
        if len(normalized) < 5 or len(normalized) > 7:
            return 0.2
        if any(character in {'I', 'O', 'Q'} for character in normalized):
            return 0.55
        if normalized[:3].isalpha() and normalized[-4:].isdigit() and len(normalized) == 7:
            return 1.0
        if normalized[:2].isalpha() and normalized[-4:].isdigit() and len(normalized) == 6:
            return 0.94
        if normalized[:4].isalpha() and normalized[-3:].isdigit() and len(normalized) == 7:
            return 0.9
        if normalized[:3].isdigit() and normalized[-4:].isalpha() and len(normalized) == 7:
            return 0.82
        if any(character.isalpha() for character in normalized) and any(character.isdigit() for character in normalized):
            return 0.58
        return 0.35
    return 1.0 if 5 <= len(normalized) <= 8 else 0.5


def _uses_taiwan_hint(country_hints: list[str]) -> bool:
    return any(str(hint).upper() in {'TW', 'TWN', 'TAIWAN'} for hint in country_hints)
