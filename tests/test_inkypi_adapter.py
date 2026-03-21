from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from PIL import Image

from app.inkypi_adapter import InkyPiAdapter
from app.models import DisplayConfig, DisplayRequest, InkyPiConfig, StorageConfig


class _FakeHttpResponse:
    def __init__(self, body: str, status: int = 200):
        self._body = body.encode("utf-8")
        self.status = status

    def __enter__(self) -> _FakeHttpResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class _FakeCompletedProcess:
    def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class InkyPiAdapterTests(unittest.TestCase):
    def test_display_writes_payload_and_switches_orientation_for_portrait(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            source_image = tmpdir_path / "prepared.png"
            Image.new("RGB", (900, 1600), (123, 111, 99)).save(source_image)

            storage_config = self._build_storage(tmpdir_path)
            display_config = self._build_display_config()
            inkypi_config = self._build_config(
                tmpdir_path,
                update_method="http_update_now",
                update_now_url="http://127.0.0.1/update_now",
                refresh_command="sudo systemctl restart inkypi.service",
            )
            self._write_device_config(tmpdir_path, orientation="horizontal")
            adapter = InkyPiAdapter(inkypi_config, storage_config, display_config)

            with patch("app.inkypi_adapter.request.urlopen", return_value=_FakeHttpResponse('{"message":"ok"}')):
                result = adapter.display(self._build_request(tmpdir_path, source_image))

            self.assertTrue(result.success)
            payload = json.loads(storage_config.current_payload_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["orientation_hint"], "vertical")
            self.assertEqual(payload["prepared_image_path"], str(storage_config.current_image_path))
            self.assertEqual(payload["caption_bar_height"], 44)
            self.assertEqual(payload["caption_character_limit"], 72)
            self.assertEqual(payload["caption_max_lines"], 1)
            self.assertEqual(payload["metadata_font_size"], 14)

            device_config = json.loads((tmpdir_path / "InkyPi" / "src" / "config" / "device.json").read_text(encoding="utf-8"))
            self.assertEqual(device_config["orientation"], "vertical")

    def test_display_sets_caption_bar_height_zero_when_show_caption_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            source_image = tmpdir_path / "prepared.png"
            Image.new("RGB", (1600, 900), (123, 111, 99)).save(source_image)

            storage_config = self._build_storage(tmpdir_path)
            display_config = self._build_display_config()
            inkypi_config = self._build_config(
                tmpdir_path,
                update_method="http_update_now",
                update_now_url="http://127.0.0.1/update_now",
                refresh_command="sudo systemctl restart inkypi.service",
            )
            self._write_device_config(tmpdir_path, orientation="horizontal")
            adapter = InkyPiAdapter(inkypi_config, storage_config, display_config)

            request = DisplayRequest(
                image_id="img-2",
                original_path=tmpdir_path / "original.jpg",
                composed_path=source_image,
                location="",
                taken_at="",
                caption="",
                created_at="2026-03-18T12:00:00+00:00",
                uploaded_by=1,
                show_caption=False,
            )
            with patch("app.inkypi_adapter.request.urlopen", return_value=_FakeHttpResponse('{"message":"ok"}')):
                result = adapter.display(request)

            self.assertTrue(result.success)
            payload = json.loads(storage_config.current_payload_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["caption_bar_height"], 0)

    def test_display_defaults_square_image_to_horizontal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            source_image = tmpdir_path / "prepared.png"
            Image.new("RGB", (800, 800), (123, 111, 99)).save(source_image)

            storage_config = self._build_storage(tmpdir_path)
            display_config = self._build_display_config()
            inkypi_config = self._build_config(
                tmpdir_path,
                update_method="http_update_now",
                update_now_url="http://127.0.0.1/update_now",
                refresh_command="sudo systemctl restart inkypi.service",
            )
            self._write_device_config(tmpdir_path, orientation="vertical")
            adapter = InkyPiAdapter(inkypi_config, storage_config, display_config)

            with patch("app.inkypi_adapter.request.urlopen", return_value=_FakeHttpResponse('{"message":"ok"}')):
                result = adapter.display(self._build_request(tmpdir_path, source_image))

            self.assertTrue(result.success)
            payload = json.loads(storage_config.current_payload_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["orientation_hint"], "horizontal")

            device_config = json.loads((tmpdir_path / "InkyPi" / "src" / "config" / "device.json").read_text(encoding="utf-8"))
            self.assertEqual(device_config["orientation"], "horizontal")

    def test_display_reports_http_json_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            source_image = tmpdir_path / "prepared.png"
            Image.new("RGB", (900, 1600), (123, 111, 99)).save(source_image)

            storage_config = self._build_storage(tmpdir_path)
            display_config = self._build_display_config()
            inkypi_config = self._build_config(
                tmpdir_path,
                update_method="http_update_now",
                update_now_url="http://127.0.0.1/update_now",
                refresh_command="sudo systemctl restart inkypi.service",
            )
            self._write_device_config(tmpdir_path, orientation="horizontal")
            adapter = InkyPiAdapter(inkypi_config, storage_config, display_config)

            http_error = HTTPError(
                url="http://127.0.0.1/update_now",
                code=500,
                msg="Internal Server Error",
                hdrs=None,
                fp=io.BytesIO(b'{"error":"Plugin not registered"}'),
            )
            with patch("app.inkypi_adapter.request.urlopen", side_effect=http_error):
                result = adapter.display(self._build_request(tmpdir_path, source_image))

            self.assertFalse(result.success)
            self.assertIn("Plugin not registered", result.message)

    def test_display_uses_command_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            source_image = tmpdir_path / "prepared.png"
            Image.new("RGB", (1600, 900), (123, 111, 99)).save(source_image)

            storage_config = self._build_storage(tmpdir_path)
            display_config = self._build_display_config()
            inkypi_config = self._build_config(
                tmpdir_path,
                update_method="command",
                update_now_url="http://127.0.0.1/update_now",
                refresh_command="python3 -c \"print('refresh ok')\"",
            )
            self._write_device_config(tmpdir_path, orientation="vertical")
            adapter = InkyPiAdapter(inkypi_config, storage_config, display_config)

            result = adapter.display(self._build_request(tmpdir_path, source_image))

            self.assertTrue(result.success)
            self.assertIn("refresh ok", result.message)
            device_config = json.loads((tmpdir_path / "InkyPi" / "src" / "config" / "device.json").read_text(encoding="utf-8"))
            self.assertEqual(device_config["orientation"], "horizontal")

    def test_apply_device_settings_saves_reloads_and_refreshes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            storage_config = self._build_storage(tmpdir_path)
            display_config = self._build_display_config()
            inkypi_config = self._build_config(
                tmpdir_path,
                update_method="http_update_now",
                update_now_url="http://127.0.0.1/update_now",
                refresh_command="sudo systemctl restart inkypi.service",
            )
            self._write_device_config(
                tmpdir_path,
                orientation="horizontal",
                image_settings={"saturation": 1.4, "contrast": 1.4},
            )
            storage_config.current_payload_path.parent.mkdir(parents=True, exist_ok=True)
            storage_config.current_payload_path.write_text(
                json.dumps({"orientation_hint": "horizontal"}),
                encoding="utf-8",
            )
            adapter = InkyPiAdapter(inkypi_config, storage_config, display_config)

            with patch(
                "app.inkypi_adapter.subprocess.run",
                side_effect=[
                    _FakeCompletedProcess(returncode=0),
                    _FakeCompletedProcess(returncode=0, stdout="active\n"),
                ],
            ), patch("app.inkypi_adapter.request.urlopen", return_value=_FakeHttpResponse('{"message":"ok"}')):
                result = adapter.apply_device_settings({"image_settings": {"saturation": 1.8}})

            self.assertTrue(result.success)
            self.assertTrue(result.saved)
            self.assertTrue(result.reloaded)
            self.assertTrue(result.refreshed)
            self.assertEqual(result.confirmed_settings["image_settings"]["saturation"], 1.8)
            device_config = json.loads((tmpdir_path / "InkyPi" / "src" / "config" / "device.json").read_text(encoding="utf-8"))
            self.assertEqual(device_config["image_settings"]["saturation"], 1.8)
            self.assertEqual(device_config["image_settings"]["contrast"], 1.4)

    def test_apply_device_settings_skips_refresh_without_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            storage_config = self._build_storage(tmpdir_path)
            display_config = self._build_display_config()
            inkypi_config = self._build_config(
                tmpdir_path,
                update_method="http_update_now",
                update_now_url="http://127.0.0.1/update_now",
                refresh_command="sudo systemctl restart inkypi.service",
            )
            self._write_device_config(
                tmpdir_path,
                orientation="horizontal",
                image_settings={"saturation": 1.4},
            )
            adapter = InkyPiAdapter(inkypi_config, storage_config, display_config)

            with patch(
                "app.inkypi_adapter.subprocess.run",
                side_effect=[
                    _FakeCompletedProcess(returncode=0),
                    _FakeCompletedProcess(returncode=0, stdout="active\n"),
                ],
            ):
                result = adapter.apply_device_settings({"image_settings": {"saturation": 1.9}})

            self.assertTrue(result.success)
            self.assertTrue(result.saved)
            self.assertTrue(result.reloaded)
            self.assertFalse(result.refreshed)
            self.assertTrue(result.refresh_skipped)
            self.assertIn("kein aktuelles Bild", result.message)

    def test_apply_device_settings_reports_restart_failure_but_keeps_saved_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            storage_config = self._build_storage(tmpdir_path)
            display_config = self._build_display_config()
            inkypi_config = self._build_config(
                tmpdir_path,
                update_method="http_update_now",
                update_now_url="http://127.0.0.1/update_now",
                refresh_command="sudo systemctl restart inkypi.service",
            )
            self._write_device_config(
                tmpdir_path,
                orientation="horizontal",
                image_settings={"saturation": 1.4},
            )
            adapter = InkyPiAdapter(inkypi_config, storage_config, display_config)

            with patch(
                "app.inkypi_adapter.subprocess.run",
                return_value=_FakeCompletedProcess(returncode=1, stderr="permission denied"),
            ):
                result = adapter.apply_device_settings({"image_settings": {"saturation": 2.0}})

            self.assertFalse(result.success)
            self.assertTrue(result.saved)
            self.assertFalse(result.reloaded)
            self.assertIn("permission denied", result.message)
            device_config = json.loads((tmpdir_path / "InkyPi" / "src" / "config" / "device.json").read_text(encoding="utf-8"))
            self.assertEqual(device_config["image_settings"]["saturation"], 2.0)

    def test_refresh_only_preserves_existing_image_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            storage_config = self._build_storage(tmpdir_path)
            display_config = self._build_display_config()
            inkypi_config = self._build_config(
                tmpdir_path,
                update_method="http_update_now",
                update_now_url="http://127.0.0.1/update_now",
                refresh_command="sudo systemctl restart inkypi.service",
            )
            self._write_device_config(
                tmpdir_path,
                orientation="vertical",
                image_settings={"saturation": 1.7, "contrast": 1.3},
            )
            storage_config.current_payload_path.parent.mkdir(parents=True, exist_ok=True)
            storage_config.current_payload_path.write_text(
                json.dumps({"orientation_hint": "horizontal"}),
                encoding="utf-8",
            )
            adapter = InkyPiAdapter(inkypi_config, storage_config, display_config)

            with patch("app.inkypi_adapter.request.urlopen", return_value=_FakeHttpResponse('{"message":"ok"}')):
                result = adapter.refresh_only()

            self.assertTrue(result.success)
            device_config = json.loads((tmpdir_path / "InkyPi" / "src" / "config" / "device.json").read_text(encoding="utf-8"))
            self.assertEqual(device_config["orientation"], "horizontal")
            self.assertEqual(device_config["image_settings"]["saturation"], 1.7)
            self.assertEqual(device_config["image_settings"]["contrast"], 1.3)

    @staticmethod
    def _build_storage(tmpdir_path: Path) -> StorageConfig:
        return StorageConfig(
            incoming_dir=tmpdir_path / "incoming",
            rendered_dir=tmpdir_path / "rendered",
            cache_dir=tmpdir_path / "cache",
            archive_dir=tmpdir_path / "archive",
            inkypi_payload_dir=tmpdir_path / "inkypi",
            current_payload_path=tmpdir_path / "inkypi" / "current.json",
            current_image_path=tmpdir_path / "inkypi" / "current.png",
            keep_recent_rendered=5,
        )

    @staticmethod
    def _build_display_config() -> DisplayConfig:
        return DisplayConfig(
            width=800,
            height=480,
            caption_height=44,
            margin=18,
            metadata_font_size=14,
            caption_font_size=20,
            caption_character_limit=72,
            max_caption_lines=1,
            font_path="/tmp/does-not-exist.ttf",
            background_color="#F7F3EA",
            text_color="#111111",
            divider_color="#3A3A3A",
        )

    @staticmethod
    def _build_config(
        tmpdir_path: Path,
        *,
        update_method: str,
        update_now_url: str,
        refresh_command: str,
    ) -> InkyPiConfig:
        return InkyPiConfig(
            repo_path=tmpdir_path / "InkyPi",
            install_path=tmpdir_path / "usr" / "local" / "inkypi",
            validated_commit="main",
            waveshare_model="epd7in3e",
            plugin_id="telegram_frame",
            payload_dir=tmpdir_path / "inkypi",
            update_method=update_method,
            update_now_url=update_now_url,
            refresh_command=refresh_command,
        )

    @staticmethod
    def _build_request(tmpdir_path: Path, source_image: Path) -> DisplayRequest:
        return DisplayRequest(
            image_id="img-1",
            original_path=tmpdir_path / "original.jpg",
            composed_path=source_image,
            location="Berlin",
            taken_at="2026-03-18",
            caption="Caption",
            created_at="2026-03-18T12:00:00+00:00",
            uploaded_by=1,
        )

    @staticmethod
    def _write_device_config(
        tmpdir_path: Path,
        *,
        orientation: str,
        image_settings: dict[str, float] | None = None,
    ) -> None:
        device_config_path = tmpdir_path / "InkyPi" / "src" / "config" / "device.json"
        device_config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"orientation": orientation}
        if image_settings is not None:
            payload["image_settings"] = image_settings
        device_config_path.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
