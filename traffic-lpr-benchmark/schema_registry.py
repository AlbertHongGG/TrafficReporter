from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCHEMA_ROOT = Path(__file__).resolve().parent.parent / 'schemas'


def load_shared_schema(*parts: str) -> dict[str, Any]:
    path = SCHEMA_ROOT.joinpath(*parts)
    return json.loads(path.read_text(encoding='utf-8'))
