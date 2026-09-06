from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from traffic_lpr_runtime.domain.errors import RuntimeFailure
from traffic_lpr_runtime.infrastructure.dependencies import DependencyRegistry

from .execution_provider import OnnxExecutionProviderPolicy

DEFAULT_VEHICLE_MODEL_NAME = 'yolo26s.pt'

DEFAULT_CROP_OCR_MODEL_NAMES = (
    'cct-xs-v2-global-model',
    'cct-s-v2-global-model',
    'global-plates-mobile-vit-v2-model',
)


class ModelHub:
    """Manages model weights, path resolution, downloads, and instance caching."""

    def __init__(
        self,
        dependencies: DependencyRegistry,
        execution_policy: OnnxExecutionProviderPolicy | None = None,
    ) -> None:
        self._dependencies = dependencies
        self._execution_policy = execution_policy or OnnxExecutionProviderPolicy(dependencies)
        self._vehicle_model: Any | None = None
        self._alpr_model: Any | None = None
        self._crop_ocr_models: dict[str, Any] = {}

    @property
    def dependencies(self) -> DependencyRegistry:
        return self._dependencies

    @property
    def execution_policy(self) -> OnnxExecutionProviderPolicy:
        return self._execution_policy

    def load_vehicle_model(self, model_name: str = DEFAULT_VEHICLE_MODEL_NAME) -> Any:
        if self._vehicle_model is not None:
            return self._vehicle_model

        self._dependencies.ensure_ready()
        yolo_type = getattr(self._dependencies.ultralytics, 'YOLO', None)
        if yolo_type is None:
            raise RuntimeFailure('ultralytics.YOLO is unavailable in the configured Python environment.')

        preferred_device = self._dependencies.preferred_torch_device()
        model_path = self.ensure_vehicle_model_path(model_name)
        try:
            self._vehicle_model = yolo_type(str(model_path))
            move_to = getattr(self._vehicle_model, 'to', None)
            if callable(move_to):
                move_to(preferred_device)
            return self._vehicle_model
        except Exception as error:
            raise RuntimeFailure(f'Unable to load vehicle detector model {model_name}: {error}') from error

    def load_alpr_model(self) -> Any:
        if self._alpr_model is not None:
            return self._alpr_model

        self._dependencies.ensure_ready()
        alpr_type = getattr(self._dependencies.fast_alpr, 'ALPR', None)
        if alpr_type is None:
            raise RuntimeFailure('fast_alpr.ALPR is unavailable in the configured Python environment.')

        detector_providers = self._execution_policy.providers()
        ocr_device = self._execution_policy.device()
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

    def load_crop_ocr_model(self, model_name: str) -> Any:
        cached_model = self._crop_ocr_models.get(model_name)
        if cached_model is not None:
            return cached_model

        self._dependencies.ensure_ready()
        recognizer_type = getattr(self._dependencies.fast_plate_ocr, 'LicensePlateRecognizer', None)
        if recognizer_type is None:
            raise RuntimeFailure('fast_plate_ocr.LicensePlateRecognizer is unavailable in the configured Python environment.')

        try:
            crop_ocr_model = recognizer_type(
                hub_ocr_model=model_name,
                device=self._execution_policy.device(),
                providers=self._execution_policy.providers(),
            )
        except Exception as error:
            raise RuntimeFailure(f'Unable to load the OCR model {model_name}: {error}') from error

        self._crop_ocr_models[model_name] = crop_ocr_model
        return crop_ocr_model

    def ensure_vehicle_model_path(self, model_name: str = DEFAULT_VEHICLE_MODEL_NAME) -> Path:
        clean_name = model_name if model_name.endswith('.pt') else f'{model_name}.pt'
        model_path = self._dependencies.models_root() / clean_name
        if model_path.exists() and model_path.stat().st_size > 1000:
            return model_path

        model_path.parent.mkdir(parents=True, exist_ok=True)
        yolo_type = getattr(self._dependencies.ultralytics, 'YOLO', None)
        if yolo_type is None:
            raise RuntimeFailure('ultralytics.YOLO is unavailable to download weights.')

        instance = yolo_type(clean_name)
        raw_weights = getattr(instance, 'weights', clean_name)
        downloaded_path = Path(str(raw_weights))
        if downloaded_path.exists() and downloaded_path.resolve() != model_path.resolve():
            shutil.copy2(downloaded_path, model_path)

        if model_path.exists() and model_path.stat().st_size > 1000:
            return model_path
        if downloaded_path.exists() and downloaded_path.stat().st_size > 1000:
            return downloaded_path

        v8_path = self._dependencies.models_root() / 'yolov8x.pt'
        if v8_path.exists() and v8_path.stat().st_size > 1000:
            return v8_path

        raise RuntimeFailure(f'Unable to resolve or download detector weights for {model_name}.')


# Clean alias during transition if any caller expects ModelRegistry
ModelRegistry = ModelHub
