from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.dropbox_client import DropboxService
from app.models import DropboxConfig


class DropboxServiceTests(unittest.TestCase):
    def test_refresh_token_client_uses_app_secret(self) -> None:
        client = _FakeDropboxClient()
        factory = _DropboxFactory(client)
        config = DropboxConfig(
            enabled=True,
            access_token=None,
            app_key="app-key",
            app_secret="app-secret",
            refresh_token="refresh-token",
            root_path="/photo-frame",
            upload_rendered=True,
        )

        with patch("app.dropbox_client.dropbox", SimpleNamespace(Dropbox=factory)), patch(
            "app.dropbox_client.WriteMode",
            SimpleNamespace(overwrite="overwrite"),
        ):
            DropboxService(config)

        self.assertEqual(len(factory.calls), 1)
        _, kwargs = factory.calls[0]
        self.assertEqual(kwargs["oauth2_refresh_token"], "refresh-token")
        self.assertEqual(kwargs["app_key"], "app-key")
        self.assertEqual(kwargs["app_secret"], "app-secret")

    def test_health_summary_is_connected_before_root_folder_exists(self) -> None:
        client = _FakeDropboxClient()
        service = self._build_service(client, upload_rendered=True)

        status = service.health_summary()

        self.assertEqual(status, "connected")
        self.assertEqual(client.account_checks, 1)
        self.assertEqual(client.created_folders, [])

    def test_upload_original_bootstraps_remote_folder_layout(self) -> None:
        client = _FakeDropboxClient()
        service = self._build_service(client, upload_rendered=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = Path(tmpdir) / "photo.jpg"
            local_path.write_bytes(b"image-bytes")

            remote_path = service.upload_original(local_path)

        self.assertEqual(remote_path, "/photo-frame/images/originals/photo.jpg")
        self.assertEqual(
            client.created_folders,
            [
                "/photo-frame",
                "/photo-frame/images",
                "/photo-frame/images/originals",
                "/photo-frame/display",
                "/photo-frame/backup",
                "/photo-frame/images/rendered",
            ],
        )
        self.assertEqual(client.uploads, ["/photo-frame/images/originals/photo.jpg"])

    def _build_service(self, client: "_FakeDropboxClient", *, upload_rendered: bool) -> DropboxService:
        factory = _DropboxFactory(client)
        config = DropboxConfig(
            enabled=True,
            access_token=None,
            app_key="app-key",
            app_secret="app-secret",
            refresh_token="refresh-token",
            root_path="/photo-frame",
            upload_rendered=upload_rendered,
        )

        patcher_dropbox = patch("app.dropbox_client.dropbox", SimpleNamespace(Dropbox=factory))
        patcher_write_mode = patch("app.dropbox_client.WriteMode", SimpleNamespace(overwrite="overwrite"))
        self.addCleanup(patcher_dropbox.stop)
        self.addCleanup(patcher_write_mode.stop)
        patcher_dropbox.start()
        patcher_write_mode.start()
        return DropboxService(config)


class _DropboxFactory:
    def __init__(self, client: "_FakeDropboxClient") -> None:
        self.client = client
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __call__(self, *args: object, **kwargs: object) -> "_FakeDropboxClient":
        self.calls.append((args, kwargs))
        return self.client


class _FakeDropboxClient:
    def __init__(self) -> None:
        self.account_checks = 0
        self.existing_paths: set[str] = set()
        self.created_folders: list[str] = []
        self.uploads: list[str] = []

    def users_get_current_account(self) -> object:
        self.account_checks += 1
        return object()

    def files_get_metadata(self, path: str) -> object:
        if path in self.existing_paths:
            return object()
        raise Exception(f"not found: {path}")

    def files_create_folder_v2(self, path: str) -> object:
        self.created_folders.append(path)
        self.existing_paths.add(path)
        return object()

    def files_upload(self, data: bytes, path: str, *, mode: object, mute: bool) -> object:
        parent = path.rsplit("/", 1)[0]
        if parent not in self.existing_paths:
            raise Exception(f"parent folder missing: {parent}")
        self.uploads.append(path)
        self.existing_paths.add(path)
        return object()


if __name__ == "__main__":
    unittest.main()
