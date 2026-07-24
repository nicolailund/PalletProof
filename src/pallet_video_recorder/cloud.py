from __future__ import annotations

from dataclasses import dataclass
import hashlib
import http.client
import json
import logging
import posixpath
from pathlib import Path
import socket
import urllib.error
import urllib.request
from urllib.parse import quote, urlparse

from .config import CloudConfig, Paths
from .filenames import sanitize_filename_part
from .provisioning import DeviceIdentity

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CloudResult:
    ok: bool
    message: str = ""
    data: dict[str, object] | None = None


@dataclass(frozen=True)
class SignedUpload:
    signed_url: str
    token: str
    path: str


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

    def create_signed_upload_url(self, identity: DeviceIdentity, *, bucket: str, storage_path: str) -> SignedUpload:
        if not self._can_send(identity):
            raise RuntimeError("cloud disabled or missing credentials")

        encoded_path = _storage_object_url_path(bucket, storage_path)
        url = f"{self.config.supabase_url.rstrip('/')}/storage/v1/object/upload/sign/{encoded_path}"
        response = self._post_storage_json(url, {})
        signed_url = str(response.get("signedUrl") or response.get("signedURL") or "")
        token = str(response.get("token") or "")
        response_path = str(response.get("path") or storage_path)

        if not signed_url:
            relative_url = str(response.get("url") or "")
            if relative_url:
                signed_url = _absolute_storage_url(self.config.supabase_url, relative_url)
        else:
            signed_url = _absolute_storage_url(self.config.supabase_url, signed_url)
        if not token and "token=" in signed_url:
            parsed = urlparse(signed_url)
            token = _query_value(parsed.query, "token")
        if not signed_url or not token:
            raise RuntimeError("Supabase did not return a signed upload URL and token")

        return SignedUpload(signed_url=signed_url, token=token, path=response_path)

    def upload_to_signed_url(self, signed_upload: SignedUpload, path: Path, *, content_type: str = "video/mp4") -> None:
        parsed = urlparse(signed_upload.signed_url)
        connection_class = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        target = parsed.path
        if parsed.query:
            target += "?" + parsed.query
        headers = {
            "cache-control": "max-age=3600",
            "content-type": content_type,
            "content-length": str(path.stat().st_size),
            "x-upsert": "false",
        }
        connection = connection_class(parsed.netloc, timeout=self.config.request_timeout_seconds)
        try:
            with path.open("rb") as handle:
                connection.request("PUT", target, body=handle, headers=headers)
            response = connection.getresponse()
            body = response.read().decode("utf-8", errors="replace")
            if response.status >= 400:
                raise RuntimeError(f"Supabase Storage upload failed with HTTP {response.status}: {_shorten(body)}")
        finally:
            connection.close()

    def register_video_upload(
        self,
        identity: DeviceIdentity,
        *,
        scanned_id: str,
        filename: str,
        storage_bucket: str,
        storage_path: str,
        size_bytes: int,
        started_at: str = "",
        ended_at: str = "",
        duration_seconds: float | None = None,
        checksum_sha256: str = "",
        metadata: dict[str, object] | None = None,
    ) -> CloudResult:
        if not self._can_send(identity):
            return CloudResult(False, "cloud disabled or missing credentials")
        payload: dict[str, object] = {
            "p_serial_number": identity.serial_number,
            "p_activation_token": identity.activation_token,
            "p_scanned_id": scanned_id,
            "p_filename": filename,
            "p_storage_bucket": storage_bucket,
            "p_storage_path": storage_path,
            "p_size_bytes": size_bytes,
            "p_started_at": started_at or None,
            "p_ended_at": ended_at or None,
            "p_duration_seconds": duration_seconds,
            "p_checksum_sha256": checksum_sha256,
            "p_metadata": metadata or {},
        }
        return self._call_rpc("register_video_upload", payload)

    def device_event(
        self,
        identity: DeviceIdentity,
        *,
        event_type: str,
        severity: str = "info",
        message: str = "",
        metadata: dict[str, object] | None = None,
    ) -> CloudResult:
        if not self._can_send(identity):
            return CloudResult(False, "cloud disabled or missing credentials")
        return self._call_rpc(
            "device_event",
            {
                "p_serial_number": identity.serial_number,
                "p_activation_token": identity.activation_token,
                "p_event_type": event_type,
                "p_severity": severity,
                "p_message": message,
                "p_metadata": metadata or {},
            },
        )

    def upload_video_file(
        self,
        identity: DeviceIdentity,
        path: Path,
        *,
        bucket: str,
        storage_path: str,
        scanned_id: str,
        started_at: str = "",
        ended_at: str = "",
        duration_seconds: float | None = None,
        metadata: dict[str, object] | None = None,
    ) -> CloudResult:
        try:
            signed_upload = self.create_signed_upload_url(identity, bucket=bucket, storage_path=storage_path)
            self.upload_to_signed_url(signed_upload, path)
            return self.register_video_upload(
                identity,
                scanned_id=scanned_id,
                filename=path.name,
                storage_bucket=bucket,
                storage_path=storage_path,
                size_bytes=path.stat().st_size,
                started_at=started_at,
                ended_at=ended_at,
                duration_seconds=duration_seconds,
                checksum_sha256=sha256_file(path),
                metadata=metadata,
            )
        except Exception as exc:
            LOGGER.warning("Supabase video upload failed for %s: %s", path.name, _shorten(str(exc)))
            return CloudResult(False, str(exc))

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
                response_body = response.read().decode("utf-8", errors="replace")
            return CloudResult(True, data=_json_dict(response_body))
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

    def _post_storage_json(self, url: str, payload: dict[str, object]) -> dict[str, object]:
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
                response_body = response.read().decode("utf-8", errors="replace")
            return _json_dict(response_body)
        except urllib.error.HTTPError as exc:
            raw_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Supabase Storage signed URL failed with HTTP {exc.code}: {_shorten(raw_body)}") from exc


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


def build_storage_path(prefix: str, serial_number: str, filename: str) -> str:
    safe_serial = sanitize_filename_part(serial_number, "Serial number", max_length=64)
    safe_filename = sanitize_filename_part(filename, "Filename", max_length=160)
    parts = [part.strip("/") for part in (prefix, safe_serial, safe_filename) if part.strip("/")]
    return posixpath.join(*parts)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _storage_object_url_path(bucket: str, object_path: str) -> str:
    encoded_bucket = quote(bucket.strip("/"), safe="")
    encoded_object = "/".join(quote(part, safe="") for part in object_path.strip("/").split("/"))
    return f"{encoded_bucket}/{encoded_object}"


def _absolute_storage_url(supabase_url: str, url: str) -> str:
    if url.startswith(("http://", "https://")):
        return url

    base_url = supabase_url.rstrip("/")
    relative_url = url if url.startswith("/") else f"/{url}"
    if relative_url.startswith("/storage/v1/"):
        return base_url + relative_url
    if relative_url.startswith("/object/"):
        return base_url + "/storage/v1" + relative_url
    return base_url + relative_url


def _query_value(query: str, key: str) -> str:
    for part in query.split("&"):
        name, _, value = part.partition("=")
        if name == key:
            return value
    return ""


def _json_dict(raw_json: str) -> dict[str, object]:
    if not raw_json.strip():
        return {}
    value = json.loads(raw_json)
    if isinstance(value, dict):
        return value
    return {"value": value}
