from __future__ import annotations

import json
from pathlib import Path

from PIL import Image
from plugins.base_plugin.base_plugin import BasePlugin


class TelegramFrame(BasePlugin):
    def generate_image(self, settings, device_config):  # noqa: D401 - InkyPi API method
        payload_path = settings.get("payload_path")
        if not payload_path:
            raise RuntimeError("Missing payload_path in plugin settings.")

        payload_file = Path(payload_path)
        if not payload_file.exists():
            raise RuntimeError(f"Payload file not found: {payload_file}")

        try:
            payload = json.loads(payload_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Payload file is not valid JSON: {exc}") from exc

        image_path = Path(payload.get("bridge_image_path") or payload.get("composed_path", ""))
        if not image_path.exists():
            raise RuntimeError(f"Bridge image not found: {image_path}")

        return Image.open(image_path).convert("RGB")
