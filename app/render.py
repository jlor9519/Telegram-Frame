from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

from app.models import DisplayConfig


class RenderService:
    def __init__(self, config: DisplayConfig):
        self.config = config

    def render(
        self,
        original_path: Path,
        output_path: Path,
        *,
        location: str,
        taken_at: str,
        caption: str,
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(original_path) as original:
            prepared = ImageOps.exif_transpose(original).convert("RGB")
            prepared.save(output_path, format="PNG")
        return output_path
