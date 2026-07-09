from __future__ import annotations

import unittest

np = None
try:
    import numpy as np
    import cv2  # noqa: F401
except Exception:
    pass

from pallet_video_recorder.config import MotionConfig
from pallet_video_recorder.motion import MotionDetector, crop_normalized


@unittest.skipIf(np is None, "numpy/opencv are not installed")
class MotionTest(unittest.TestCase):
    def test_crop_normalized(self) -> None:
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        cropped = crop_normalized(frame, (0.25, 0.2, 0.5, 0.6))
        self.assertEqual(cropped.shape, (60, 100, 3))

    def test_detects_motion_between_frames(self) -> None:
        detector = MotionDetector(MotionConfig(threshold=0.005))
        frame_a = np.zeros((120, 160, 3), dtype=np.uint8)
        frame_b = frame_a.copy()
        frame_b[:, 40:120] = 255

        first = detector.update(frame_a)
        second = detector.update(frame_b)

        self.assertFalse(first.moving)
        self.assertTrue(second.moving)
        self.assertGreater(second.score, 0.005)


if __name__ == "__main__":
    unittest.main()
