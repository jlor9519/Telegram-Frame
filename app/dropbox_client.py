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
        if self.config.enabled and dropbox is not None:
            if self.config.refresh_token and self.config.app_key:
                self._client = dropbox.Dropbox(
                    oauth2_refresh_token=self.config.refresh_token,
                    app_key=self.config.app_key,
                )
            elif self.config.access_token:
                self._client = dropbox.Dropbox(self.config.access_token)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def health_summary(self) -> str:
        if not self.config.enabled:
            return "disabled"
        if self._client is None:
            return "enabled but not ready"
        return "configured"

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
            return True
        except Exception as exc:
            logger.warning("Dropbox download failed for %s: %s", remote_path, exc)
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
            return False
        try:
            self._client.files_delete_v2(remote_path)
            logger.info("Dropbox delete complete: %s", remote_path)
            return True
        except Exception as exc:
            logger.warning("Dropbox delete failed for %s: %s", remote_path, exc)
            return False

    def upload_display_payload(self, payload_path: Path, image_path: Path) -> bool:
        """Upload current.json + current.png to the display sync folder on Dropbox."""
        if self._client is None:
            return False
        try:
            self._upload(image_path, "display")
            self._upload(payload_path, "display")
            logger.info("Display payload uploaded to Dropbox")
            return True
        except Exception as exc:
            logger.warning("Failed to upload display payload: %s", exc)
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
        """Live-ping Dropbox by fetching root folder metadata. Returns False if unreachable."""
        if self._client is None:
            return False
        try:
            self._client.files_get_metadata(self.config.root_path)
            return True
        except Exception:
            return False

    def _upload(self, local_path: Path, remote_folder: str) -> str | None:
        if self._client is None:
            return None
        remote_path = f"{self.config.root_path}/{remote_folder}/{local_path.name}".replace("//", "/")
        logger.info("Uploading %s to Dropbox %s", local_path.name, remote_path)
        with local_path.open("rb") as handle:
            self._client.files_upload(
                handle.read(),
                remote_path,
                mode=WriteMode.overwrite,
                mute=True,
            )
        logger.info("Dropbox upload complete: %s", remote_path)
        return remote_path

