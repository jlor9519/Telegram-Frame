from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from app.inkypi_setup import (
    DEFAULT_PLUGIN_INSTANCE_NAME,
    seed_dashboard_plugin_instance,
    verify_plugin_module_import,
    verify_seeded_plugin_instance,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class InkyPiSetupTests(unittest.TestCase):
    def test_seed_dashboard_plugin_creates_default_playlist_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            device_path = Path(tmpdir) / "device.json"

            result = seed_dashboard_plugin_instance(device_path, "telegram_frame", "/tmp/current.json")

            self.assertTrue(result.applied)
            verify_seeded_plugin_instance(device_path, "telegram_frame", "/tmp/current.json")
            data = json.loads(device_path.read_text(encoding="utf-8"))
            self.assertIn("playlist_config", data)

    def test_seed_dashboard_plugin_seeds_empty_default_playlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            device_path = Path(tmpdir) / "device.json"
            device_path.write_text(
                json.dumps(
                    {
                        "playlists": {"Default": ["telegram_frame"]},
                        "telegram_frame": {"payload_path": "/tmp/old.json"},
                        "playlist_config": {
                            "playlists": [
                                {
                                    "name": "Default",
                                    "start_time": "00:00",
                                    "end_time": "24:00",
                                    "plugins": [],
                                    "current_plugin_index": None,
                                }
                            ],
                            "active_playlist": None,
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = seed_dashboard_plugin_instance(device_path, "telegram_frame", "/tmp/current.json")

            self.assertTrue(result.applied)
            verify_seeded_plugin_instance(device_path, "telegram_frame", "/tmp/current.json")
            data = json.loads(device_path.read_text(encoding="utf-8"))
            self.assertNotIn("playlists", data)
            self.assertNotIn("telegram_frame", data)

    def test_seed_dashboard_plugin_skips_existing_nonempty_playlists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            device_path = Path(tmpdir) / "device.json"
            original = {
                "playlist_config": {
                    "playlists": [
                        {
                            "name": "Default",
                            "start_time": "00:00",
                            "end_time": "24:00",
                            "plugins": [
                                {
                                    "plugin_id": "weather",
                                    "name": "Weather",
                                    "plugin_settings": {},
                                    "refresh": {"interval": 600},
                                    "latest_refresh_time": None,
                                }
                            ],
                            "current_plugin_index": None,
                        }
                    ],
                    "active_playlist": None,
                }
            }
            device_path.write_text(json.dumps(original), encoding="utf-8")

            result = seed_dashboard_plugin_instance(device_path, "telegram_frame", "/tmp/current.json")

            self.assertFalse(result.applied)
            data = json.loads(device_path.read_text(encoding="utf-8"))
            self.assertEqual(data, original)

    def test_verify_plugin_module_import_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            source_root = tmpdir_path / "src"
            plugin_root = source_root / "plugins"
            base_plugin_dir = plugin_root / "base_plugin"
            telegram_plugin_dir = plugin_root / "telegram_frame"

            base_plugin_dir.mkdir(parents=True)
            telegram_plugin_dir.parent.mkdir(parents=True, exist_ok=True)
            (plugin_root / "__init__.py").write_text("", encoding="utf-8")
            (base_plugin_dir / "__init__.py").write_text("", encoding="utf-8")
            (base_plugin_dir / "base_plugin.py").write_text(
                "class BasePlugin:\n    def __init__(self, config=None, **dependencies):\n        self.config = config or {}\n",
                encoding="utf-8",
            )
            shutil.copytree(PROJECT_ROOT / "integrations" / "inkypi_plugin" / "telegram_frame", telegram_plugin_dir)

            verify_plugin_module_import(source_root, "telegram_frame", "TelegramFrame")

            plugin_module = __import__("plugins.telegram_frame.telegram_frame", fromlist=["TelegramFrame"])
            plugin_class = getattr(plugin_module, "TelegramFrame")
            self.assertEqual(plugin_class.__name__, "TelegramFrame")
            self.assertEqual(DEFAULT_PLUGIN_INSTANCE_NAME, "Telegram Frame")


if __name__ == "__main__":
    unittest.main()
