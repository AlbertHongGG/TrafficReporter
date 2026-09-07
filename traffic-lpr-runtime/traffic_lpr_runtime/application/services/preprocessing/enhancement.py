from __future__ import annotations

from typing import Any

from traffic_lpr_runtime.domain.analysis_options import AnalysisOptions
from traffic_lpr_runtime.domain.models import QualityMetrics


class EnhancementMixin:
    def _enhance_plate(self, plate_image: Any) -> Any:
        cv2 = self._dependencies.cv2
        if cv2 is None or plate_image is None or getattr(plate_image, 'size', 0) == 0:
            return plate_image

        grayscale = cv2.cvtColor(plate_image, cv2.COLOR_BGR2GRAY)
        contrast = float(grayscale.std()) / 255.0
        brightness = float(grayscale.mean()) / 255.0
        clip_limit = 3.0 if contrast < 0.22 or brightness < 0.4 else 2.2
        tile_grid = (6, 6) if min(plate_image.shape[:2]) >= 96 else (4, 4)
        lab = cv2.cvtColor(plate_image, cv2.COLOR_BGR2LAB)
        channel_l, channel_a, channel_b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid)
        equalized_l = clahe.apply(channel_l)
        merged_lab = cv2.merge((equalized_l, channel_a, channel_b))
        enhanced = cv2.cvtColor(merged_lab, cv2.COLOR_LAB2BGR)
        filter_strength = 55 if contrast < 0.22 else 45
        denoised = cv2.bilateralFilter(enhanced, 7 if contrast < 0.22 else 5, filter_strength, filter_strength)
        softened = cv2.GaussianBlur(denoised, (0, 0), 0.95 if contrast < 0.22 else 1.2)
        sharpen_gain = 1.68 if contrast < 0.22 else 1.55
        return cv2.addWeighted(denoised, sharpen_gain, softened, -(sharpen_gain - 1.0), 0)

    def _should_restore(self, plate_image: Any, quality: QualityMetrics | None, options: AnalysisOptions, quality_route: str) -> bool:
        if options.restoration_mode == 'off' or plate_image is None:
            return False
        height, width = plate_image.shape[:2]
        if min(height, width) < 52:
            return True
        if quality is None:
            return True
        if quality_route == 'high-angle':
            return False
        if quality_route == 'tiny-plate':
            return True
        return (
            quality.overall_score < 0.66
            or quality.sharpness < 0.3
            or quality.glare_score < 0.46
            or quality.contrast < 0.36
            or (quality_route in {'motion-soft', 'low-light'} and quality.legibility_score < 0.76)
        )

    def _restore_plate(self, plate_image: Any, options: AnalysisOptions) -> tuple[Any | None, dict[str, Any]]:
        restoration_mode = (options.restoration_mode or 'off').strip().lower()
        if restoration_mode == 'off':
            return None, {'applied': False, 'backend': 'none', 'mode': restoration_mode}

        if restoration_mode.startswith('mambairv2') and self._restorer is not None:
            scale = 4 if restoration_mode.endswith('x4') or min(plate_image.shape[:2]) < 40 else 2
            restored_image = self._restorer.restore(plate_image, scale=scale)
            if restored_image is not None and getattr(restored_image, 'size', 0) > 0:
                return restored_image, {
                    'applied': True,
                    'backend': 'mambairv2-lightsr',
                    'mode': restoration_mode,
                    'scale': scale,
                }

        restored_image = self._classical_restore_plate(plate_image)
        return restored_image, {
            'applied': restored_image is not None,
            'backend': 'classical',
            'mode': restoration_mode,
        }

    def _classical_restore_plate(self, plate_image: Any) -> Any:
        cv2 = self._dependencies.cv2
        if cv2 is None or plate_image is None or getattr(plate_image, 'size', 0) == 0:
            return plate_image

        upscaled = cv2.resize(plate_image, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_LANCZOS4)
        denoised = cv2.fastNlMeansDenoisingColored(upscaled, None, 3, 3, 7, 21)
        lab = cv2.cvtColor(denoised, cv2.COLOR_BGR2LAB)
        channel_l, channel_a, channel_b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.6, tileGridSize=(6, 6))
        restored_lab = cv2.merge((clahe.apply(channel_l), channel_a, channel_b))
        restored = cv2.cvtColor(restored_lab, cv2.COLOR_LAB2BGR)
        softened = cv2.GaussianBlur(restored, (0, 0), 1.0)
        return cv2.addWeighted(restored, 1.65, softened, -0.65, 0)
