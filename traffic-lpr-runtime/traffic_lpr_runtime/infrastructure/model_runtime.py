from __future__ import annotations

import importlib
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from traffic_lpr_runtime.domain.errors import RuntimeFailure
from traffic_lpr_runtime.domain.models import PlateCandidate, TrackedRegion
from traffic_lpr_runtime.domain.text import normalize_plate_text
from traffic_lpr_runtime.domain.value_objects import NormalizedRect, clamp, crop_image

from .dependencies import DependencyRegistry
from .image_processing import QualityScorer


COCO_VEHICLE_CLASSES = {
    'car': 2,
    'motorcycle': 3,
    'bus': 5,
    'truck': 7,
}

VEHICLE_MODEL_NAMES = (
    'yolo26x.pt',
    'yolo11x.pt',
    'yolov8x.pt',
    'yolo26s.pt',
    'yolo11s.pt',
    'yolov8s.pt',
)


class ModelRegistry:
    def __init__(self, dependencies: DependencyRegistry) -> None:
        self._dependencies = dependencies
        self._vehicle_model: Any | None = None
        self._alpr_model: Any | None = None

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

    def load_vehicle_model(self) -> Any:
        if self._vehicle_model is not None:
            return self._vehicle_model

        self._dependencies.ensure_ready()
        yolo_type = getattr(self._dependencies.ultralytics, 'YOLO', None)
        if yolo_type is None:
            raise RuntimeFailure('ultralytics.YOLO is unavailable in the configured Python environment.')

        last_error: Exception | None = None
        preferred_device = self._dependencies.preferred_torch_device()
        for model_name in VEHICLE_MODEL_NAMES:
            try:
                self._vehicle_model = yolo_type(str(self._ensure_vehicle_model_path(model_name)))
                move_to = getattr(self._vehicle_model, 'to', None)
                if callable(move_to):
                    move_to(preferred_device)
                return self._vehicle_model
            except Exception as error:
                last_error = error

        raise RuntimeFailure(f'Unable to load a vehicle detector model: {last_error}')

    @property
    def dependencies(self) -> DependencyRegistry:
        return self._dependencies

    def load_alpr_model(self) -> Any:
        if self._alpr_model is not None:
            return self._alpr_model

        self._dependencies.ensure_ready()
        alpr_type = getattr(self._dependencies.fast_alpr, 'ALPR', None)
        if alpr_type is None:
            raise RuntimeFailure('fast_alpr.ALPR is unavailable in the configured Python environment.')

        detector_providers = self._onnx_providers()
        ocr_device = self._onnx_device()
        last_error: Exception | None = None
        for detector_model in [
            'yolo-v9-t-384-license-plate-end2end',
            'yolo-v9-t-640-license-plate-end2end',
        ]:
            try:
                self._alpr_model = alpr_type(
                    detector_model=detector_model,
                    detector_providers=detector_providers,
                    ocr_model='cct-xs-v2-global-model',
                    ocr_device=ocr_device,
                    ocr_providers=detector_providers,
                )
                return self._alpr_model
            except Exception as error:
                last_error = error

        raise RuntimeFailure(f'Unable to load the ALPR detector/OCR stack: {last_error}')

    def _onnx_device(self) -> str:
        return 'cuda' if self._dependencies.torch_cuda_available() else 'cpu'

    def _onnx_providers(self) -> list[str]:
        if self._dependencies.torch_cuda_available():
            return ['CUDAExecutionProvider', 'CPUExecutionProvider']
        return ['CPUExecutionProvider']

    def _ensure_vehicle_model_path(self, model_name: str) -> Path:
        model_path = self._dependencies.models_root() / model_name
        if model_path.exists() and model_path.stat().st_size > 0:
            return model_path

        model_path.parent.mkdir(parents=True, exist_ok=True)
        utils_module = importlib.import_module('ultralytics.utils')
        downloads_module = importlib.import_module('ultralytics.utils.downloads')
        assets_url = getattr(utils_module, 'ASSETS_URL', None)
        safe_download = getattr(downloads_module, 'safe_download', None)

        if not assets_url or not callable(safe_download):
            raise RuntimeFailure(f'Unable to resolve the Ultralytics downloader for {model_name}.')

        safe_download(url=f'{assets_url}/{model_name}', file=model_path, unzip=False)
        if model_path.exists() and model_path.stat().st_size > 0:
            return model_path

        raise RuntimeFailure(f'Unable to download the detector model {model_name} into {model_path.parent}.')


class UltralyticsTargetDetector:
    def __init__(self, models: ModelRegistry) -> None:
        self._models = models

    def detect_targets(
        self,
        frame: Any,
        time_ms: int,
        vehicle_kind: str,
        marker_rect: NormalizedRect | None,
    ) -> list[TrackedRegion]:
        model = self._models.load_vehicle_model()
        inference_device = self._models.dependencies.preferred_torch_device()
        working_frame = crop_image(frame, marker_rect) if marker_rect else frame
        if working_frame is None or getattr(working_frame, 'size', 0) == 0:
            return []

        result = model(
            working_frame,
            classes=self._models.vehicle_classes_for_kind(vehicle_kind),
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
                normalized_box = _translate_rect_from_crop(normalized_box, marker_rect)

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


class FastAlprPlateRecognizer:
    def __init__(
        self,
        models: ModelRegistry,
        quality_scorer: QualityScorer,
    ) -> None:
        self._models = models
        self._quality_scorer = quality_scorer

    def recognize(
        self,
        image: Any,
        time_ms: int,
        crop_box: NormalizedRect | None,
    ) -> list[PlateCandidate]:
        model = self._models.load_alpr_model()
        temp_path = _write_temp_image(self._models, image)
        try:
            raw_predictions = model.predict(temp_path)
        finally:
            _cleanup_temp_image(temp_path)

        frame_height, frame_width = image.shape[:2]
        predictions: list[PlateCandidate] = []
        raw_items = list(raw_predictions) if _is_prediction_iterable(raw_predictions) else [raw_predictions]

        for index, raw_prediction in enumerate(raw_items):
            payload = _serialize_prediction_object(raw_prediction)
            text = normalize_plate_text(
                _first_present(
                    payload.get('text'),
                    payload.get('plate'),
                    payload.get('plate_text'),
                    payload.get('ocr_text'),
                    _nested_get(payload, 'ocr', 'text'),
                )
            )
            if not text:
                continue

            confidence = _to_float(
                _first_present(
                    payload.get('confidence'),
                    payload.get('ocr_confidence'),
                    payload.get('score'),
                    _nested_get(payload, 'ocr', 'confidence'),
                    _nested_get(payload, 'detection', 'confidence'),
                )
            )
            candidate_box = _normalize_candidate_box(
                _first_present(
                    payload.get('box'),
                    payload.get('bbox'),
                    payload.get('xyxy'),
                    _nested_get(payload, 'detection', 'bounding_box'),
                ),
                crop_box,
                frame_width,
                frame_height,
            )
            quality = self._quality_scorer.score(image, candidate_box)
            predictions.append(
                PlateCandidate(
                    id=f'baseline-{time_ms}-{index}',
                    text=text,
                    confidence=confidence,
                    source='baseline',
                    frame_time_ms=time_ms,
                    country_code=_to_optional_str(_nested_get(payload, 'ocr', 'region')),
                    box=candidate_box,
                    quality=quality,
                )
            )

        predictions.sort(
            key=lambda candidate: (
                candidate.confidence,
                candidate.quality.overall_score if candidate.quality else 0.0,
            ),
            reverse=True,
        )
        return predictions


def _translate_rect_from_crop(rect: NormalizedRect, crop_rect: NormalizedRect) -> NormalizedRect:
    x = clamp(crop_rect.x + (rect.x * crop_rect.width), 0.0, 1.0)
    y = clamp(crop_rect.y + (rect.y * crop_rect.height), 0.0, 1.0)
    width = clamp(rect.width * crop_rect.width, 0.0, 1.0 - x)
    height = clamp(rect.height * crop_rect.height, 0.0, 1.0 - y)
    return NormalizedRect(x=x, y=y, width=width, height=height)


def _write_temp_image(models: ModelRegistry, image: Any) -> str:
    cv2 = models.dependencies.cv2
    handle = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    handle.close()
    cv2.imwrite(handle.name, image)
    return handle.name


def _cleanup_temp_image(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        return


def _serialize_prediction_object(prediction: Any) -> dict[str, Any]:
    serialized = _serialize_prediction_value(prediction)
    return serialized if isinstance(serialized, dict) else {'raw': serialized}


def _serialize_prediction_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {key: _serialize_prediction_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_prediction_value(item) for item in value]
    if hasattr(value, '_asdict'):
        return {
            key: _serialize_prediction_value(item)
            for key, item in value._asdict().items()
        }
    if hasattr(value, '__dict__'):
        return {
            key: _serialize_prediction_value(item)
            for key, item in vars(value).items()
        }
    return str(value)


def _is_prediction_iterable(raw_predictions: Any) -> bool:
    return isinstance(raw_predictions, Iterable) and not isinstance(raw_predictions, (dict, str, bytes))


def _to_float(value: Any) -> float:
    if isinstance(value, (list, tuple)):
        values = [_to_float(item) for item in value if item is not None]
        return sum(values) / len(values) if values else 0.0
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value:
            continue
        return value
    return None


def _nested_get(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _to_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_candidate_box(
    raw_box: Any,
    crop_box: NormalizedRect | None,
    frame_width: int,
    frame_height: int,
) -> NormalizedRect | None:
    if raw_box is None:
        return None

    if isinstance(raw_box, dict):
        values = raw_box
        if {'xmin', 'ymin', 'xmax', 'ymax'} <= set(values):
            x1, y1, x2, y2 = values['xmin'], values['ymin'], values['xmax'], values['ymax']
        elif {'x1', 'y1', 'x2', 'y2'} <= set(values):
            x1, y1, x2, y2 = values['x1'], values['y1'], values['x2'], values['y2']
        elif {'x', 'y', 'width', 'height'} <= set(values):
            x1 = values['x']
            y1 = values['y']
            x2 = values['x'] + values['width']
            y2 = values['y'] + values['height']
        else:
            return None
    elif isinstance(raw_box, (list, tuple)) and len(raw_box) >= 4:
        x1, y1, x2, y2 = raw_box[:4]
    else:
        return None

    x1 = float(x1)
    y1 = float(y1)
    x2 = float(x2)
    y2 = float(y2)

    if crop_box:
        crop_x = crop_box.x * frame_width
        crop_y = crop_box.y * frame_height
        crop_width = crop_box.width * frame_width
        crop_height = crop_box.height * frame_height
        return NormalizedRect.from_xyxy(
            crop_x + x1,
            crop_y + y1,
            crop_x + min(crop_width, x2),
            crop_y + min(crop_height, y2),
            frame_width,
            frame_height,
        )

    return NormalizedRect.from_xyxy(x1, y1, x2, y2, frame_width, frame_height)
