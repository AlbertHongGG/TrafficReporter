from __future__ import annotations

from traffic_lpr_runtime.domain.errors import RuntimeFailure

from .dependencies import DependencyRegistry


class OpenCvFrameReader:
    def __init__(self, dependencies: DependencyRegistry) -> None:
        self._dependencies = dependencies

    def read_frame(self, source_path: str, time_ms: int):
        self._dependencies.ensure_ready()
        cv2 = self._dependencies.cv2
        capture = cv2.VideoCapture(source_path)
        try:
            capture.set(cv2.CAP_PROP_POS_MSEC, float(max(0, time_ms)))
            ok, frame = capture.read()
            if not ok or frame is None:
                fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
                frame_index = max(0, int(round((max(0, time_ms) / 1000.0) * fps)))
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ok, frame = capture.read()
            if not ok or frame is None:
                raise RuntimeFailure(f'Unable to decode frame at {time_ms}ms from {source_path}.')
            return frame
        finally:
            capture.release()
