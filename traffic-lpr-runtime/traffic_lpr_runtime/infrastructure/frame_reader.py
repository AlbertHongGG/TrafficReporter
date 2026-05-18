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
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if fps > 0 and frame_count > 0:
                last_frame_index = max(0, frame_count - 1)
                last_frame_time_ms = int(max(0, round((last_frame_index / fps) * 1000)))
                clamped_time_ms = min(max(0, int(time_ms)), last_frame_time_ms)
            else:
                last_frame_index = 0
                clamped_time_ms = max(0, int(time_ms))

            capture.set(cv2.CAP_PROP_POS_MSEC, float(clamped_time_ms))
            ok, frame = capture.read()
            if not ok or frame is None:
                fallback_fps = fps or float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
                frame_index = max(0, int(round((clamped_time_ms / 1000.0) * fallback_fps)))
                if frame_count > 0:
                    frame_index = min(frame_index, last_frame_index)
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ok, frame = capture.read()
            if not ok or frame is None:
                raise RuntimeFailure(f'Unable to decode frame at {time_ms}ms from {source_path}.')
            return frame
        finally:
            capture.release()
