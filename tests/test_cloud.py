from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from pallet_video_recorder.cloud import _absolute_storage_url, build_storage_path, read_temperature_c, sha256_file


class CloudTest(unittest.TestCase):
    def test_reads_pi_temperature_millidegrees(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "temp"
            path.write_text("51234\n", encoding="utf-8")

            self.assertEqual(read_temperature_c(path), 51.2)

    def test_reads_temperature_degrees(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "temp"
            path.write_text("48.6\n", encoding="utf-8")

            self.assertEqual(read_temperature_c(path), 48.6)

    def test_missing_temperature_is_optional(self) -> None:
        self.assertIsNone(read_temperature_c(Path("/definitely/missing/palletproof/temp")))

    def test_builds_safe_storage_path(self) -> None:
        self.assertEqual(
            build_storage_path("device-uploads", "PP/000123", "REF/123_20260724_120000.mp4"),
            "device-uploads/PP_000123/REF_123_20260724_120000.mp4",
        )

    def test_builds_absolute_signed_storage_upload_url(self) -> None:
        self.assertEqual(
            _absolute_storage_url(
                "https://example.supabase.co",
                "/object/upload/sign/videos/device-uploads/PP/video.mp4?token=abc",
            ),
            "https://example.supabase.co/storage/v1/object/upload/sign/videos/device-uploads/PP/video.mp4?token=abc",
        )

    def test_keeps_absolute_signed_storage_upload_url(self) -> None:
        self.assertEqual(
            _absolute_storage_url(
                "https://example.supabase.co",
                "https://example.supabase.co/storage/v1/object/upload/sign/videos/video.mp4?token=abc",
            ),
            "https://example.supabase.co/storage/v1/object/upload/sign/videos/video.mp4?token=abc",
        )

    def test_hashes_file_for_upload_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "video.mp4"
            path.write_bytes(b"palletproof")

            self.assertEqual(
                sha256_file(path),
                "8e6aced578464134a62f953604243aecb2724342fe8edef4c23757aea9894e20",
            )


if __name__ == "__main__":
    unittest.main()
