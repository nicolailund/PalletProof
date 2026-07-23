from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Paths, SoftwareUpdateConfig
from . import __version__

LOGGER = logging.getLogger(__name__)

POLICY_FORCE = "force"
POLICY_NIGHT = "night"
VALID_POLICIES = {POLICY_FORCE, POLICY_NIGHT}
POLICY_ALIASES = {
    "force": POLICY_FORCE,
    "force_push": POLICY_FORCE,
    "force-push": POLICY_FORCE,
    "night": POLICY_NIGHT,
    "night_push": POLICY_NIGHT,
    "night-push": POLICY_NIGHT,
}


class SoftwareUpdateError(ValueError):
    pass


@dataclass(frozen=True)
class UpdateManifest:
    update_id: str
    policy: str
    target_ref: str = "main"
    target_commit: str = ""
    version: str = ""
    created_at: str = ""
    description: str = ""


class SoftwareUpdateStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as handle:
            values = json.load(handle)
        if not isinstance(values, dict):
            raise SoftwareUpdateError(f"Software update state is not a JSON object: {self.path}")
        return values

    def save(self, values: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f".{self.path.name}.tmp")
        with temporary_path.open("w", encoding="utf-8") as handle:
            json.dump(values, handle, indent=2, sort_keys=True)
            handle.write("\n")
        try:
            os.chmod(temporary_path, 0o600)
        except OSError:
            pass
        temporary_path.replace(self.path)

    def mark_attempt(self, manifest: UpdateManifest, error: str = "") -> None:
        state = self.load()
        state.update(
            {
                "last_attempted_update_id": manifest.update_id,
                "last_attempted_at": _timestamp(),
                "last_error": error,
            }
        )
        self.save(state)

    def mark_applied(self, manifest: UpdateManifest) -> None:
        state = self.load()
        state.update(
            {
                "applied_update_id": manifest.update_id,
                "applied_at": _timestamp(),
                "applied_policy": manifest.policy,
                "applied_target_ref": manifest.target_ref,
                "applied_target_commit": manifest.target_commit,
                "applied_version": manifest.version,
                "last_error": "",
            }
        )
        self.save(state)


class SoftwareUpdateWorker:
    def __init__(
        self,
        config: SoftwareUpdateConfig,
        paths: Paths,
        *,
        current_version: str = __version__,
    ) -> None:
        self.config = config
        self.paths = paths
        self.current_version = current_version
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.pending: UpdateManifest | None = None
        self.last_apply_attempt_at = 0.0
        self.state_store = SoftwareUpdateStateStore(self._state_path())

    def start(self) -> None:
        if not self.config.enabled:
            LOGGER.info("Software update checks are disabled")
            return
        self.thread = threading.Thread(target=self._run, name="software-update-worker", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=5)
            self.thread = None

    def check_once(self) -> UpdateManifest | None:
        if not self.config.enabled:
            return None

        try:
            manifest = self._fetch_manifest()
            if self._already_applied(manifest):
                with self.lock:
                    self.pending = None
                return None
            with self.lock:
                self.pending = manifest
            LOGGER.info(
                "Software update pending update_id=%s policy=%s version=%s target_ref=%s target_commit=%s",
                manifest.update_id,
                manifest.policy,
                manifest.version or "-",
                manifest.target_ref,
                manifest.target_commit or "-",
            )
            return manifest
        except Exception:
            LOGGER.exception("Software update check failed")
            return None

    def pending_update(self) -> UpdateManifest | None:
        with self.lock:
            return self.pending

    def ready_to_apply(self, idle_seconds: float, now: datetime | None = None) -> bool:
        manifest = self.pending_update()
        if manifest is None:
            return False
        if idle_seconds < self.config.idle_grace_seconds:
            return False
        if self.last_apply_attempt_at and time.monotonic() - self.last_apply_attempt_at < self.config.apply_retry_seconds:
            return False
        if manifest.policy == POLICY_FORCE:
            return True
        if manifest.policy == POLICY_NIGHT:
            return is_in_night_window(now or datetime.now(), self.config.night_start_hour, self.config.night_end_hour)
        return False

    def apply_pending(self) -> bool:
        manifest = self.pending_update()
        if manifest is None:
            return False

        self.last_apply_attempt_at = time.monotonic()
        argv = shlex.split(self.config.install_command)
        if not argv:
            raise SoftwareUpdateError("software_update.install_command produced no executable")

        env = dict(os.environ)
        env.update(
            {
                "PALLETPROOF_UPDATE_ID": manifest.update_id,
                "PALLETPROOF_TARGET_REF": manifest.target_ref,
                "PALLETPROOF_TARGET_COMMIT": manifest.target_commit,
                "PALLETPROOF_TARGET_VERSION": manifest.version,
                "PALLETPROOF_CURRENT_VERSION": self.current_version,
                "PALLETPROOF_REPO_DIR": str(self._repository_dir()),
            }
        )

        LOGGER.warning(
            "Applying software update update_id=%s policy=%s target_ref=%s target_commit=%s",
            manifest.update_id,
            manifest.policy,
            manifest.target_ref,
            manifest.target_commit or "-",
        )
        self.state_store.mark_attempt(manifest)
        try:
            subprocess.run(
                argv,
                cwd=self._repository_dir(),
                env=env,
                timeout=self.config.install_timeout_seconds,
                check=True,
            )
        except Exception as exc:
            error = str(exc)
            self.state_store.mark_attempt(manifest, error=error)
            LOGGER.exception("Software update install command failed for update_id=%s", manifest.update_id)
            return False

        self.state_store.mark_applied(manifest)
        with self.lock:
            self.pending = None
        LOGGER.warning("Software update applied; service should restart to load new code")
        return True

    def _run(self) -> None:
        while not self.stop_event.is_set():
            self.check_once()
            self.stop_event.wait(self.config.check_interval_seconds)

    def _fetch_manifest(self) -> UpdateManifest:
        request = urllib.request.Request(
            self.config.manifest_url,
            headers={"User-Agent": f"PalletProof/{self.current_version}"},
        )
        with urllib.request.urlopen(request, timeout=self.config.request_timeout_seconds) as response:
            raw = response.read().decode("utf-8")
        return parse_update_manifest(raw)

    def _already_applied(self, manifest: UpdateManifest) -> bool:
        state = self.state_store.load()
        return state.get("applied_update_id") == manifest.update_id

    def _state_path(self) -> Path:
        path = self.config.state_file
        if path.is_absolute():
            return path
        return self.paths.root / path

    def _repository_dir(self) -> Path:
        return self.config.repository_dir


def parse_update_manifest(raw_json: str) -> UpdateManifest:
    try:
        values = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise SoftwareUpdateError("Update manifest contains invalid JSON") from exc
    if not isinstance(values, dict):
        raise SoftwareUpdateError("Update manifest must be a JSON object")

    schema_version = int(values.get("schema_version", 1))
    if schema_version != 1:
        raise SoftwareUpdateError(f"Unsupported update manifest schema_version: {schema_version}")

    update_id = str(values.get("update_id", "")).strip()
    if not update_id:
        raise SoftwareUpdateError("Update manifest is missing update_id")

    policy = normalize_policy(str(values.get("policy", "")))
    target_ref = str(values.get("target_ref", "main")).strip() or "main"
    target_commit = str(values.get("target_commit", "")).strip()
    version = str(values.get("version", "")).strip()
    created_at = str(values.get("created_at", "")).strip()
    description = str(values.get("description", "")).strip()

    return UpdateManifest(
        update_id=update_id,
        policy=policy,
        target_ref=target_ref,
        target_commit=target_commit,
        version=version,
        created_at=created_at,
        description=description,
    )


def normalize_policy(value: str) -> str:
    policy = POLICY_ALIASES.get(value.strip().lower())
    if policy not in VALID_POLICIES:
        raise SoftwareUpdateError("Update policy must be 'force' or 'night'")
    return policy


def is_in_night_window(now: datetime, start_hour: int, end_hour: int) -> bool:
    current_hour = now.hour
    if start_hour < end_hour:
        return start_hour <= current_hour < end_hour
    return current_hour >= start_hour or current_hour < end_hour


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
