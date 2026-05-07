from __future__ import annotations

import re


def normalize_plate_text(value: str | None) -> str:
    if not value:
        return ''
    return re.sub(r'[^A-Z0-9]', '', value.upper())
