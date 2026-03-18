from __future__ import annotations

from pathlib import Path

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
        if self.config.enabled and self.config.access_token and dropbox is not None:
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

    def _upload(self, local_path: Path, remote_folder: str) -> str | None:
        if self._client is None:
            return None
        remote_path = f"{self.config.root_path}/{remote_folder}/{local_path.name}".replace("//", "/")
        with local_path.open("rb") as handle:
            self._client.files_upload(
                handle.read(),
                remote_path,
                mode=WriteMode.overwrite,
                mute=True,
            )
        return remote_path

