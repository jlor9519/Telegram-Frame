from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageOps
from plugins.base_plugin.base_plugin import BasePlugin


DEFAULT_CAPTION_BAR_HEIGHT = 44
DEFAULT_CAPTION_FONT_SIZE = 20
DEFAULT_CAPTION_MARGIN = 12
DEFAULT_CAPTION_TEXT_COLOR = "#111111"
DEFAULT_CAPTION_BACKGROUND_COLOR = "#FFFFFF"


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

        image_path = Path(
            payload.get("prepared_image_path")
            or payload.get("bridge_image_path")
            or payload.get("composed_path", "")
        )
        if not image_path.exists():
            raise RuntimeError(f"Prepared image not found: {image_path}")

        orientation = str(payload.get("orientation_hint") or device_config.get_config("orientation") or "horizontal")
        width, height = self._resolve_dimensions(device_config, orientation)
        caption_bar_height = self._safe_int(payload.get("caption_bar_height"), DEFAULT_CAPTION_BAR_HEIGHT)
        caption_bar_height = max(1, min(caption_bar_height, height - 1))
        photo_height = max(1, height - caption_bar_height)

        with Image.open(image_path) as prepared_image:
            prepared_rgb = prepared_image.convert("RGB")
            final_image = self._compose_final_image(
                prepared_rgb,
                width=width,
                height=height,
                photo_height=photo_height,
                caption=payload.get("caption", ""),
                caption_bar_height=caption_bar_height,
                caption_font_size=self._safe_int(payload.get("caption_font_size"), DEFAULT_CAPTION_FONT_SIZE),
                caption_margin=self._safe_int(payload.get("caption_margin"), DEFAULT_CAPTION_MARGIN),
                font_path=str(payload.get("font_path") or ""),
                caption_text_color=str(payload.get("caption_text_color") or DEFAULT_CAPTION_TEXT_COLOR),
                caption_background_color=str(payload.get("caption_background_color") or DEFAULT_CAPTION_BACKGROUND_COLOR),
            )

        return final_image

    def _compose_final_image(
        self,
        prepared_image: Image.Image,
        *,
        width: int,
        height: int,
        photo_height: int,
        caption: str,
        caption_bar_height: int,
        caption_font_size: int,
        caption_margin: int,
        font_path: str,
        caption_text_color: str,
        caption_background_color: str,
    ) -> Image.Image:
        final_image = Image.new("RGB", (width, height), ImageColor.getrgb(caption_background_color))
        photo_area_size = (width, photo_height)

        blurred_background = ImageOps.fit(
            prepared_image,
            photo_area_size,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        ).filter(ImageFilter.GaussianBlur(radius=18))
        final_image.paste(blurred_background, (0, 0))

        contained = ImageOps.contain(
            prepared_image,
            photo_area_size,
            method=Image.Resampling.LANCZOS,
        )
        paste_x = (width - contained.width) // 2
        paste_y = (photo_height - contained.height) // 2
        final_image.paste(contained, (paste_x, paste_y))

        draw = ImageDraw.Draw(final_image)
        bar_top = photo_height
        draw.rectangle(
            [(0, bar_top), (width, height)],
            fill=ImageColor.getrgb(caption_background_color),
        )

        font = self._load_font(font_path, caption_font_size)
        text_color = ImageColor.getrgb(caption_text_color)
        text = self._truncate_line(
            draw,
            str(caption or "").strip(),
            font,
            max(1, width - (caption_margin * 2)),
        )

        if text:
            text_bbox = draw.textbbox((0, 0), text, font=font)
            text_height = text_bbox[3] - text_bbox[1]
            text_y = bar_top + max(0, (caption_bar_height - text_height) // 2) - text_bbox[1]
            draw.text(
                (caption_margin, text_y),
                text,
                font=font,
                fill=text_color,
            )

        return final_image

    def _resolve_dimensions(self, device_config, orientation: str) -> tuple[int, int]:
        width, height = device_config.get_resolution()
        if orientation == "vertical":
            return height, width
        return width, height

    def _load_font(self, font_path: str, size: int) -> ImageFont.ImageFont:
        if font_path:
            try:
                return ImageFont.truetype(font_path, size=size)
            except OSError:
                pass
        return ImageFont.load_default()

    def _truncate_line(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.ImageFont,
        max_width: int,
    ) -> str:
        if not text:
            return ""

        candidate = " ".join(text.split())
        ellipsis = "..."
        while candidate and draw.textlength(candidate, font=font) > max_width:
            if draw.textlength(candidate + ellipsis, font=font) <= max_width:
                return candidate + ellipsis
            candidate = candidate[:-1].rstrip()
        return candidate or ellipsis

    def _safe_int(self, value, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
