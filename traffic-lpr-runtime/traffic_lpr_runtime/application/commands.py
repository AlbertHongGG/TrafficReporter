from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from traffic_lpr_runtime.domain.analysis_options import AnalysisOptions
from traffic_lpr_runtime.domain.errors import RuntimeFailure
from traffic_lpr_runtime.domain.value_objects import NormalizedRect


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized if normalized else None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True, slots=True)
class ScanTargetsCommand:
    source_path: str
    time_ms: int
    target_vehicle_kind: str = 'vehicle'
    marker_rect: NormalizedRect | None = None
    request_id: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> 'ScanTargetsCommand':
        source_path = str(payload.get('sourcePath') or '').strip()
        if not source_path:
            raise RuntimeFailure('ScanTargetsCommand requires a non-empty sourcePath.')
        return cls(
            source_path=source_path,
            time_ms=_safe_int(payload.get('timeMs')),
            target_vehicle_kind=str(payload.get('targetVehicleKind') or 'vehicle'),
            marker_rect=NormalizedRect.from_payload(payload.get('markerRect')),
            request_id=_optional_str(payload.get('requestId')),
        )


@dataclass(frozen=True, slots=True)
class AnalyzeFrameCommand:
    source_path: str
    time_ms: int
    target_vehicle_kind: str = 'vehicle'
    marker_rect: NormalizedRect | None = None
    selected_target_box: NormalizedRect | None = None
    country_hints: tuple[str, ...] = ()
    analysis_profile_id: str | None = None
    enable_developer_diagnostics: bool = False
    options: AnalysisOptions = field(default_factory=AnalysisOptions)
    request_id: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> 'AnalyzeFrameCommand':
        source_path = str(payload.get('sourcePath') or '').strip()
        if not source_path:
            raise RuntimeFailure('AnalyzeFrameCommand requires a non-empty sourcePath.')
        options = AnalysisOptions.from_payload(payload).for_interactive_frame()
        country_hints = tuple(str(h) for h in (payload.get('countryHints') or []) if str(h).strip())
        return cls(
            source_path=source_path,
            time_ms=_safe_int(payload.get('timeMs')),
            target_vehicle_kind=str(payload.get('targetVehicleKind') or 'vehicle'),
            marker_rect=NormalizedRect.from_payload(payload.get('markerRect')),
            selected_target_box=NormalizedRect.from_payload(payload.get('selectedTargetBox')),
            country_hints=country_hints,
            analysis_profile_id=_optional_str(payload.get('analysisProfileId')),
            enable_developer_diagnostics=payload.get('enableDeveloperDiagnostics') is True,
            options=options,
            request_id=_optional_str(payload.get('requestId')),
        )


@dataclass(frozen=True, slots=True)
class AnalyzeIntervalCommand:
    source_path: str
    start_ms: int
    end_ms: int
    anchor_time_ms: int
    target_vehicle_kind: str = 'vehicle'
    marker_rect: NormalizedRect | None = None
    selected_target_box: NormalizedRect | None = None
    country_hints: tuple[str, ...] = ()
    analysis_profile_id: str | None = None
    enable_developer_diagnostics: bool = False
    selected_target_track_id: str | None = None
    ground_truth_frames: tuple[dict[str, Any], ...] = ()
    options: AnalysisOptions = field(default_factory=AnalysisOptions)
    request_id: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> 'AnalyzeIntervalCommand':
        source_path = str(payload.get('sourcePath') or '').strip()
        if not source_path:
            raise RuntimeFailure('AnalyzeIntervalCommand requires a non-empty sourcePath.')

        interval = payload.get('interval') or {}
        start_ms = _safe_int(interval.get('startMs'))
        end_ms = _safe_int(interval.get('endMs'))
        anchor_time_ms = _safe_int(payload.get('anchorTimeMs'))

        selected_target_box = NormalizedRect.from_payload(payload.get('selectedTargetBox'))
        if selected_target_box is None:
            raise RuntimeFailure('Range analysis requires a selected target on the anchor frame.')
        if anchor_time_ms < start_ms or anchor_time_ms > end_ms:
            raise RuntimeFailure('Range analysis requires the selected target anchor to stay inside the requested interval.')

        options = AnalysisOptions.from_payload(payload)
        country_hints = tuple(str(h) for h in (payload.get('countryHints') or []) if str(h).strip())
        gt = payload.get('groundTruthFrames')
        ground_truth_frames = tuple(gt) if isinstance(gt, list) else ()

        return cls(
            source_path=source_path,
            start_ms=start_ms,
            end_ms=end_ms,
            anchor_time_ms=anchor_time_ms,
            target_vehicle_kind=str(payload.get('targetVehicleKind') or 'vehicle'),
            marker_rect=NormalizedRect.from_payload(payload.get('markerRect')),
            selected_target_box=selected_target_box,
            country_hints=country_hints,
            analysis_profile_id=_optional_str(payload.get('analysisProfileId')),
            enable_developer_diagnostics=payload.get('enableDeveloperDiagnostics') is True,
            selected_target_track_id=_optional_str(payload.get('selectedTargetTrackId')),
            ground_truth_frames=ground_truth_frames,
            options=options,
            request_id=_optional_str(payload.get('requestId')),
            raw_payload=dict(payload),
        )


@dataclass(frozen=True, slots=True)
class AiEvidenceCommand:
    source_path: str
    start_ms: int
    end_ms: int
    anchor_time_ms: int | None
    description: str
    target_vehicle_kind: str = 'vehicle'
    plate_number_hint: str | None = None
    compression_mode: str = 'compact'
    coarse_sample_interval_ms: int | None = None
    fine_window_ms: int | None = None
    fine_sample_interval_ms: int | None = None
    max_keyframes: int | None = None
    analysis_profile_id: str | None = None
    enable_developer_diagnostics: bool = False
    request_id: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> 'AiEvidenceCommand':
        source_path = str(payload.get('sourcePath') or '').strip()
        if not source_path:
            raise RuntimeFailure('AiEvidenceCommand requires a non-empty sourcePath.')

        interval = payload.get('interval') or {}
        start_ms = _safe_int(interval.get('startMs'))
        end_ms = _safe_int(interval.get('endMs'))
        anchor_time_ms = payload.get('anchorTimeMs')
        resolved_anchor_ms = _safe_int(anchor_time_ms) if anchor_time_ms is not None else None

        description = str(payload.get('description') or '').strip()
        if not description:
            raise RuntimeFailure('AI evidence analysis requires a descriptive target vehicle prompt.')

        return cls(
            source_path=source_path,
            start_ms=start_ms,
            end_ms=end_ms,
            anchor_time_ms=resolved_anchor_ms,
            description=description,
            target_vehicle_kind=str(payload.get('targetVehicleKind') or 'vehicle'),
            plate_number_hint=_optional_str(payload.get('plateNumberHint')),
            compression_mode=str(payload.get('compressionMode') or 'compact'),
            coarse_sample_interval_ms=payload.get('coarseSampleIntervalMs'),
            fine_window_ms=payload.get('fineWindowMs'),
            fine_sample_interval_ms=payload.get('fineSampleIntervalMs'),
            max_keyframes=payload.get('maxKeyframes'),
            analysis_profile_id=_optional_str(payload.get('analysisProfileId')),
            enable_developer_diagnostics=payload.get('enableDeveloperDiagnostics') is True,
            request_id=_optional_str(payload.get('requestId')),
            raw_payload=dict(payload),
        )
