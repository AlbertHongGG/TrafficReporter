from __future__ import annotations

from typing import Any, Callable

from traffic_lpr_runtime.application.commands import ScanTargetsCommand
from traffic_lpr_runtime.domain.interfaces import FrameReader, TargetDetector
from traffic_lpr_runtime.domain.models import TrackedRegion
from traffic_lpr_runtime.domain.value_objects import NormalizedRect


class ScanTargetsUseCase:
    name = 'scan-targets'

    def __init__(
        self,
        ensure_ready: Callable[[], None],
        status: Callable[[], dict[str, Any]],
        frame_reader: FrameReader,
        detect_targets: TargetDetector | Callable[[Any, int, str, NormalizedRect | None], list[TrackedRegion]],
    ) -> None:
        self._ensure_ready = ensure_ready
        self._status = status
        self._frame_reader = frame_reader
        self._detect_targets = (
            detect_targets.detect_targets if hasattr(detect_targets, 'detect_targets') else detect_targets
        )

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        command = ScanTargetsCommand.from_payload(payload)
        frame = self._frame_reader.read_frame(command.source_path, command.time_ms)
        detections = self._detect_targets(
            frame,
            command.time_ms,
            command.target_vehicle_kind,
            command.marker_rect,
        )
        return {
            'detections': [detection.to_payload() for detection in detections],
            'runtime': self._status(),
        }
