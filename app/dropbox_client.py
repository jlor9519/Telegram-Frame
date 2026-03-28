from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

from app.models import DropboxConfig

try:
    import dropbox
    from dropbox.files import WriteMode
except ImportError:  # pragma: no cover - exercised when dependencies are not installed locally
    dropbox = None
    WriteMode = None


class DropboxService:
    def __init__(self, config: DropboxConfig):
        self.config = config
        self._client = None
        self._last_error: str | None = None
        self._folders_ready = False
        if self.config.enabled and dropbox is not None:
            if self.config.refresh_token and self.config.app_key and self.config.app_secret:
                self._client = dropbox.Dropbox(
                    oauth2_refresh_token=self.config.refresh_token,
                    app_key=self.config.app_key,
                    app_secret=self.config.app_secret,
                )
            elif self.config.access_token:
                self._client = dropbox.Dropbox(self.config.access_token)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def health_summary(self) -> str:
        if not self.config.enabled:
            return "disabled"
        if self._client is None:
            return "not_configured"
        if self.check_connection():
            return "connected"
        return "auth_failed"

    def upload_original(self, local_path: Path) -> str | None:
        return self._upload(local_path, "images/originals")

    def upload_rendered(self, local_path: Path) -> str | None:
        if not self.config.upload_rendered:
            return None
        return self._upload(local_path, "images/rendered")

    def backup_database(self, db_path: Path) -> str | None:
        """Upload the SQLite database file to Dropbox as a backup."""
        return self._upload(db_path, "backup")

    def restore_database(self, db_path: Path) -> bool:
        """Download the database backup from Dropbox. Returns True if restored."""
        remote_path = f"{self.config.root_path}/backup/{db_path.name}".replace("//", "/")
        return self.download_file(remote_path, db_path)

    def download_file(self, remote_path: str, local_path: Path) -> bool:
        """Download a file from Dropbox to local_path. Returns True on success."""
        if self._client is None:
            self._set_error("Dropbox client is not configured.")
            return False
        logger.info("Downloading from Dropbox %s to %s", remote_path, local_path)
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            _, response = self._client.files_download(remote_path)
            with tempfile.NamedTemporaryFile(dir=local_path.parent, delete=False) as tmp:
                tmp.write(response.content)
            tmp_path = Path(tmp.name)
            tmp_path.replace(local_path)
            logger.info("Dropbox download complete: %s", local_path)
            self._clear_error()
            return True
        except Exception as exc:
            self._set_error(f"Dropbox download failed for {remote_path}: {exc}")
            logger.warning(self._last_error)
            return False

    def remote_file_exists(self, remote_path: str) -> bool:
        """Check whether a file exists on Dropbox."""
        if self._client is None:
            return False
        try:
            self._client.files_get_metadata(remote_path)
            return True
        except Exception:
            return False

    def delete_file(self, remote_path: str) -> bool:
        """Permanently delete a file from Dropbox. Returns True on success."""
        if self._client is None:
            self._set_error("Dropbox client is not configured.")
            return False
        try:
            self._client.files_delete_v2(remote_path)
            logger.info("Dropbox delete complete: %s", remote_path)
            self._clear_error()
            return True
        except Exception as exc:
            self._set_error(f"Dropbox delete failed for {remote_path}: {exc}")
            logger.warning(self._last_error)
            return False

    def upload_display_payload(self, payload_path: Path, image_path: Path) -> bool:
        """Upload current.json + current.png to the display sync folder on Dropbox."""
        if self._client is None:
            self._set_error("Dropbox client is not configured.")
            return False
        try:
            self._upload(image_path, "display")
            self._upload(payload_path, "display")
            logger.info("Display payload uploaded to Dropbox")
            self._clear_error()
            return True
        except Exception as exc:
            if self._last_error is None:
                self._set_error(f"Failed to upload display payload: {exc}")
            logger.warning(self._last_error)
            return False

    def get_display_payload_revision(self) -> str | None:
        """Fetch the revision field from the remote display payload. Returns None if unavailable."""
        if self._client is None:
            return None
        remote_path = f"{self.config.root_path}/display/current.json".replace("//", "/")
        try:
            _, response = self._client.files_download(remote_path)
            payload = json.loads(response.content)
            return str(payload.get("revision", ""))
        except Exception:
            return None

    def check_connection(self) -> bool:
        """Live-ping Dropbox auth without assuming the remote root folder already exists."""
        if self._client is None:
            self._set_error("Dropbox client is not configured.")
            return False
        try:
            self._client.users_get_current_account()
            self._clear_error()
            return True
        except Exception as exc:
            self._set_error(f"Dropbox authentication failed: {exc}")
            return False

    def _upload(self, local_path: Path, remote_folder: str) -> str | None:
        if self._client is None:
            return None
        if not self.ensure_required_folders():
            raise RuntimeError(self._last_error or "Dropbox folder bootstrap failed.")
        remote_path = f"{self.config.root_path}/{remote_folder}/{local_path.name}".replace("//", "/")
        logger.info("Uploading %s to Dropbox %s", local_path.name, remote_path)
        try:
            with local_path.open("rb") as handle:
                self._client.files_upload(
                    handle.read(),
                    remote_path,
                    mode=WriteMode.overwrite,
                    mute=True,
                )
        except Exception as exc:
            self._set_error(f"Dropbox upload failed for {remote_path}: {exc}")
            raise
        logger.info("Dropbox upload complete: %s", remote_path)
        self._clear_error()
        return remote_path

    def ensure_required_folders(self) -> bool:
        if self._client is None:
            self._set_error("Dropbox client is not configured.")
            return False
        if self._folders_ready:
            return True
        try:
            for folder_path in self._required_folder_paths():
                if not self._ensure_folder(folder_path):
                    return False
        except Exception as exc:
            self._set_error(f"Dropbox folder bootstrap failed: {exc}")
            return False
        self._folders_ready = True
        self._clear_error()
        return True

    def _required_folder_paths(self) -> list[str]:
        folders = [
            self.config.root_path,
            f"{self.config.root_path}/images",
            f"{self.config.root_path}/images/originals",
            f"{self.config.root_path}/display",
            f"{self.config.root_path}/backup",
        ]
        if self.config.upload_rendered:
            folders.append(f"{self.config.root_path}/images/rendered")
        return [folder.replace("//", "/") for folder in folders]

    def _ensure_folder(self, folder_path: str) -> bool:
        if self._remote_path_exists(folder_path):
            return True
        try:
            self._client.files_create_folder_v2(folder_path)
            logger.info("Created Dropbox folder %s", folder_path)
            return True
        except Exception as exc:
            if self._remote_path_exists(folder_path):
                return True
            self._set_error(f"Dropbox folder creation failed for {folder_path}: {exc}")
            logger.warning(self._last_error)
            return False

    def _remote_path_exists(self, remote_path: str) -> bool:
        if self._client is None:
            return False
        try:
            self._client.files_get_metadata(remote_path)
            return True
        except Exception:
            return False

    def _set_error(self, message: str) -> None:
        self._last_error = message

    def _clear_error(self) -> None:
        self._last_error = None
