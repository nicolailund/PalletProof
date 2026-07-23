from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROVISIONING_PREFIX = "PALLETPROOF"
PROVISIONING_VERSION = 1
RESET_PAYLOAD_TYPE = "palletproof_reset"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class ProvisioningError(ValueError):
    pass


@dataclass(frozen=True)
class ProvisioningPayload:
    serial_number: str
    activation_token: str
    wifi_ssid: str
    wifi_password: str
    version: int = PROVISIONING_VERSION
    customer_id: str = ""
    site_id: str = ""
    api_base_url: str = ""
    issued_at: str = ""
    expires_at: str = ""
    signature: str = ""

    def to_identity(self, activated_at: datetime | None = None) -> "DeviceIdentity":
        activated = activated_at or datetime.now(timezone.utc)
        return DeviceIdentity(
            serial_number=self.serial_number,
            customer_id=self.customer_id,
            site_id=self.site_id,
            activation_token=self.activation_token,
            api_base_url=self.api_base_url,
            wifi_ssid=self.wifi_ssid,
            activated_at=_format_datetime(activated),
            provisioning_version=self.version,
        )


@dataclass(frozen=True)
class ResetPayload:
    serial_number: str
    version: int = PROVISIONING_VERSION


@dataclass(frozen=True)
class DeviceIdentity:
    serial_number: str
    customer_id: str = ""
    site_id: str = ""
    activation_token: str = ""
    api_base_url: str = ""
    wifi_ssid: str = ""
    activated_at: str = ""
    provisioning_version: int = PROVISIONING_VERSION
    provisioned: bool = True

    @classmethod
    def unmanaged(cls, serial_number: str) -> "DeviceIdentity":
        return cls(
            serial_number=normalize_identifier(serial_number, "serial_number"),
            provisioned=False,
        )

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "DeviceIdentity":
        serial_number = normalize_identifier(str(values.get("serial_number", "")), "serial_number")
        customer_id = _optional_identifier(values.get("customer_id", ""), "customer_id")
        site_id = _optional_identifier(values.get("site_id", ""), "site_id")
        return cls(
            serial_number=serial_number,
            customer_id=customer_id,
            site_id=site_id,
            activation_token=str(values.get("activation_token", "")),
            api_base_url=str(values.get("api_base_url", "")),
            wifi_ssid=str(values.get("wifi_ssid", "")),
            activated_at=str(values.get("activated_at", "")),
            provisioning_version=int(values.get("provisioning_version", PROVISIONING_VERSION)),
            provisioned=bool(values.get("provisioned", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "serial_number": self.serial_number,
            "customer_id": self.customer_id,
            "site_id": self.site_id,
            "activation_token": self.activation_token,
            "api_base_url": self.api_base_url,
            "wifi_ssid": self.wifi_ssid,
            "activated_at": self.activated_at,
            "provisioning_version": self.provisioning_version,
            "provisioned": self.provisioned,
        }


class DeviceIdentityStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> DeviceIdentity | None:
        if not self.path.exists():
            return None
        with self.path.open("r", encoding="utf-8") as handle:
            values = json.load(handle)
        if not isinstance(values, dict):
            raise ProvisioningError(f"Device identity file is not a JSON object: {self.path}")
        return DeviceIdentity.from_dict(values)

    def save(self, identity: DeviceIdentity) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f".{self.path.name}.tmp")
        with temporary_path.open("w", encoding="utf-8") as handle:
            json.dump(identity.to_dict(), handle, indent=2, sort_keys=True)
            handle.write("\n")
        try:
            os.chmod(temporary_path, 0o600)
        except OSError:
            pass
        temporary_path.replace(self.path)

    def delete(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def parse_provisioning_qr(
    raw_value: str,
    *,
    prefix: str = PROVISIONING_PREFIX,
    now: datetime | None = None,
) -> ProvisioningPayload:
    data = _decode_payload(raw_value.strip(), prefix)
    version = int(data.get("version", PROVISIONING_VERSION))
    if version != PROVISIONING_VERSION:
        raise ProvisioningError(f"Unsupported provisioning version: {version}")

    payload_type = str(data.get("type", "palletproof_provisioning"))
    if payload_type != "palletproof_provisioning":
        raise ProvisioningError(f"Unsupported provisioning payload type: {payload_type!r}")

    serial_number = normalize_identifier(_required_string(data, "serial_number"), "serial_number")
    activation_token = _required_string(data, "activation_token")
    wifi_ssid, wifi_password = _wifi_fields(data)
    customer_id = _optional_identifier(data.get("customer_id", ""), "customer_id")
    site_id = _optional_identifier(data.get("site_id", ""), "site_id")
    api_base_url = str(data.get("api_base_url", "")).strip()
    issued_at = str(data.get("issued_at", "")).strip()
    expires_at = str(data.get("expires_at", "")).strip()
    signature = str(data.get("signature", "")).strip()

    if expires_at:
        expires = _parse_datetime(expires_at, "expires_at")
        current = now or datetime.now(timezone.utc)
        if expires <= _as_utc(current):
            raise ProvisioningError("Provisioning QR has expired")

    return ProvisioningPayload(
        version=version,
        serial_number=serial_number,
        customer_id=customer_id,
        site_id=site_id,
        activation_token=activation_token,
        wifi_ssid=wifi_ssid,
        wifi_password=wifi_password,
        api_base_url=api_base_url,
        issued_at=issued_at,
        expires_at=expires_at,
        signature=signature,
    )


def build_provisioning_qr(payload: dict[str, Any], *, prefix: str = PROVISIONING_PREFIX) -> str:
    values = dict(payload)
    values.setdefault("version", PROVISIONING_VERSION)
    values.setdefault("type", "palletproof_provisioning")
    raw_json = json.dumps(values, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw_json).decode("ascii").rstrip("=")
    return f"{prefix}{PROVISIONING_VERSION}.{encoded}"


def build_reset_qr(serial_number: str, *, prefix: str = PROVISIONING_PREFIX) -> str:
    payload = {
        "type": RESET_PAYLOAD_TYPE,
        "version": PROVISIONING_VERSION,
        "serial_number": normalize_identifier(serial_number, "serial_number"),
    }
    raw_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw_json).decode("ascii").rstrip("=")
    return f"{prefix}RESET{PROVISIONING_VERSION}.{encoded}"


def looks_like_provisioning_qr(raw_value: str, *, prefix: str = PROVISIONING_PREFIX) -> bool:
    value = raw_value.strip()
    return value.startswith(f"{prefix}{PROVISIONING_VERSION}.") or value.startswith(f"{prefix}:")


def looks_like_reset_qr(raw_value: str, *, prefix: str = PROVISIONING_PREFIX) -> bool:
    return raw_value.strip().startswith(f"{prefix}RESET{PROVISIONING_VERSION}.")


def parse_reset_qr(raw_value: str, *, prefix: str = PROVISIONING_PREFIX) -> ResetPayload:
    value = raw_value.strip()
    if not looks_like_reset_qr(value, prefix=prefix):
        raise ProvisioningError("Scanned value is not a PalletProof reset QR")

    encoded = value.split(".", 1)[1]
    padding = "=" * (-len(encoded) % 4)
    try:
        raw_json = base64.urlsafe_b64decode((encoded + padding).encode("ascii"))
    except Exception as exc:
        raise ProvisioningError("Reset QR contains invalid base64url data") from exc
    data = _json_object(raw_json.decode("utf-8"))

    version = int(data.get("version", PROVISIONING_VERSION))
    if version != PROVISIONING_VERSION:
        raise ProvisioningError(f"Unsupported reset QR version: {version}")
    payload_type = str(data.get("type", ""))
    if payload_type != RESET_PAYLOAD_TYPE:
        raise ProvisioningError(f"Unsupported reset QR payload type: {payload_type!r}")

    return ResetPayload(serial_number=normalize_identifier(_required_string(data, "serial_number"), "serial_number"))


def normalize_identifier(value: str, name: str) -> str:
    normalized = value.strip()
    if IDENTIFIER.fullmatch(normalized) is None:
        raise ProvisioningError(f"{name} must be 1-64 safe characters")
    return normalized


def _decode_payload(raw_value: str, prefix: str) -> dict[str, Any]:
    if raw_value.startswith(f"{prefix}{PROVISIONING_VERSION}."):
        encoded = raw_value.split(".", 1)[1]
        padding = "=" * (-len(encoded) % 4)
        try:
            raw_json = base64.urlsafe_b64decode((encoded + padding).encode("ascii"))
        except Exception as exc:
            raise ProvisioningError("Provisioning QR contains invalid base64url data") from exc
        return _json_object(raw_json.decode("utf-8"))

    if raw_value.startswith(f"{prefix}:"):
        return _json_object(raw_value.split(":", 1)[1])

    raise ProvisioningError("Scanned value is not a PalletProof provisioning QR")


def _json_object(raw_json: str) -> dict[str, Any]:
    try:
        values = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ProvisioningError("Provisioning QR contains invalid JSON") from exc
    if not isinstance(values, dict):
        raise ProvisioningError("Provisioning QR JSON must be an object")
    return values


def _required_string(values: dict[str, Any], name: str) -> str:
    value = str(values.get(name, "")).strip()
    if not value:
        raise ProvisioningError(f"Provisioning QR is missing {name}")
    return value


def _wifi_fields(values: dict[str, Any]) -> tuple[str, str]:
    wifi = values.get("wifi", {})
    if wifi is None:
        wifi = {}
    if not isinstance(wifi, dict):
        raise ProvisioningError("Provisioning QR wifi field must be an object")
    ssid = str(values.get("wifi_ssid", wifi.get("ssid", ""))).strip()
    password = str(values.get("wifi_password", wifi.get("password", "")))
    if not ssid:
        raise ProvisioningError("Provisioning QR is missing wifi_ssid")
    if not password:
        raise ProvisioningError("Provisioning QR is missing wifi_password")
    return ssid, password


def _optional_identifier(value: object, name: str) -> str:
    text = str(value).strip()
    if not text:
        return ""
    return normalize_identifier(text, name)


def _parse_datetime(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProvisioningError(f"{name} must be ISO-8601") from exc
    return _as_utc(parsed)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_datetime(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")
