from __future__ import annotations

import re


def normalize_plate_text(value: str | None) -> str:
    if not value:
        return ''
    return re.sub(r'[^A-Z0-9]', '', value.upper())


def levenshtein_distance(left: str | None, right: str | None) -> int:
    source = normalize_plate_text(left)
    target = normalize_plate_text(right)
    if source == target:
        return 0
    if not source:
        return len(target)
    if not target:
        return len(source)

    previous = list(range(len(target) + 1))
    for source_index, source_char in enumerate(source, start=1):
        current = [source_index]
        for target_index, target_char in enumerate(target, start=1):
            insertion_cost = current[target_index - 1] + 1
            deletion_cost = previous[target_index] + 1
            substitution_cost = previous[target_index - 1] + (0 if source_char == target_char else 1)
            current.append(min(insertion_cost, deletion_cost, substitution_cost))
        previous = current
    return previous[-1]


def character_error_rate(actual: str | None, expected: str | None) -> float:
    expected_text = normalize_plate_text(expected)
    if not expected_text:
        return 0.0 if not normalize_plate_text(actual) else 1.0
    return levenshtein_distance(actual, expected_text) / max(len(expected_text), 1)
