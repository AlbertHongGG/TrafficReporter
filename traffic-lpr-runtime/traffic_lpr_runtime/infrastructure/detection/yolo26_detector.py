from __future__ import annotations

from typing import Any

from traffic_lpr_runtime.domain.models import TrackedRegion
from traffic_lpr_runtime.domain.value_objects import NormalizedRect, clamp, crop_image
from traffic_lpr_runtime.infrastructure.models.hub import DEFAULT_VEHICLE_MODEL_NAME, ModelHub

COCO_VEHICLE_CLASSES = {
    'car': 2,
    'motorcycle': 3,
    'bus': 5,
    'truck': 7,
}


class Yolo26TargetDetector:
    """Detects vehicles using Ultralytics YOLO26 models."""

    def __init__(self, models: ModelHub, model_name: str = DEFAULT_VEHICLE_MODEL_NAME) -> None:
        self._models = models
        self._model_name = model_name

    def load_model(self) -> Any:
        return self._models.load_vehicle_model(self._model_name)

    def vehicle_classes_for_kind(self, vehicle_kind: str) -> list[int]:
        if vehicle_kind == 'motorcycle':
            return [COCO_VEHICLE_CLASSES['motorcycle']]
        if vehicle_kind == 'car':
            return [COCO_VEHICLE_CLASSES['car']]
        if vehicle_kind == 'truck':
            return [COCO_VEHICLE_CLASSES['truck']]
        if vehicle_kind == 'bus':
            return [COCO_VEHICLE_CLASSES['bus']]
        return [
            COCO_VEHICLE_CLASSES['car'],
            COCO_VEHICLE_CLASSES['motorcycle'],
            COCO_VEHICLE_CLASSES['bus'],
            COCO_VEHICLE_CLASSES['truck'],
        ]

    def detect_targets(
        self,
        frame: Any,
        time_ms: int,
        vehicle_kind: str,
        marker_rect: NormalizedRect | None,
    ) -> list[TrackedRegion]:
        if frame is None or getattr(frame, 'size', 0) == 0:
            return []

        model = self.load_model()
        inference_device = self._models.dependencies.preferred_torch_device()
        working_frame = crop_image(frame, marker_rect) if marker_rect else frame
        if working_frame is None or getattr(working_frame, 'size', 0) == 0:
            return []

        result = model(
            working_frame,
            classes=self.vehicle_classes_for_kind(vehicle_kind),
            verbose=False,
            conf=0.18,
            device=inference_device,
        )[0]
        frame_height, frame_width = working_frame.shape[:2]
        names = getattr(model, 'names', {})

        detections: list[TrackedRegion] = []
        if getattr(result, 'boxes', None) is None:
            return detections

        for index, box in enumerate(result.boxes):
            xyxy = box.xyxy[0].tolist()
            normalized_box = NormalizedRect.from_xyxy(
                float(xyxy[0]),
                float(xyxy[1]),
                float(xyxy[2]),
                float(xyxy[3]),
                frame_width,
                frame_height,
            )
            if marker_rect:
                normalized_box = self._translate_rect_from_crop(normalized_box, marker_rect)

            confidence = float(box.conf[0].item())
            class_id = int(box.cls[0].item())
            detections.append(
                TrackedRegion(
                    id=f'target-{time_ms}-{index}',
                    time_ms=int(time_ms),
                    box=normalized_box,
                    confidence=confidence,
                    class_name=str(names.get(class_id, class_id)),
                )
            )

        detections.sort(key=lambda candidate: candidate.confidence, reverse=True)
        return detections

    @staticmethod
    def _translate_rect_from_crop(rect: NormalizedRect, crop_rect: NormalizedRect) -> NormalizedRect:
        x = clamp(crop_rect.x + (rect.x * crop_rect.width), 0.0, 1.0)
        y = clamp(crop_rect.y + (rect.y * crop_rect.height), 0.0, 1.0)
        width = clamp(rect.width * crop_rect.width, 0.0, 1.0 - x)
        height = clamp(rect.height * crop_rect.height, 0.0, 1.0 - y)
        return NormalizedRect(x=x, y=y, width=width, height=height)
