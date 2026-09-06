from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from traffic_lpr_runtime.infrastructure.storage import RuntimeStorageLayout


def _catalog_path() -> Path:
    return RuntimeStorageLayout.discover().repo_root / 'src' / 'shared' / 'config' / 'lpr-analysis-profiles.json'


@lru_cache(maxsize=1)
def load_analysis_profile_catalog() -> dict[str, Any]:
    fallback = {
        'version': 1,
        'defaultProfileId': 'precision',
        'developerDiagnosticsOptions': {},
        'profiles': [],
    }
    catalog_file = _catalog_path()
    if not catalog_file.exists():
        return fallback
    try:
        payload = json.loads(catalog_file.read_text(encoding='utf-8'))
    except Exception:
        return fallback
    if not isinstance(payload, dict):
        return fallback
    if not isinstance(payload.get('profiles'), list):
        return fallback
    return payload


def resolve_analysis_profile_options(
    profile_id: str | None,
    enable_developer_diagnostics: bool,
) -> tuple[str, dict[str, Any]]:
    catalog = load_analysis_profile_catalog()
    profiles = {
        str(profile.get('id')): profile
        for profile in catalog.get('profiles') or []
        if isinstance(profile, dict) and isinstance(profile.get('id'), str)
    }
    default_profile_id = str(catalog.get('defaultProfileId') or 'precision')
    resolved_profile_id = profile_id if profile_id in profiles else default_profile_id
    base_options = dict((profiles.get(resolved_profile_id) or {}).get('options') or {})
    if enable_developer_diagnostics:
        base_options = {
            **base_options,
            **dict(catalog.get('developerDiagnosticsOptions') or {}),
        }
    return resolved_profile_id, base_options
