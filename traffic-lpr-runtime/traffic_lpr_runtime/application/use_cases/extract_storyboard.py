from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Callable, Sequence

from traffic_lpr_runtime.domain.errors import RuntimeFailure
from traffic_lpr_runtime.domain.interfaces import FrameReader
from traffic_lpr_runtime.domain.value_objects import NormalizedRect, crop_image
from traffic_lpr_runtime.infrastructure.storage import RuntimeStorageLayout


def format_time_label(time_ms: int) -> str:
    total_seconds = max(0, time_ms) // 1000
    ms = max(0, time_ms) % 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:02d}.{ms:03d}"


class ExtractStoryboardUseCase:
    name = "sample-storyboard-frames"

    def __init__(
        self,
        ensure_ready: Callable[[], None],
        runtime_root: Callable[[], Path],
        frame_reader: FrameReader,
        dependencies: Any,
        storage: RuntimeStorageLayout | None = None,
    ) -> None:
        self._ensure_ready = ensure_ready
        self._runtime_root = runtime_root
        self._frame_reader = frame_reader
        self._dependencies = dependencies
        self._storage = storage

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        source_path = str(payload.get("sourcePath") or "").strip()
        if not source_path:
            raise RuntimeFailure("sample-storyboard-frames requires a non-empty sourcePath.")

        duration_ms = self._probe_duration_ms(source_path)
        times_ms = self._resolve_sample_times(payload, duration_ms)
        if not times_ms:
            raise RuntimeFailure("sample-storyboard-frames produced no sample timestamps.")

        output_dir_str = payload.get("outputDir")
        if output_dir_str:
            output_dir = Path(output_dir_str)
        else:
            request_id = str(payload.get("requestId") or "storyboard")
            storage = self._storage or getattr(self._dependencies, 'storage', None) or RuntimeStorageLayout.discover(self._runtime_root())
            output_dir = storage.run_child(request_id, "storyboard")

        output_dir.mkdir(parents=True, exist_ok=True)
        prefix = str(payload.get("prefix") or "frame")
        show_header = bool(payload.get("showHeader", True))
        max_dimension = int(payload.get("maxDimension") or 1280)

        rendered_frames: list[dict[str, Any]] = []
        cv2 = self._dependencies.cv2

        for index, time_ms in enumerate(times_ms):
            frame = self._frame_reader.read_frame(source_path, time_ms)
            rendered, width, height = self._prepare_frame(
                frame=frame,
                title=f"{prefix}-{index:03d}",
                subtitle=f"T+{format_time_label(time_ms)}",
                show_header=show_header,
                max_dimension=max_dimension,
                cv2=cv2,
            )
            image_path = output_dir / f"{prefix}-{index:03d}.jpg"
            ok, encoded = cv2.imencode(".jpg", rendered, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
            if not ok:
                raise RuntimeFailure(f"Unable to encode storyboard image at {image_path}.")
            image_path.write_bytes(encoded.tobytes())

            rendered_frames.append({
                "frameId": f"{prefix}-{index:03d}",
                "timeMs": time_ms,
                "sequenceIndex": index,
                "label": f"{prefix}-{index:03d} @ T+{format_time_label(time_ms)}",
                "imagePath": str(image_path),
                "frameWidth": width,
                "frameHeight": height,
            })

        return {
            "sourcePath": source_path,
            "durationMs": duration_ms,
            "outputDir": str(output_dir),
            "frames": rendered_frames,
        }

    def _resolve_sample_times(self, payload: dict[str, Any], duration_ms: int) -> list[int]:
        explicit_times = payload.get("timesMs")
        if isinstance(explicit_times, list) and explicit_times:
            return sorted(set(int(t) for t in explicit_times if isinstance(t, (int, float))))

        start_ms = max(0, int(payload.get("startMs") or 0))
        end_ms = min(duration_ms, int(payload.get("endMs") or duration_ms))
        if end_ms <= start_ms:
            end_ms = min(duration_ms, start_ms + 1000)

        step_ms = max(100, int(payload.get("sampleEveryMs") or 1000))
        max_samples = max(2, int(payload.get("maxSamples") or 30))

        count = min(max_samples, max(2, math.ceil((end_ms - start_ms) / step_ms) + 1))
        actual_step = (end_ms - start_ms) / float(count - 1) if count > 1 else step_ms
        return [int(round(start_ms + i * actual_step)) for i in range(count)]

    def _probe_duration_ms(self, source_path: str) -> int:
        cv2 = self._dependencies.cv2
        capture = cv2.VideoCapture(source_path)
        try:
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
            duration = int(round((frame_count / fps) * 1000)) if fps > 0 and frame_count > 0 else 0
            return max(1000, duration)
        finally:
            capture.release()

    def _prepare_frame(
        self,
        frame: Any,
        *,
        title: str,
        subtitle: str,
        show_header: bool,
        max_dimension: int,
        cv2: Any,
    ) -> tuple[Any, int, int]:
        image = frame.copy()
        height, width = image.shape[:2]
        if show_header:
            header_w = min(width, 520)
            cv2.rectangle(image, (0, 0), (header_w, 84), (8, 8, 8), -1)
            cv2.putText(image, title, (18, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.putText(image, subtitle, (18, 66), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (222, 222, 222), 2, cv2.LINE_AA)

        longest_side = max(width, height)
        if longest_side > max_dimension:
            scale = float(max_dimension) / float(longest_side)
            image = cv2.resize(image, (int(round(width * scale)), int(round(height * scale))), interpolation=cv2.INTER_AREA)
            height, width = image.shape[:2]
        return image, width, height
