from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.models import StorageConfig


class StorageService:
    def __init__(self, config: StorageConfig):
        self.config = config

    def ensure_directories(self) -> None:
        for path in self._directories():
            path.mkdir(parents=True, exist_ok=True)

    def generate_image_id(self) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return f"{stamp}_{uuid.uuid4().hex[:8]}"

    def original_path(self, image_id: str, extension: str = ".jpg") -> Path:
        return self.config.incoming_dir / f"{image_id}{extension}"

    def rendered_path(self, image_id: str, extension: str = ".png") -> Path:
        return self.config.rendered_dir / f"{image_id}{extension}"

    def cleanup_rendered_cache(self) -> None:
        keep = max(self.config.keep_recent_rendered, 0)
        rendered_files = sorted(
            (path for path in self.config.rendered_dir.glob("*") if path.is_file()),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for old_file in rendered_files[keep:]:
            if old_file.name == ".gitkeep":
                continue
            old_file.unlink(missing_ok=True)

    def _directories(self) -> Iterable[Path]:
        return (
            self.config.incoming_dir,
            self.config.rendered_dir,
            self.config.cache_dir,
            self.config.archive_dir,
            self.config.inkypi_payload_dir,
            self.config.current_payload_path.parent,
            self.config.current_image_path.parent,
        )

