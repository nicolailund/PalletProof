from __future__ import annotations

import unittest
from urllib.request import urlopen

from pallet_video_recorder.config import PreviewConfig
from pallet_video_recorder.preview import CameraPreviewServer


class CameraPreviewServerTest(unittest.TestCase):
    def test_serves_index_page(self) -> None:
        preview = CameraPreviewServer(PreviewConfig(enabled=True, host="127.0.0.1", port=0))
        preview.start()
        try:
            assert preview._server is not None
            port = preview._server.server_address[1]
            with urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
                body = response.read().decode("utf-8")
        finally:
            preview.stop()

        self.assertIn("Live kamera-preview", body)
        self.assertIn("/stream.mjpg", body)


if __name__ == "__main__":
    unittest.main()
