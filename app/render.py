from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps

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
        background = Image.new(
            "RGB",
            (self.config.width, self.config.height),
            ImageColor.getrgb(self.config.background_color),
        )
        with Image.open(original_path) as original:
            original_rgb = ImageOps.exif_transpose(original).convert("RGB")
            if self._is_portrait(original_rgb):
                self._render_portrait_layout(
                    background,
                    original_rgb,
                    location=location,
                    taken_at=taken_at,
                    caption=caption,
                )
            else:
                self._render_landscape_layout(
                    background,
                    original_rgb,
                    location=location,
                    taken_at=taken_at,
                    caption=caption,
                )

        background.save(output_path, format="PNG")
        return output_path

    def _render_landscape_layout(
        self,
        background: Image.Image,
        original: Image.Image,
        *,
        location: str,
        taken_at: str,
        caption: str,
    ) -> None:
        image_height = self.config.height - self.config.caption_height
        fitted = ImageOps.fit(
            original,
            (self.config.width, image_height),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
        background.paste(fitted, (0, 0))

        draw = ImageDraw.Draw(background)
        self._draw_bottom_text_band(
            draw,
            band_top=image_height,
            band_left=0,
            band_right=self.config.width,
            location=location,
            taken_at=taken_at,
            caption=caption,
        )

    def _render_portrait_layout(
        self,
        background: Image.Image,
        original: Image.Image,
        *,
        location: str,
        taken_at: str,
        caption: str,
    ) -> None:
        margin = self.config.margin
        divider_color = ImageColor.getrgb(self.config.divider_color)
        info_panel_width = max(250, int(self.config.width * 0.32))
        photo_left = margin
        photo_top = margin
        photo_right = self.config.width - info_panel_width - (margin * 2)
        photo_bottom = self.config.height - margin
        photo_width = max(1, photo_right - photo_left)
        photo_height = max(1, photo_bottom - photo_top)

        fitted = ImageOps.contain(
            original,
            (photo_width, photo_height),
            method=Image.Resampling.LANCZOS,
        )
        paste_x = photo_left + (photo_width - fitted.width) // 2
        paste_y = photo_top + (photo_height - fitted.height) // 2
        background.paste(fitted, (paste_x, paste_y))

        draw = ImageDraw.Draw(background)
        divider_x = photo_right + margin
        draw.line(
            [(divider_x, margin), (divider_x, self.config.height - margin)],
            fill=divider_color,
            width=2,
        )

        self._draw_side_text_panel(
            draw,
            panel_left=divider_x + margin,
            panel_top=margin,
            panel_right=self.config.width - margin,
            panel_bottom=self.config.height - margin,
            location=location,
            taken_at=taken_at,
            caption=caption,
        )

    def _draw_bottom_text_band(
        self,
        draw: ImageDraw.ImageDraw,
        *,
        band_top: int,
        band_left: int,
        band_right: int,
        location: str,
        taken_at: str,
        caption: str,
    ) -> None:
        metadata_font = self._load_font(self.config.metadata_font_size)
        caption_font = self._load_font(self.config.caption_font_size)
        divider_color = ImageColor.getrgb(self.config.divider_color)
        text_color = ImageColor.getrgb(self.config.text_color)
        background_color = ImageColor.getrgb(self.config.background_color)

        draw.rectangle(
            [(band_left, band_top), (band_right, self.config.height)],
            fill=background_color,
        )
        draw.line(
            [(self.config.margin, band_top), (band_right - self.config.margin, band_top)],
            fill=divider_color,
            width=2,
        )

        metadata_text = f"{location.strip()} | {taken_at.strip()}"
        metadata_y = band_top + self.config.margin
        draw.text(
            (self.config.margin, metadata_y),
            metadata_text,
            font=metadata_font,
            fill=text_color,
        )

        caption_width = band_right - band_left - (self.config.margin * 2)
        caption_lines = self._wrap_text(draw, caption.strip(), caption_font, caption_width, self.config.max_caption_lines)
        caption_y = metadata_y + metadata_font.size + 18
        for line in caption_lines:
            draw.text((self.config.margin, caption_y), line, font=caption_font, fill=text_color)
            caption_y += caption_font.size + 8

    def _draw_side_text_panel(
        self,
        draw: ImageDraw.ImageDraw,
        *,
        panel_left: int,
        panel_top: int,
        panel_right: int,
        panel_bottom: int,
        location: str,
        taken_at: str,
        caption: str,
    ) -> None:
        metadata_font = self._load_font(self.config.metadata_font_size)
        caption_font = self._load_font(self.config.caption_font_size)
        divider_color = ImageColor.getrgb(self.config.divider_color)
        text_color = ImageColor.getrgb(self.config.text_color)

        metadata_text = f"{location.strip()} | {taken_at.strip()}"
        draw.text(
            (panel_left, panel_top),
            metadata_text,
            font=metadata_font,
            fill=text_color,
        )

        divider_y = panel_top + metadata_font.size + 16
        draw.line(
            [(panel_left, divider_y), (panel_right, divider_y)],
            fill=divider_color,
            width=2,
        )

        caption_width = panel_right - panel_left
        caption_lines = self._wrap_text(draw, caption.strip(), caption_font, caption_width, max(self.config.max_caption_lines + 3, 4))
        caption_y = divider_y + 16
        line_step = caption_font.size + 8
        max_caption_bottom = panel_bottom
        for line in caption_lines:
            if caption_y + caption_font.size > max_caption_bottom:
                break
            draw.text((panel_left, caption_y), line, font=caption_font, fill=text_color)
            caption_y += line_step

    def _is_portrait(self, image: Image.Image) -> bool:
        return image.height > image.width

    def _load_font(self, size: int) -> ImageFont.ImageFont:
        try:
            return ImageFont.truetype(self.config.font_path, size=size)
        except OSError:
            return ImageFont.load_default()

    def _wrap_text(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.ImageFont,
        max_width: int,
        max_lines: int,
    ) -> list[str]:
        if not text:
            return [""]

        words = text.split()
        lines: list[str] = []
        current = words[0]

        for word in words[1:]:
            candidate = f"{current} {word}"
            if draw.textlength(candidate, font=font) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
                if len(lines) == max_lines - 1:
                    break

        remaining_words = words[len(" ".join(lines + [current]).split()):]
        if len(lines) < max_lines:
            tail = " ".join([current] + remaining_words).strip()
            if draw.textlength(tail, font=font) <= max_width:
                lines.append(tail)
            else:
                lines.append(self._truncate_line(draw, tail, font, max_width))
        return lines[:max_lines]

    def _truncate_line(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.ImageFont,
        max_width: int,
    ) -> str:
        candidate = text
        ellipsis = "..."
        while candidate and draw.textlength(candidate + ellipsis, font=font) > max_width:
            candidate = candidate[:-1].rstrip()
        return (candidate + ellipsis) if candidate else ellipsis
