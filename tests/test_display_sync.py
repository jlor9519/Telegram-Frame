from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DISPLAY_SYNC_PATH = PROJECT_ROOT / "scripts" / "display_sync.py"
HAS_DISPLAY_SYNC_DEPS = all(find_spec(name) is not None for name in ("dropbox", "yaml", "dotenv"))


@unittest.skipUnless(HAS_DISPLAY_SYNC_DEPS, "display_sync dependencies are not installed")
class DisplaySyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("display_sync_under_test", DISPLAY_SYNC_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.display_sync = module

    def test_failed_update_is_retried_until_revision_is_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            revision = "rev-123"
            payload_bytes = json.dumps({"image_id": "img-1", "revision": revision}).encode("utf-8")
            png_bytes = b"png-data"
            client = _FakeDropboxClient(
                {
                    "/photo-frame/display/current.json": payload_bytes,
                    "/photo-frame/display/current.png": png_bytes,
                }
            )
            config = {
                "dropbox_token": "token",
                "dropbox_refresh_token": None,
                "dropbox_app_key": None,
                "dropbox_app_secret": None,
                "root_path": "/photo-frame",
                "payload_dir": tmpdir_path,
                "update_now_url": "http://127.0.0.1/update_now",
                "plugin_id": "telegram_frame",
            }

            with patch.object(self.display_sync.dropbox, "Dropbox", return_value=client), patch.object(
                self.display_sync,
                "trigger_update",
                side_effect=[False, True],
            ) as trigger_update:
                first = self.display_sync.sync_once(config)
                second = self.display_sync.sync_once(config)

            self.assertFalse(first)
            self.assertTrue(second)
            self.assertEqual(trigger_update.call_count, 2)
            applied_revision = self.display_sync.get_applied_revision(tmpdir_path)
            self.assertEqual(applied_revision, revision)
            local_payload = json.loads((tmpdir_path / "current.json").read_text(encoding="utf-8"))
            self.assertEqual(local_payload["revision"], revision)
            self.assertTrue((tmpdir_path / "current.png").exists())

    def test_load_sync_config_reads_dropbox_app_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            config_path = tmpdir_path / "config.yaml"
            env_path = tmpdir_path / ".env"
            config_path.write_text(
                "\n".join(
                    [
                        "dropbox:",
                        "  enabled: true",
                        "  app_key: test-app-key",
                        "  refresh_token_env: TEST_DROPBOX_REFRESH_TOKEN",
                        "  app_secret_env: TEST_DROPBOX_APP_SECRET",
                        "storage:",
                        "  inkypi_payload_dir: data/inkypi",
                        "inkypi:",
                        "  update_now_url: http://127.0.0.1/update_now",
                    ]
                ),
                encoding="utf-8",
            )
            env_path.write_text(
                "TEST_DROPBOX_REFRESH_TOKEN=refresh-token\nTEST_DROPBOX_APP_SECRET=app-secret\n",
                encoding="utf-8",
            )

            old_env = os.environ.get("PHOTO_FRAME_ENV_FILE")
            os.environ["PHOTO_FRAME_ENV_FILE"] = str(env_path)
            try:
                loaded = self.display_sync.load_sync_config(config_path)
            finally:
                if old_env is None:
                    os.environ.pop("PHOTO_FRAME_ENV_FILE", None)
                else:
                    os.environ["PHOTO_FRAME_ENV_FILE"] = old_env

            self.assertEqual(loaded["dropbox_refresh_token"], "refresh-token")
            self.assertEqual(loaded["dropbox_app_key"], "test-app-key")
            self.assertEqual(loaded["dropbox_app_secret"], "app-secret")

    def test_sync_once_passes_app_secret_for_refresh_token_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            factory = _DropboxFactory(
                _FakeDropboxClient(
                    {
                        "/photo-frame/display/current.json": json.dumps({"revision": ""}).encode("utf-8"),
                        "/photo-frame/display/current.png": b"png-data",
                    }
                )
            )
            config = {
                "dropbox_token": None,
                "dropbox_refresh_token": "refresh-token",
                "dropbox_app_key": "app-key",
                "dropbox_app_secret": "app-secret",
                "root_path": "/photo-frame",
                "payload_dir": tmpdir_path,
                "update_now_url": "http://127.0.0.1/update_now",
                "plugin_id": "telegram_frame",
            }

            with patch.object(self.display_sync.dropbox, "Dropbox", side_effect=factory), patch.object(
                self.display_sync,
                "download_and_patch",
                return_value=None,
            ):
                result = self.display_sync.sync_once(config)

            self.assertFalse(result)
            self.assertEqual(len(factory.calls), 1)
            _, kwargs = factory.calls[0]
            self.assertEqual(kwargs["oauth2_refresh_token"], "refresh-token")
            self.assertEqual(kwargs["app_key"], "app-key")
            self.assertEqual(kwargs["app_secret"], "app-secret")


class _FakeDropboxClient:
    def __init__(self, responses: dict[str, bytes]) -> None:
        self.responses = responses

    def files_download(self, path: str):
        return None, SimpleNamespace(content=self.responses[path])


class _DropboxFactory:
    def __init__(self, client: _FakeDropboxClient) -> None:
        self.client = client
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __call__(self, *args: object, **kwargs: object) -> _FakeDropboxClient:
        self.calls.append((args, kwargs))
        return self.client


if __name__ == "__main__":
    unittest.main()
