from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable
from typing import Any

from traffic_lpr_runtime.domain.errors import RuntimeFailure
from traffic_lpr_runtime.domain.models import PlateCandidate, TrackedRegion
from traffic_lpr_runtime.domain.text import normalize_plate_text
from traffic_lpr_runtime.domain.value_objects import NormalizedRect

from .dependencies import DependencyRegistry
from .image_processing import QualityScorer


COCO_VEHICLE_CLASSES = {
    'car': 2,
    'motorcycle': 3,
    'bus': 5,
    'truck': 7,
}


class ModelRegistry:
    def __init__(self, dependencies: DependencyRegistry) -> None:
        self._dependencies = dependencies
        self._vehicle_model: Any | None = None
        self._alpr_model: Any | None = None
        self._fallback_ocr: Any | None = None

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
        for model_name in ['yolo11x.pt', 'yolov8x.pt', 'yolo11s.pt', 'yolov8s.pt']:
            try:
                self._vehicle_model = yolo_type(model_name)
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

        last_error: Exception | None = None
        for detector_model in [
            'yolo-v9-t-384-license-plate-end2end',
            'yolo-v9-t-640-license-plate-end2end',
        ]:
            try:
                self._alpr_model = alpr_type(
                    detector_model=detector_model,
                    ocr_model='cct-xs-v2-global-model',
                )
                return self._alpr_model
            except Exception as error:
                last_error = error

        raise RuntimeFailure(f'Unable to load the ALPR detector/OCR stack: {last_error}')

    def load_fallback_ocr(self) -> Any:
        if self._fallback_ocr is not None:
            return self._fallback_ocr

        self._dependencies.ensure_ready()
        recognizer_type = getattr(self._dependencies.fast_plate_ocr, 'LicensePlateRecognizer', None)
        if recognizer_type is None:
            raise RuntimeFailure('fast_plate_ocr.LicensePlateRecognizer is unavailable in the configured Python environment.')

        try:
            self._fallback_ocr = recognizer_type('cct-s-v2-global-model')
            return self._fallback_ocr
        except Exception as error:
            raise RuntimeFailure(f'Unable to load the OCR fallback model: {error}') from error


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
        result = model(
            frame,
            classes=self._models.vehicle_classes_for_kind(vehicle_kind),
            verbose=False,
            conf=0.18,
        )[0]
        frame_height, frame_width = frame.shape[:2]
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
            if marker_rect and normalized_box.intersection_over_union(marker_rect) <= 0.02:
                continue

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
        source_label: str,
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
                payload.get('text')
                or payload.get('plate')
                or payload.get('plate_text')
                or payload.get('ocr_text')
                or payload.get('ocr')
            )
            if not text:
                continue

            confidence = _to_float(payload.get('confidence') or payload.get('ocr_confidence') or payload.get('score'))
            candidate_box = _normalize_candidate_box(
                payload.get('box') or payload.get('bbox') or payload.get('xyxy'),
                crop_box,
                frame_width,
                frame_height,
            )
            quality = self._quality_scorer.score(image, candidate_box)
            predictions.append(
                PlateCandidate(
                    id=f'{source_label}-{time_ms}-{index}',
                    text=text,
                    confidence=confidence,
                    source='restored' if source_label.startswith('restored') else 'baseline',
                    frame_time_ms=time_ms,
                    country_code=None,
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


class FastPlateOcrFallbackRecognizer:
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
        source_label: str,
        time_ms: int,
        crop_box: NormalizedRect | None,
    ) -> list[PlateCandidate]:
        del source_label

        model = self._models.load_fallback_ocr()
        temp_path = _write_temp_image(self._models, image)
        try:
            raw_predictions = model.run(temp_path, return_confidence=True)
        finally:
            _cleanup_temp_image(temp_path)

        raw_items = list(raw_predictions) if _is_prediction_iterable(raw_predictions) else [raw_predictions]
        frame_height, frame_width = image.shape[:2]
        predictions: list[PlateCandidate] = []

        for index, raw_prediction in enumerate(raw_items):
            payload = _serialize_prediction_object(raw_prediction)
            text = normalize_plate_text(payload.get('text') or payload.get('plate') or payload.get('ocr'))
            if not text:
                continue
            confidence = _to_float(payload.get('confidence') or payload.get('prob') or payload.get('region_prob'))
            candidate_box = _normalize_candidate_box(
                payload.get('box') or payload.get('bbox'),
                crop_box,
                frame_width,
                frame_height,
            )
            quality = self._quality_scorer.score(image, candidate_box)
            predictions.append(
                PlateCandidate(
                    id=f'fallback-{time_ms}-{index}',
                    text=text,
                    confidence=confidence,
                    source='fallback',
                    frame_time_ms=time_ms,
                    country_code=payload.get('region'),
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
    if prediction is None:
        return {}
    if isinstance(prediction, dict):
        return prediction
    if hasattr(prediction, '__dict__'):
        return dict(vars(prediction))
    if hasattr(prediction, '_asdict'):
        return dict(prediction._asdict())
    return {'raw': str(prediction)}


def _is_prediction_iterable(raw_predictions: Any) -> bool:
    return isinstance(raw_predictions, Iterable) and not isinstance(raw_predictions, (dict, str, bytes))


def _to_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


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
