from __future__ import annotations

import os
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path


class ConfigTests(unittest.TestCase):
    def test_load_config_merges_env_and_yaml(self) -> None:
        if find_spec("yaml") is None or find_spec("dotenv") is None:
            self.skipTest("PyYAML and python-dotenv are required for config tests.")

        import yaml

        from app.config import load_config

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "telegram": {"bot_token_env": "TEST_TELEGRAM_BOT_TOKEN"},
                        "security": {"admin_user_ids": [123], "whitelisted_user_ids": [456]},
                        "database": {"path": "data/db/test.db"},
                        "storage": {
                            "incoming_dir": "data/incoming",
                            "rendered_dir": "data/rendered",
                            "cache_dir": "data/cache",
                            "archive_dir": "data/archive",
                            "inkypi_payload_dir": "data/inkypi",
                            "current_payload_path": "data/inkypi/current.json",
                            "current_image_path": "data/inkypi/current.png",
                            "keep_recent_rendered": 3,
                        },
                        "dropbox": {
                            "enabled": False,
                            "access_token_env": "TEST_DROPBOX_ACCESS_TOKEN",
                            "root_path": "/photo-frame",
                            "upload_rendered": True,
                        },
                        "display": {
                            "width": 800,
                            "height": 480,
                            "caption_height": 120,
                            "margin": 12,
                            "metadata_font_size": 20,
                            "caption_font_size": 26,
                            "max_caption_lines": 2,
                            "font_path": "/tmp/does-not-exist.ttf",
                            "background_color": "#FFFFFF",
                            "text_color": "#000000",
                            "divider_color": "#333333",
                        },
                        "inkypi": {
                            "repo_path": "~/InkyPi",
                            "install_path": "/usr/local/inkypi",
                            "validated_commit": "main",
                            "waveshare_model": "epd7in3e",
                            "plugin_id": "telegram_frame",
                            "payload_dir": "data/inkypi",
                            "refresh_command": "echo refresh",
                        },
                    }
                ),
                encoding="utf-8",
            )

            os.environ["TEST_TELEGRAM_BOT_TOKEN"] = "token-123"
            os.environ["TEST_DROPBOX_ACCESS_TOKEN"] = "dropbox-123"
            try:
                config = load_config(config_path)
            finally:
                os.environ.pop("TEST_TELEGRAM_BOT_TOKEN", None)
                os.environ.pop("TEST_DROPBOX_ACCESS_TOKEN", None)

            self.assertEqual(config.telegram.bot_token, "token-123")
            self.assertEqual(config.security.admin_user_ids, [123])
            self.assertEqual(config.security.whitelisted_user_ids, [456])
            self.assertTrue(str(config.database.path).endswith("data/db/test.db"))
            self.assertEqual(config.inkypi.repo_path, Path.home() / "InkyPi")
            self.assertEqual(config.inkypi.install_path, Path("/usr/local/inkypi"))
            self.assertEqual(config.inkypi.waveshare_model, "epd7in3e")

    def test_missing_telegram_token_raises_error(self) -> None:
        if find_spec("yaml") is None or find_spec("dotenv") is None:
            self.skipTest("PyYAML and python-dotenv are required for config tests.")

        import yaml

        from app.config import ConfigError, load_config

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "telegram": {"bot_token_env": "MISSING_TOKEN"},
                        "security": {},
                        "database": {"path": "data/db/test.db"},
                        "storage": {
                            "incoming_dir": "data/incoming",
                            "rendered_dir": "data/rendered",
                            "cache_dir": "data/cache",
                            "archive_dir": "data/archive",
                            "inkypi_payload_dir": "data/inkypi",
                            "current_payload_path": "data/inkypi/current.json",
                            "current_image_path": "data/inkypi/current.png",
                            "keep_recent_rendered": 3,
                        },
                        "dropbox": {"enabled": False},
                        "display": {
                            "width": 800,
                            "height": 480,
                            "caption_height": 120,
                            "margin": 12,
                            "metadata_font_size": 20,
                            "caption_font_size": 26,
                            "max_caption_lines": 2,
                            "font_path": "/tmp/does-not-exist.ttf",
                            "background_color": "#FFFFFF",
                            "text_color": "#000000",
                            "divider_color": "#333333",
                        },
                        "inkypi": {
                            "repo_path": "~/InkyPi",
                            "install_path": "/usr/local/inkypi",
                            "validated_commit": "main",
                            "waveshare_model": "epd7in3e",
                            "plugin_id": "telegram_frame",
                            "payload_dir": "data/inkypi",
                            "refresh_command": "echo refresh",
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                load_config(config_path)

    def test_load_config_uses_env_override_paths(self) -> None:
        if find_spec("yaml") is None or find_spec("dotenv") is None:
            self.skipTest("PyYAML and python-dotenv are required for config tests.")

        import yaml

        from app.config import load_config

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            config_path = tmpdir_path / "mock-config.yaml"
            env_path = tmpdir_path / "mock.env"
            env_path.write_text("OVERRIDE_TELEGRAM_TOKEN=token-from-env\n", encoding="utf-8")
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "telegram": {"bot_token_env": "OVERRIDE_TELEGRAM_TOKEN"},
                        "security": {},
                        "database": {"path": "data/db/test.db"},
                        "storage": {
                            "incoming_dir": "data/incoming",
                            "rendered_dir": "data/rendered",
                            "cache_dir": "data/cache",
                            "archive_dir": "data/archive",
                            "inkypi_payload_dir": "data/inkypi",
                            "current_payload_path": "data/inkypi/current.json",
                            "current_image_path": "data/inkypi/current.png",
                            "keep_recent_rendered": 3,
                        },
                        "dropbox": {"enabled": False},
                        "display": {
                            "width": 800,
                            "height": 480,
                            "caption_height": 120,
                            "margin": 12,
                            "metadata_font_size": 20,
                            "caption_font_size": 26,
                            "max_caption_lines": 2,
                            "font_path": "/tmp/does-not-exist.ttf",
                            "background_color": "#FFFFFF",
                            "text_color": "#000000",
                            "divider_color": "#333333",
                        },
                        "inkypi": {
                            "repo_path": "~/InkyPi",
                            "install_path": "/usr/local/inkypi",
                            "validated_commit": "main",
                            "waveshare_model": "epd7in3e",
                            "plugin_id": "telegram_frame",
                            "payload_dir": "data/inkypi",
                            "refresh_command": "echo refresh",
                        },
                    }
                ),
                encoding="utf-8",
            )

            old_config = os.environ.get("PHOTO_FRAME_CONFIG")
            old_env = os.environ.get("PHOTO_FRAME_ENV_FILE")
            os.environ["PHOTO_FRAME_CONFIG"] = str(config_path)
            os.environ["PHOTO_FRAME_ENV_FILE"] = str(env_path)
            try:
                config = load_config()
            finally:
                if old_config is None:
                    os.environ.pop("PHOTO_FRAME_CONFIG", None)
                else:
                    os.environ["PHOTO_FRAME_CONFIG"] = old_config
                if old_env is None:
                    os.environ.pop("PHOTO_FRAME_ENV_FILE", None)
                else:
                    os.environ["PHOTO_FRAME_ENV_FILE"] = old_env

            self.assertEqual(config.telegram.bot_token, "token-from-env")


if __name__ == "__main__":
    unittest.main()
