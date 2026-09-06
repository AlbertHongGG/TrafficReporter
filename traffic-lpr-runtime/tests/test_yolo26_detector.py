from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from traffic_lpr_runtime.domain.value_objects import NormalizedRect
from traffic_lpr_runtime.infrastructure.model_runtime import ModelRegistry, Yolo26TargetDetector


class TestYolo26TargetDetector(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_deps = MagicMock()
        self.mock_deps.preferred_torch_device.return_value = 'cpu'
        self.mock_deps.models_root.return_value = MagicMock()
        self.model_registry = ModelRegistry(self.mock_deps)

    def test_detect_targets_maps_boxes_and_filters_classes(self) -> None:
        mock_box_1 = MagicMock()
        mock_box_1.xyxy = [np.array([100.0, 100.0, 200.0, 300.0])]
        mock_box_1.conf = [np.array(0.92)]
        mock_box_1.cls = [np.array(2.0)]

        mock_box_2 = MagicMock()
        mock_box_2.xyxy = [np.array([300.0, 150.0, 500.0, 400.0])]
        mock_box_2.conf = [np.array(0.85)]
        mock_box_2.cls = [np.array(3.0)]

        mock_result = SimpleNamespace(boxes=[mock_box_1, mock_box_2])
        mock_yolo_instance = MagicMock()
        mock_yolo_instance.return_value = [mock_result]
        mock_yolo_instance.names = {2: 'car', 3: 'motorcycle', 5: 'bus', 7: 'truck'}

        self.model_registry._vehicle_model = mock_yolo_instance
        detector = Yolo26TargetDetector(self.model_registry, model_name='yolo26s.pt')

        frame = np.zeros((1000, 1000, 3), dtype=np.uint8)
        targets = detector.detect_targets(frame, time_ms=1000, vehicle_kind='vehicle', marker_rect=None)

        self.assertEqual(len(targets), 2)
        self.assertEqual(targets[0].class_name, 'car')
        self.assertAlmostEqual(targets[0].confidence, 0.92, places=2)
        self.assertEqual(targets[0].box.x, 0.1)
        self.assertEqual(targets[0].box.y, 0.1)
        self.assertEqual(targets[0].box.width, 0.1)
        self.assertEqual(targets[0].box.height, 0.2)

        self.assertEqual(targets[1].class_name, 'motorcycle')
        self.assertAlmostEqual(targets[1].confidence, 0.85, places=2)

    def test_detect_targets_with_marker_rect_translates_coordinates(self) -> None:
        mock_box = MagicMock()
        mock_box.xyxy = [np.array([100.0, 100.0, 200.0, 200.0])]
        mock_box.conf = [np.array(0.95)]
        mock_box.cls = [np.array(2.0)]

        mock_result = SimpleNamespace(boxes=[mock_box])
        mock_yolo_instance = MagicMock()
        mock_yolo_instance.return_value = [mock_result]
        mock_yolo_instance.names = {2: 'car'}

        self.model_registry._vehicle_model = mock_yolo_instance
        detector = Yolo26TargetDetector(self.model_registry, model_name='yolo26s.pt')

        frame = np.zeros((1000, 1000, 3), dtype=np.uint8)
        marker = NormalizedRect(x=0.5, y=0.5, width=0.5, height=0.5)
        targets = detector.detect_targets(frame, time_ms=2000, vehicle_kind='car', marker_rect=marker)

        self.assertEqual(len(targets), 1)
        self.assertAlmostEqual(targets[0].box.x, 0.6, places=4)
        self.assertAlmostEqual(targets[0].box.y, 0.6, places=4)
        self.assertAlmostEqual(targets[0].box.width, 0.1, places=4)
        self.assertAlmostEqual(targets[0].box.height, 0.1, places=4)

    def test_detect_targets_empty_frame_returns_empty(self) -> None:
        detector = Yolo26TargetDetector(self.model_registry)
        targets = detector.detect_targets(None, time_ms=0, vehicle_kind='car', marker_rect=None)
        self.assertEqual(targets, [])


if __name__ == '__main__':
    unittest.main()
