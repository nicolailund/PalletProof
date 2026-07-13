from __future__ import annotations

from collections import deque
import time
import unittest

from pallet_video_recorder.config import BarcodeConfig
from pallet_video_recorder.scanner import BarcodeScanWorker


class FakeReader:
    def __init__(self, values: list[str | None]) -> None:
        self.values = deque(values)
        self.frames: list[object] = []
        self.ambient_reset_count = 0

    def read(self, frame: object) -> str | None:
        self.frames.append(frame)
        if not self.values:
            return None
        return self.values.popleft()

    def start_ambient_suppression(self) -> None:
        self.ambient_reset_count += 1


class BarcodeScanWorkerTest(unittest.TestCase):
    def test_scans_in_background_and_returns_result(self) -> None:
        worker = BarcodeScanWorker(BarcodeConfig(ambient_suppress_seconds=0.0))
        fake_reader = FakeReader(["ORD-123"])
        worker.reader = fake_reader  # type: ignore[assignment]

        worker.start()
        try:
            worker.submit(object())
            result = self._wait_for_result(worker)
        finally:
            worker.stop()

        self.assertEqual(result, "ORD-123")
        self.assertEqual(len(fake_reader.frames), 1)

    def test_forwards_ambient_suppression_reset_to_reader(self) -> None:
        worker = BarcodeScanWorker(BarcodeConfig(ambient_suppress_seconds=0.0))
        fake_reader = FakeReader([])
        worker.reader = fake_reader  # type: ignore[assignment]

        worker.start_ambient_suppression()

        self.assertEqual(fake_reader.ambient_reset_count, 1)

    def _wait_for_result(self, worker: BarcodeScanWorker) -> str | None:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            result = worker.poll()
            if result is not None:
                return result
            time.sleep(0.01)
        return None


if __name__ == "__main__":
    unittest.main()
