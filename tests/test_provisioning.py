from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pallet_video_recorder.provisioning import (
    DeviceIdentityStore,
    ProvisioningError,
    build_provisioning_qr,
    build_reset_qr,
    looks_like_provisioning_qr,
    looks_like_reset_qr,
    parse_provisioning_qr,
    parse_reset_qr,
)


class ProvisioningTest(unittest.TestCase):
    def test_parses_base64url_provisioning_qr(self) -> None:
        value = build_provisioning_qr(
            {
                "serial_number": "PP-000123",
                "customer_id": "CUST-001",
                "site_id": "RHENUS-HORSENS",
                "activation_token": "tok_123",
                "wifi": {"ssid": "WarehouseWifi", "password": "secret-password"},
                "api_base_url": "https://api.example.com",
                "expires_at": "2026-08-01T00:00:00Z",
            }
        )

        payload = parse_provisioning_qr(
            value,
            now=datetime(2026, 7, 23, tzinfo=timezone.utc),
        )

        self.assertTrue(looks_like_provisioning_qr(value))
        self.assertEqual(payload.serial_number, "PP-000123")
        self.assertEqual(payload.customer_id, "CUST-001")
        self.assertEqual(payload.site_id, "RHENUS-HORSENS")
        self.assertEqual(payload.wifi_ssid, "WarehouseWifi")
        self.assertEqual(payload.wifi_password, "secret-password")
        self.assertEqual(payload.api_base_url, "https://api.example.com")

    def test_parses_prefixed_json_provisioning_qr(self) -> None:
        raw_json = json.dumps(
            {
                "version": 1,
                "serial_number": "PP-000124",
                "activation_token": "tok_124",
                "wifi_ssid": "WarehouseWifi",
                "wifi_password": "secret-password",
            }
        )

        payload = parse_provisioning_qr(f"PALLETPROOF:{raw_json}")

        self.assertEqual(payload.serial_number, "PP-000124")
        self.assertEqual(payload.wifi_ssid, "WarehouseWifi")

    def test_rejects_expired_qr(self) -> None:
        value = build_provisioning_qr(
            {
                "serial_number": "PP-000125",
                "activation_token": "tok_125",
                "wifi_ssid": "WarehouseWifi",
                "wifi_password": "secret-password",
                "expires_at": "2026-07-01T00:00:00Z",
            }
        )

        with self.assertRaises(ProvisioningError):
            parse_provisioning_qr(value, now=datetime(2026, 7, 23, tzinfo=timezone.utc))

    def test_rejects_missing_wifi(self) -> None:
        value = build_provisioning_qr(
            {
                "serial_number": "PP-000126",
                "activation_token": "tok_126",
            }
        )

        with self.assertRaises(ProvisioningError):
            parse_provisioning_qr(value)

    def test_identity_store_does_not_persist_wifi_password(self) -> None:
        value = build_provisioning_qr(
            {
                "serial_number": "PP-000127",
                "activation_token": "tok_127",
                "wifi_ssid": "WarehouseWifi",
                "wifi_password": "secret-password",
            }
        )
        identity = parse_provisioning_qr(value).to_identity(
            datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            store = DeviceIdentityStore(Path(temp_dir) / "identity.json")
            store.save(identity)
            raw_file = store.path.read_text(encoding="utf-8")
            loaded = store.load()

        self.assertNotIn("secret-password", raw_file)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.serial_number, "PP-000127")
        self.assertEqual(loaded.wifi_ssid, "WarehouseWifi")

    def test_parses_device_specific_reset_qr(self) -> None:
        value = build_reset_qr("PP-000128")

        payload = parse_reset_qr(value)

        self.assertTrue(looks_like_reset_qr(value))
        self.assertFalse(looks_like_provisioning_qr(value))
        self.assertEqual(payload.serial_number, "PP-000128")

    def test_rejects_provisioning_qr_as_reset_qr(self) -> None:
        value = build_provisioning_qr(
            {
                "serial_number": "PP-000129",
                "activation_token": "tok_129",
                "wifi_ssid": "WarehouseWifi",
                "wifi_password": "secret-password",
            }
        )

        with self.assertRaises(ProvisioningError):
            parse_reset_qr(value)


if __name__ == "__main__":
    unittest.main()
