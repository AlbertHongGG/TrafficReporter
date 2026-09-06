from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.application.use_cases.extract_storyboard import (
    ExtractStoryboardUseCase,
    format_time_label,
)

try:
    import cv2
    import numpy as np
except Exception:
    cv2 = None
    np = None


@unittest.skipIf(cv2 is None or np is None, 'OpenCV and NumPy are required.')
class ExtractStoryboardTests(unittest.TestCase):
    def test_format_time_label(self) -> None:
        self.assertEqual(format_time_label(0), "00:00.000")
        self.assertEqual(format_time_label(1500), "00:01.500")
        self.assertEqual(format_time_label(65432), "01:05.432")

    def test_sample_times_resolution(self) -> None:
        use_case = ExtractStoryboardUseCase(
            ensure_ready=lambda: None,
            runtime_root=lambda: Path("/tmp"),
            frame_reader=MagicMock(),
            dependencies=MagicMock(),
        )
        # Explicit times
        times = use_case._resolve_sample_times({"timesMs": [2000, 1000, 3000]}, 10000)
        self.assertEqual(times, [1000, 2000, 3000])

        # Range with step
        times_range = use_case._resolve_sample_times(
            {"startMs": 0, "endMs": 4000, "sampleEveryMs": 1000, "maxSamples": 10},
            10000,
        )
        self.assertEqual(len(times_range), 5)
        self.assertEqual(times_range[0], 0)
        self.assertEqual(times_range[-1], 4000)
