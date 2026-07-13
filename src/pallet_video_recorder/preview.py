from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import logging
import threading
import time
from typing import Any

from .config import PreviewConfig

LOGGER = logging.getLogger(__name__)


class CameraPreviewServer:
    def __init__(
        self,
        config: PreviewConfig,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._clock = clock
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._condition = threading.Condition()
        self._latest_jpeg: bytes | None = None
        self._sequence = 0
        self._last_encode_at = 0.0

    def start(self) -> None:
        if not self.config.enabled:
            return

        handler = self._handler_class()
        try:
            self._server = ThreadingHTTPServer((self.config.host, self.config.port), handler)
        except OSError as exc:
            LOGGER.warning(
                "Camera preview unavailable on %s:%s: %s",
                self.config.host,
                self.config.port,
                exc,
            )
            return

        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="camera-preview",
            daemon=True,
        )
        self._thread.start()
        LOGGER.info("Camera preview listening on http://%s:%s", self.config.host, self.config.port)

    def update_frame(self, frame: Any) -> None:
        if self._server is None:
            return

        now = self._clock()
        minimum_interval = 1.0 / self.config.max_fps
        if now - self._last_encode_at < minimum_interval:
            return

        jpeg = self._encode_jpeg(frame)
        if jpeg is None:
            return

        self._last_encode_at = now
        with self._condition:
            self._latest_jpeg = jpeg
            self._sequence += 1
            self._condition.notify_all()

    def stop(self) -> None:
        if self._server is None:
            return

        self._server.shutdown()
        self._server.server_close()
        self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        with self._condition:
            self._condition.notify_all()

    def wait_for_frame(self, last_sequence: int, timeout: float = 5.0) -> tuple[int, bytes] | None:
        with self._condition:
            self._condition.wait_for(
                lambda: self._sequence > last_sequence or self._server is None,
                timeout=timeout,
            )
            if self._latest_jpeg is None or self._sequence <= last_sequence:
                return None
            return self._sequence, self._latest_jpeg

    def latest_frame(self) -> bytes | None:
        with self._condition:
            return self._latest_jpeg

    def _encode_jpeg(self, frame: Any) -> bytes | None:
        try:
            import cv2
        except Exception as exc:  # pragma: no cover - dependency depends on install target
            LOGGER.warning("Camera preview unavailable; OpenCV import failed: %s", exc)
            return None

        try:
            preview_frame = frame
            if self.config.width > 0 and hasattr(frame, "shape"):
                height, width = frame.shape[:2]
                if width > self.config.width:
                    target_height = max(1, int(height * (self.config.width / width)))
                    preview_frame = cv2.resize(
                        frame,
                        (self.config.width, target_height),
                        interpolation=cv2.INTER_AREA,
                    )
            ok, encoded = cv2.imencode(
                ".jpg",
                preview_frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), self.config.jpeg_quality],
            )
        except Exception as exc:
            LOGGER.debug("Camera preview JPEG encode failed: %s", exc)
            return None

        if not ok:
            return None
        return encoded.tobytes()

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        preview = self

        class PreviewRequestHandler(BaseHTTPRequestHandler):
            server_version = "PalletPreview/0.1"

            def do_GET(self) -> None:
                if self.path in {"/", "/index.html"}:
                    self._serve_index()
                    return
                if self.path == "/snapshot.jpg":
                    self._serve_snapshot()
                    return
                if self.path == "/stream.mjpg":
                    self._serve_stream()
                    return
                self.send_error(HTTPStatus.NOT_FOUND)

            def log_message(self, format: str, *args: object) -> None:
                LOGGER.debug("Camera preview client: " + format, *args)

            def _serve_index(self) -> None:
                body = _INDEX_HTML.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _serve_snapshot(self) -> None:
                frame = preview.latest_frame()
                if frame is None:
                    self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "No camera frame available yet")
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(frame)))
                self.end_headers()
                self.wfile.write(frame)

            def _serve_stream(self) -> None:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()

                last_sequence = 0
                while True:
                    frame = preview.wait_for_frame(last_sequence)
                    if frame is None:
                        if preview._server is None:
                            return
                        continue
                    last_sequence, jpeg = frame
                    try:
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                        self.wfile.write(jpeg)
                        self.wfile.write(b"\r\n")
                    except (BrokenPipeError, ConnectionError, OSError):
                        return

        return PreviewRequestHandler


_INDEX_HTML = """<!doctype html>
<html lang="da">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pallet camera preview</title>
  <style>
    html, body { margin: 0; min-height: 100%; background: #111; color: #eee; font-family: system-ui, sans-serif; }
    main { min-height: 100vh; display: grid; grid-template-rows: auto 1fr; }
    header { padding: 10px 14px; font-size: 14px; background: #1c1c1c; }
    img { display: block; width: 100%; height: calc(100vh - 42px); object-fit: contain; background: #000; }
  </style>
</head>
<body>
  <main>
    <header>Live kamera-preview</header>
    <img src="/stream.mjpg" alt="Live kamera-preview">
  </main>
</body>
</html>
"""
