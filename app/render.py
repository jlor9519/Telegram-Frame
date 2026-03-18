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
        image_height = self.config.height - self.config.caption_height

        background = Image.new(
            "RGB",
            (self.config.width, self.config.height),
            ImageColor.getrgb(self.config.background_color),
        )

        with Image.open(original_path) as original:
            fitted = ImageOps.fit(
                original.convert("RGB"),
                (self.config.width, image_height),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            background.paste(fitted, (0, 0))

        draw = ImageDraw.Draw(background)
        metadata_font = self._load_font(self.config.metadata_font_size)
        caption_font = self._load_font(self.config.caption_font_size)

        band_top = image_height
        divider_color = ImageColor.getrgb(self.config.divider_color)
        text_color = ImageColor.getrgb(self.config.text_color)
        draw.rectangle(
            [(0, band_top), (self.config.width, self.config.height)],
            fill=ImageColor.getrgb(self.config.background_color),
        )
        draw.line(
            [(self.config.margin, band_top), (self.config.width - self.config.margin, band_top)],
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

        caption_width = self.config.width - (self.config.margin * 2)
        caption_lines = self._wrap_text(draw, caption.strip(), caption_font, caption_width, self.config.max_caption_lines)
        caption_y = metadata_y + metadata_font.size + 18
        for line in caption_lines:
            draw.text((self.config.margin, caption_y), line, font=caption_font, fill=text_color)
            caption_y += caption_font.size + 8

        background.save(output_path, format="PNG")
        return output_path

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

