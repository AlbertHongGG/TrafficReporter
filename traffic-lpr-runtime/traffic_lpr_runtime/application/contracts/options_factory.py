from __future__ import annotations

from typing import Any

from traffic_lpr_runtime.domain.analysis_options import AnalysisOptions
from traffic_lpr_runtime.domain.profiles import AnalysisProfileCatalog


def _to_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized if normalized else None


def build_analysis_options_from_payload(payload: dict[str, Any] | None) -> AnalysisOptions:
    request_payload = payload or {}
    developer_diagnostics_enabled = request_payload.get('enableDeveloperDiagnostics') is True
    analysis_profile_id, profile_options = AnalysisProfileCatalog.resolve_profile_options(
        _to_optional_str(request_payload.get('analysisProfileId')),
        developer_diagnostics_enabled,
    )
    raw = {
        **profile_options,
        **dict(request_payload.get('analysisOptions') or {}),
    }
    raw['analysisProfileId'] = analysis_profile_id
    raw['enableDeveloperDiagnostics'] = developer_diagnostics_enabled
    raw['persistArtifacts'] = bool(raw.get('persistArtifacts') or False) and developer_diagnostics_enabled
    return AnalysisOptions.from_dict(raw)
