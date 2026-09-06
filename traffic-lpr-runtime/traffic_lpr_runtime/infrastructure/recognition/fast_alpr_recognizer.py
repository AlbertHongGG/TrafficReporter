from __future__ import annotations

from typing import Any

from traffic_lpr_runtime.domain.interfaces import QualityScorer
from traffic_lpr_runtime.domain.models import PlateCandidate
from traffic_lpr_runtime.domain.text import normalize_plate_text
from traffic_lpr_runtime.domain.value_objects import NormalizedRect, clamp
from traffic_lpr_runtime.infrastructure.models.hub import (
    DEFAULT_CROP_OCR_MODEL_NAMES,
    ModelHub,
)

from .plate_priors import TaiwanPlatePrior
from .prediction_mapper import AlprPredictionMapper


class FastAlprPlateRecognizer:
    """Plate recognizer backed by FastALPR detector and FastPlateOCR engines."""

    def __init__(
        self,
        models: ModelHub,
        quality_scorer: QualityScorer,
        priors: TaiwanPlatePrior | None = None,
        mapper: AlprPredictionMapper | None = None,
    ) -> None:
        self._models = models
        self._quality_scorer = quality_scorer
        self._priors = priors or TaiwanPlatePrior()
        self._mapper = mapper or AlprPredictionMapper()

    def recognize(
        self,
        image: Any,
        time_ms: int,
        crop_box: NormalizedRect | None,
    ) -> list[PlateCandidate]:
        if image is None or getattr(image, 'size', 0) == 0:
            return []

        model = self._models.load_alpr_model()
        temp_path = self._mapper.write_temp_image(self._models.dependencies.cv2, image)
        try:
            raw_predictions = model.predict(temp_path)
        finally:
            self._mapper.cleanup_temp_image(temp_path)

        frame_height, frame_width = image.shape[:2]
        predictions: list[PlateCandidate] = []
        raw_items = (
            list(raw_predictions)
            if self._mapper.is_prediction_iterable(raw_predictions)
            else [raw_predictions]
        )

        for index, raw_prediction in enumerate(raw_items):
            payload = self._mapper.serialize_prediction(raw_prediction)
            text = normalize_plate_text(
                self._mapper.first_present(
                    payload.get('text'),
                    payload.get('plate'),
                    payload.get('plate_text'),
                    payload.get('ocr_text'),
                    self._mapper.nested_get(payload, 'ocr', 'text'),
                )
            )
            if not text:
                continue

            confidence = self._mapper.to_float(
                self._mapper.first_present(
                    payload.get('confidence'),
                    payload.get('ocr_confidence'),
                    payload.get('score'),
                    self._mapper.nested_get(payload, 'ocr', 'confidence'),
                    self._mapper.nested_get(payload, 'detection', 'confidence'),
                )
            )
            local_candidate_box = self._mapper.normalize_candidate_box(
                self._mapper.first_present(
                    payload.get('box'),
                    payload.get('bbox'),
                    payload.get('xyxy'),
                    self._mapper.nested_get(payload, 'detection', 'bounding_box'),
                ),
                frame_width,
                frame_height,
            )
            candidate_box = self._mapper.translate_rect_from_crop(local_candidate_box, crop_box)
            quality = self._quality_scorer.score(image, local_candidate_box)
            raw_confidence = self._mapper.first_present(
                payload.get('ocr_confidence'),
                self._mapper.nested_get(payload, 'ocr', 'confidence'),
                payload.get('confidence'),
            )
            predictions.append(
                PlateCandidate(
                    id=f'baseline-{time_ms}-{index}',
                    text=text,
                    confidence=confidence,
                    source='baseline',
                    frame_time_ms=time_ms,
                    country_code=self._mapper.to_optional_str(self._mapper.nested_get(payload, 'ocr', 'region')),
                    box=candidate_box,
                    quality=quality,
                    diagnostics={
                        'recognizer': 'fast-alpr',
                        'ocrModel': 'cct-xs-v2-global-model',
                        'charConfidences': self._mapper.to_float_list(raw_confidence),
                    },
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

    def recognize_plate_crop(
        self,
        image: Any,
        time_ms: int,
        plate_box: NormalizedRect | None,
        country_hints: list[str] | None = None,
        model_names: list[str] | None = None,
    ) -> list[PlateCandidate]:
        if image is None or getattr(image, 'size', 0) == 0:
            return []

        hints = [hint.upper() for hint in (country_hints or []) if hint]
        predictions: list[PlateCandidate] = []
        effective_model_names = list(dict.fromkeys(model_names or DEFAULT_CROP_OCR_MODEL_NAMES))

        for index, model_name in enumerate(effective_model_names):
            crop_ocr_model = self._models.load_crop_ocr_model(model_name)
            try:
                prediction = crop_ocr_model.run_one(image, return_confidence=True)
            except Exception:
                continue

            text = normalize_plate_text(getattr(prediction, 'plate', None))
            if not text:
                continue

            char_confidences = self._mapper.to_float_list(getattr(prediction, 'char_probs', None)) or []
            raw_confidence = sum(char_confidences) / len(char_confidences) if char_confidences else 0.0
            quality = self._quality_scorer.score(image, None)
            country_code = (
                self._mapper.to_optional_str(getattr(prediction, 'region', None))
                or self._priors.preferred_country_hint(hints)
            )
            taiwan_prior = (
                self._priors.calculate_prior(text)
                if self._priors.is_applicable(hints, country_code)
                else 1.0
            )
            confidence = clamp(
                ((raw_confidence * 0.72) + ((quality.overall_score if quality else 0.55) * 0.28)) * taiwan_prior,
                0.0,
                1.0,
            )
            predictions.append(
                PlateCandidate(
                    id=f'ocr-{time_ms}-{index}',
                    text=text,
                    confidence=confidence,
                    source=f'ocr:{model_name}',
                    frame_time_ms=time_ms,
                    country_code=country_code,
                    box=plate_box,
                    quality=quality,
                    diagnostics={
                        'recognizer': 'fast-plate-ocr',
                        'ocrModel': model_name,
                        'charConfidences': char_confidences,
                        'taiwanPrior': taiwan_prior,
                        'regionConfidence': self._mapper.to_float(getattr(prediction, 'region_prob', None)),
                    },
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
