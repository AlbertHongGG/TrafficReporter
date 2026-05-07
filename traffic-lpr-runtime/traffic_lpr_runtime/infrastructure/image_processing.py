from __future__ import annotations

from traffic_lpr_runtime.domain.models import QualityMetrics
from traffic_lpr_runtime.domain.value_objects import NormalizedRect, crop_image

from .dependencies import DependencyRegistry


class ImagePreprocessor:
    def __init__(self, dependencies: DependencyRegistry) -> None:
        self._dependencies = dependencies

    def build_variants(self, image):
        self._dependencies.ensure_ready()
        cv2 = self._dependencies.cv2

        variants = [('baseline', image)]

        upscaled = cv2.resize(image, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        variants.append(('restored-upscale', upscaled))

        denoised = cv2.fastNlMeansDenoisingColored(image, None, 4, 4, 7, 21)
        sharpened = cv2.addWeighted(denoised, 1.35, cv2.GaussianBlur(denoised, (0, 0), 3), -0.35, 0)
        variants.append(('restored-denoise', sharpened))

        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = cv2.merge((clahe.apply(l_channel), a_channel, b_channel))
        variants.append(('restored-clahe', cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)))
        return variants


class QualityScorer:
    def __init__(self, dependencies: DependencyRegistry) -> None:
        self._dependencies = dependencies

    def score(self, image, plate_box: NormalizedRect | None) -> QualityMetrics | None:
        if image is None or self._dependencies.cv2 is None or self._dependencies.numpy is None:
            return QualityMetrics(
                sharpness=0.0,
                contrast=0.0,
                plate_area=0.0,
                angle_score=0.5,
                occlusion_score=0.5,
                glare_score=0.5,
                legibility_score=0.0,
                overall_score=0.0,
                legibility_level='unknown',
            )

        cv2 = self._dependencies.cv2
        plate_image = crop_image(image, plate_box)
        grayscale = cv2.cvtColor(plate_image, cv2.COLOR_BGR2GRAY)
        sharpness = float(clamp(cv2.Laplacian(grayscale, cv2.CV_64F).var() / 1200.0, 0.0, 1.0))
        contrast = float(clamp(float(grayscale.std()) / 90.0, 0.0, 1.0))
        glare_ratio = float(((grayscale > 245).sum() / grayscale.size) if grayscale.size else 0.0)
        glare_score = float(clamp(1.0 - (glare_ratio * 4.0), 0.0, 1.0))
        plate_area = float(plate_box.area()) if plate_box else 0.0
        angle_score = (
            float(
                clamp(
                    1.0 - abs((plate_box.width / max(plate_box.height, 0.001)) - 3.0) / 4.0,
                    0.0,
                    1.0,
                )
            )
            if plate_box
            else 0.5
        )
        occlusion_score = float(clamp((sharpness * 0.5) + (contrast * 0.5), 0.0, 1.0))
        legibility_score = float(
            clamp(
                (sharpness * 0.35)
                + (contrast * 0.3)
                + (glare_score * 0.2)
                + (clamp(plate_area * 12.0, 0.0, 1.0) * 0.15),
                0.0,
                1.0,
            )
        )
        overall_score = float(clamp((legibility_score * 0.75) + (angle_score * 0.25), 0.0, 1.0))

        if overall_score >= 0.82:
            legibility_level = 'perfect'
        elif overall_score >= 0.62:
            legibility_level = 'good'
        elif overall_score >= 0.35:
            legibility_level = 'poor'
        else:
            legibility_level = 'illegible'

        return QualityMetrics(
            sharpness=sharpness,
            contrast=contrast,
            plate_area=plate_area,
            angle_score=angle_score,
            occlusion_score=occlusion_score,
            glare_score=glare_score,
            legibility_score=legibility_score,
            overall_score=overall_score,
            legibility_level=legibility_level,
        )
