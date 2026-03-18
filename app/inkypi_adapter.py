from __future__ import annotations

import hashlib
import json
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.models import DisplayRequest, DisplayResult, InkyPiConfig, StorageConfig


class InkyPiAdapter:
    def __init__(self, config: InkyPiConfig, storage: StorageConfig):
        self.config = config
        self.storage = storage

    def display(self, request: DisplayRequest) -> DisplayResult:
        payload_path = self._write_bridge_payload(request)
        command = self._format_refresh_command(payload_path, self.storage.current_image_path)
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip() or completed.stdout.strip() or "unknown refresh error"
            return DisplayResult(False, f"InkyPi refresh failed: {stderr}", payload_path=payload_path)
        stdout = completed.stdout.strip() or "refresh command completed successfully"
        return DisplayResult(True, stdout, payload_path=payload_path)

    def refresh_only(self) -> DisplayResult:
        command = self._format_refresh_command(
            self.storage.current_payload_path,
            self.storage.current_image_path,
        )
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip() or completed.stdout.strip() or "unknown refresh error"
            return DisplayResult(False, f"InkyPi refresh failed: {stderr}")
        return DisplayResult(True, completed.stdout.strip() or "refresh command completed successfully")

    def _write_bridge_payload(self, request: DisplayRequest) -> Path:
        self.storage.inkypi_payload_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(request.composed_path, self.storage.current_image_path)

        payload = request.to_payload()
        payload["bridge_image_path"] = str(self.storage.current_image_path)
        payload["payload_path"] = str(self.storage.current_payload_path)
        payload["plugin_id"] = self.config.plugin_id
        payload["revision"] = self._revision_hash(payload)

        self.storage.current_payload_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.storage.current_payload_path.parent,
            delete=False,
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(self.storage.current_payload_path)
        return self.storage.current_payload_path

    def _revision_hash(self, payload: dict[str, object]) -> str:
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:16]

    def _format_refresh_command(self, payload_path: Path, image_path: Path) -> list[str]:
        command = self.config.refresh_command.format(
            payload_path=payload_path,
            image_path=image_path,
            repo_path=self.config.repo_path,
            install_path=self.config.install_path,
            plugin_id=self.config.plugin_id,
        )
        return shlex.split(command)
