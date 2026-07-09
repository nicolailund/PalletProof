from __future__ import annotations

import ftplib
import logging
import posixpath
import shutil
import threading
import time
from pathlib import Path

from .config import Paths, UploadConfig

LOGGER = logging.getLogger(__name__)


class UploadWorker:
    def __init__(self, config: UploadConfig, paths: Paths) -> None:
        self.config = config
        self.paths = paths
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.config.enabled:
            LOGGER.info("Upload is disabled")
            return
        self.thread = threading.Thread(target=self._run, name="upload-worker", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
        if self.thread is not None:
            self.thread.join(timeout=10)
            self.thread = None

    def wake(self) -> None:
        self.wake_event.set()

    def _run(self) -> None:
        while not self.stop_event.is_set():
            self._upload_pending_once()
            self.wake_event.wait(self.config.retry_seconds)
            self.wake_event.clear()

    def _upload_pending_once(self) -> None:
        for path in sorted(self.paths.pending.iterdir()):
            if self.stop_event.is_set():
                return
            if not path.is_file() or path.name.endswith(self.config.temp_suffix):
                continue
            try:
                self._upload_file(path)
                self._after_success(path)
            except Exception:
                LOGGER.exception("Upload failed for %s; will retry", path)

    def _upload_file(self, path: Path) -> None:
        if not self.config.host:
            raise RuntimeError("Upload host is not configured")

        if self.config.protocol.lower() == "sftp":
            self._upload_file_sftp(path)
            return

        self._upload_file_ftp(path)

    def _upload_file_ftp(self, path: Path) -> None:
        LOGGER.info("Uploading %s to %s://%s%s", path.name, self.config.protocol, self.config.host, self.config.remote_dir)
        ftp = self._connect()
        try:
            self._ensure_remote_dir(ftp, self.config.remote_dir)
            remote_name = path.name
            temp_name = remote_name + self.config.temp_suffix
            with path.open("rb") as handle:
                ftp.storbinary(f"STOR {temp_name}", handle)
            try:
                ftp.delete(remote_name)
            except ftplib.error_perm:
                pass
            ftp.rename(temp_name, remote_name)
        finally:
            try:
                ftp.quit()
            except Exception:
                ftp.close()

    def _upload_file_sftp(self, path: Path) -> None:
        try:
            import paramiko
        except Exception as exc:
            raise RuntimeError("SFTP upload requires paramiko. Install python3-paramiko on the Pi.") from exc

        LOGGER.info("Uploading %s to sftp://%s:%s%s", path.name, self.config.host, self.config.port, self.config.remote_dir)
        transport = paramiko.Transport((self.config.host, self.config.port))
        transport.banner_timeout = self.config.timeout_seconds
        transport.auth_timeout = self.config.timeout_seconds
        transport.connect(username=self.config.username, password=self.config.password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        try:
            self._ensure_sftp_dir(sftp, self.config.remote_dir)
            remote_name = path.name
            temp_name = remote_name + self.config.temp_suffix
            temp_path = _remote_path(self.config.remote_dir, temp_name)
            final_path = _remote_path(self.config.remote_dir, remote_name)
            sftp.put(str(path), temp_path)
            try:
                sftp.remove(final_path)
            except OSError:
                pass
            sftp.rename(temp_path, final_path)
        finally:
            sftp.close()
            transport.close()

    def _connect(self) -> ftplib.FTP:
        protocol = self.config.protocol.lower()
        if protocol == "ftps":
            ftp: ftplib.FTP = ftplib.FTP_TLS(timeout=self.config.timeout_seconds)
        elif protocol == "ftp":
            ftp = ftplib.FTP(timeout=self.config.timeout_seconds)
        else:
            raise ValueError(f"Unsupported upload protocol: {self.config.protocol}")

        ftp.connect(self.config.host, self.config.port)
        ftp.login(self.config.username, self.config.password)
        ftp.set_pasv(self.config.passive)
        if isinstance(ftp, ftplib.FTP_TLS):
            ftp.prot_p()
        return ftp

    def _ensure_sftp_dir(self, sftp: object, remote_dir: str) -> None:
        if not remote_dir or remote_dir in ("/", "."):
            return

        current = "/" if remote_dir.startswith("/") else "."
        for part in remote_dir.strip("/").split("/"):
            current = posixpath.join(current, part)
            try:
                sftp.mkdir(current)  # type: ignore[attr-defined]
            except OSError:
                pass

    def _ensure_remote_dir(self, ftp: ftplib.FTP, remote_dir: str) -> None:
        if not remote_dir or remote_dir == "/":
            return

        current = ""
        for part in remote_dir.strip("/").split("/"):
            current += "/" + part
            try:
                ftp.mkd(current)
            except ftplib.error_perm:
                pass
        ftp.cwd(remote_dir)

    def _after_success(self, path: Path) -> None:
        LOGGER.info("Upload succeeded for %s", path.name)
        if self.config.delete_after_upload:
            path.unlink()
        else:
            shutil.move(str(path), str(self.paths.uploaded / path.name))


def _remote_path(remote_dir: str, filename: str) -> str:
    if not remote_dir or remote_dir == ".":
        return filename
    return posixpath.join(remote_dir, filename)
