from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import socket
import urllib.error
import urllib.request

from .config import CloudConfig, Paths
from .provisioning import DeviceIdentity

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CloudResult:
    ok: bool
    message: str = ""


class SupabaseDeviceClient:
    def __init__(self, config: CloudConfig, paths: Paths) -> None:
        self.config = config
        self.paths = paths

    def activate(self, identity: DeviceIdentity, software_version: str, metadata: dict[str, object]) -> CloudResult:
        if not self._can_send(identity):
            return CloudResult(False, "cloud disabled or missing credentials")
        return self._call_rpc(
            "activate_device",
            {
                "p_serial_number": identity.serial_number,
                "p_activation_token": identity.activation_token,
                "p_software_version": software_version,
                "p_metadata": metadata,
            },
        )

    def heartbeat(
        self,
        identity: DeviceIdentity,
        *,
        status: str,
        software_version: str,
        last_update_id: str,
        metadata: dict[str, object],
    ) -> CloudResult:
        if not self._can_send(identity):
            return CloudResult(False, "cloud disabled or missing credentials")
        return self._call_rpc(
            "device_heartbeat",
            {
                "p_serial_number": identity.serial_number,
                "p_activation_token": identity.activation_token,
                "p_status": status,
                "p_software_version": software_version,
                "p_last_update_id": last_update_id,
                "p_metadata": metadata,
            },
        )

    def build_metadata(self) -> dict[str, object]:
        metadata: dict[str, object] = {
            "hostname": socket.gethostname(),
            "pending_uploads": _count_files(self.paths.pending),
            "failed_uploads": _count_files(self.paths.failed),
        }
        temperature_c = read_temperature_c(self.config.temperature_file)
        if temperature_c is not None:
            metadata["temperature_c"] = temperature_c
        return metadata

    def _can_send(self, identity: DeviceIdentity) -> bool:
        return bool(
            self.config.enabled
            and self.config.supabase_url.strip()
            and self.config.supabase_anon_key.strip()
            and identity.provisioned
            and identity.activation_token.strip()
        )

    def _call_rpc(self, rpc_name: str, payload: dict[str, object]) -> CloudResult:
        url = self._rpc_url(rpc_name)
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "apikey": self.config.supabase_anon_key,
                "Authorization": f"Bearer {self.config.supabase_anon_key}",
                "Content-Type": "application/json",
                "User-Agent": "PalletProofDevice/0.1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.request_timeout_seconds) as response:
                response.read()
            return CloudResult(True)
        except urllib.error.HTTPError as exc:
            raw_body = exc.read().decode("utf-8", errors="replace")
            message = _shorten(raw_body or exc.reason)
            LOGGER.warning("Supabase RPC %s failed with HTTP %s: %s", rpc_name, exc.code, message)
            return CloudResult(False, message)
        except Exception as exc:
            message = _shorten(str(exc))
            LOGGER.warning("Supabase RPC %s failed: %s", rpc_name, message)
            return CloudResult(False, message)

    def _rpc_url(self, rpc_name: str) -> str:
        base_url = self.config.supabase_url.rstrip("/")
        return f"{base_url}/rest/v1/rpc/{rpc_name}"


def read_temperature_c(path: Path) -> float | None:
    try:
        raw_value = path.read_text(encoding="utf-8").strip()
        if not raw_value:
            return None
        value = float(raw_value)
    except (OSError, ValueError):
        return None

    if value > 1000:
        value = value / 1000.0
    return round(value, 1)


def _count_files(path: Path) -> int:
    try:
        return sum(1 for candidate in path.iterdir() if candidate.is_file())
    except OSError:
        return 0


def _shorten(value: str, limit: int = 240) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "..."
