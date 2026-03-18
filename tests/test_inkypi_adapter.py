from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.inkypi_adapter import InkyPiAdapter
from app.models import DisplayRequest, InkyPiConfig, StorageConfig


class InkyPiAdapterTests(unittest.TestCase):
    def test_display_writes_bridge_payload_and_current_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            source_image = tmpdir_path / "rendered.png"
            Image.new("RGB", (800, 480), (123, 111, 99)).save(source_image)

            storage_config = StorageConfig(
                incoming_dir=tmpdir_path / "incoming",
                rendered_dir=tmpdir_path / "rendered",
                cache_dir=tmpdir_path / "cache",
                archive_dir=tmpdir_path / "archive",
                inkypi_payload_dir=tmpdir_path / "inkypi",
                current_payload_path=tmpdir_path / "inkypi" / "current.json",
                current_image_path=tmpdir_path / "inkypi" / "current.png",
                keep_recent_rendered=5,
            )
            inkypi_config = InkyPiConfig(
                repo_path=tmpdir_path / "InkyPi",
                validated_commit="main",
                waveshare_model="epd7in3e",
                plugin_id="telegram_frame",
                payload_dir=tmpdir_path / "inkypi",
                refresh_command="python3 -c \"print('refresh ok')\"",
            )
            adapter = InkyPiAdapter(inkypi_config, storage_config)
            request = DisplayRequest(
                image_id="img-1",
                original_path=tmpdir_path / "original.jpg",
                composed_path=source_image,
                location="Berlin",
                taken_at="2026-03-18",
                caption="Caption",
                created_at="2026-03-18T12:00:00+00:00",
                uploaded_by=1,
            )

            result = adapter.display(request)

            self.assertTrue(result.success)
            self.assertTrue(storage_config.current_payload_path.exists())
            self.assertTrue(storage_config.current_image_path.exists())


if __name__ == "__main__":
    unittest.main()

