from __future__ import annotations

import math
from typing import Any

from .geometry import _distance, _order_quad_points


class RectificationMixin:
    def _rectify_plate(self, plate_image: Any) -> tuple[Any, dict[str, Any]]:
        cv2 = self._dependencies.cv2
        if cv2 is None or plate_image is None or getattr(plate_image, 'size', 0) == 0:
            return plate_image, {'applied': False, 'method': 'crop'}

        grayscale = cv2.cvtColor(plate_image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(grayscale, (5, 5), 0)
        edges = cv2.Canny(blurred, 60, 180)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        image_area = max(float(plate_image.shape[0] * plate_image.shape[1]), 1.0)
        best_quad: Any = None
        best_score = 0.0

        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < image_area * 0.12:
                continue
            rect = cv2.minAreaRect(contour)
            (_, _), (width, height), _ = rect
            if width <= 1 or height <= 1:
                continue
            aspect_ratio = max(width, height) / max(min(width, height), 1.0)
            if not 2.0 <= aspect_ratio <= 6.5:
                continue
            score = (area / image_area) - (abs(aspect_ratio - 3.2) * 0.08)
            if score <= best_score:
                continue
            best_score = score
            best_quad = cv2.boxPoints(rect)

        if best_quad is None:
            return self._deskew_plate(plate_image)

        ordered = _order_quad_points(best_quad)
        dest_width = max(128, int(round(max(_distance(ordered[0], ordered[1]), _distance(ordered[2], ordered[3])))))
        dest_height = max(40, int(round(dest_width / 3.2)))
        destination = self._dependencies.numpy.array(
            [[0, 0], [dest_width - 1, 0], [dest_width - 1, dest_height - 1], [0, dest_height - 1]],
            dtype='float32',
        )
        transform = cv2.getPerspectiveTransform(ordered, destination)
        rectified = cv2.warpPerspective(plate_image, transform, (dest_width, dest_height))
        return rectified, {'applied': True, 'method': 'minAreaRect', 'score': best_score}

    def _deskew_plate(self, plate_image: Any) -> tuple[Any, dict[str, Any]]:
        cv2 = self._dependencies.cv2
        numpy = self._dependencies.numpy
        if cv2 is None or numpy is None or plate_image is None or getattr(plate_image, 'size', 0) == 0:
            return plate_image, {'applied': False, 'method': 'crop'}

        grayscale = cv2.cvtColor(plate_image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(grayscale, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 160)
        min_line_length = max(int(round(plate_image.shape[1] * 0.4)), 24)
        max_line_gap = max(int(round(plate_image.shape[1] * 0.12)), 6)
        lines = cv2.HoughLinesP(
            edges,
            1,
            numpy.pi / 180.0,
            threshold=24,
            minLineLength=min_line_length,
            maxLineGap=max_line_gap,
        )
        if lines is None:
            return plate_image, {'applied': False, 'method': 'crop'}

        weighted_angles: list[tuple[float, float]] = []
        for line in lines.reshape(-1, 4):
            x1, y1, x2, y2 = [int(value) for value in line]
            angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
            if abs(angle) > 45.0:
                continue
            length = math.hypot(x2 - x1, y2 - y1)
            if length < max(18.0, plate_image.shape[1] * 0.18):
                continue
            weighted_angles.append((angle, length))

        if not weighted_angles:
            return plate_image, {'applied': False, 'method': 'crop'}

        total_weight = sum(weight for _, weight in weighted_angles)
        weighted_angle = sum(angle * weight for angle, weight in weighted_angles) / max(total_weight, 1e-6)
        if abs(weighted_angle) < 2.0:
            return plate_image, {'applied': False, 'method': 'crop'}

        height, width = plate_image.shape[:2]
        center = (width / 2.0, height / 2.0)
        transform = cv2.getRotationMatrix2D(center, -weighted_angle, 1.0)
        cos_theta = abs(transform[0, 0])
        sin_theta = abs(transform[0, 1])
        bound_width = int(round((height * sin_theta) + (width * cos_theta)))
        bound_height = int(round((height * cos_theta) + (width * sin_theta)))
        transform[0, 2] += (bound_width / 2.0) - center[0]
        transform[1, 2] += (bound_height / 2.0) - center[1]
        rotated = cv2.warpAffine(
            plate_image,
            transform,
            (bound_width, bound_height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )
        return rotated, {
            'applied': True,
            'method': 'hough-deskew',
            'angle': weighted_angle,
            'linesUsed': len(weighted_angles),
        }
