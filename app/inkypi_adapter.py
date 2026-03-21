from __future__ import annotations

import hashlib
import json
import logging
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib import error, parse, request

logger = logging.getLogger(__name__)

from PIL import Image

from app.inkypi_paths import resolve_inkypi_layout
from app.models import (
    DeviceSettingsApplyResult,
    DisplayConfig,
    DisplayRequest,
    DisplayResult,
    InkyPiConfig,
    StorageConfig,
)


INKYPI_SERVICE_NAME = "inkypi.service"
INKYPI_RESTART_TIMEOUT_SECONDS = 45


def _write_device_json(path: Path, updates: dict[str, object]) -> None:
    data: dict[str, object] = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    data = _merge_device_settings(data, updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _merge_device_settings(existing: dict[str, object], updates: dict[str, object]) -> dict[str, object]:
    merged = dict(existing)
    for key, value in updates.items():
        if (
            key == "image_settings"
            and isinstance(value, dict)
            and isinstance(merged.get("image_settings"), dict)
        ):
            nested = dict(merged["image_settings"])
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


class InkyPiAdapter:
    def __init__(self, config: InkyPiConfig, storage: StorageConfig, display: DisplayConfig):
        self.config = config
        self.storage = storage
        self.display_config = display
        self.layout = resolve_inkypi_layout(config.repo_path, config.install_path)
        self._systemctl_bin = shutil.which("systemctl") or "/usr/bin/systemctl"

    def display(self, request: DisplayRequest) -> DisplayResult:
        logger.info("Writing bridge payload for image %s", request.image_id)
        payload_path = self._write_bridge_payload(request)
        result = self._trigger_display_update(payload_path)
        result.payload_path = payload_path
        logger.info("Display result for %s: success=%s", request.image_id, result.success)
        return result

    def read_device_settings(self) -> dict[str, object]:
        path = self._device_config_path()
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def apply_device_settings(
        self,
        updates: dict[str, object],
        *,
        refresh_current: bool = True,
    ) -> DeviceSettingsApplyResult:
        device_config_path = self._device_config_path()
        try:
            current = self.read_device_settings()
            merged = _merge_device_settings(current, updates)
            _write_device_json(device_config_path, merged)
            confirmed = self.read_device_settings()
        except PermissionError as exc:
            logger.warning("Permission denied saving device settings: %s", exc)
            return DeviceSettingsApplyResult(
                success=False,
                message=f"Einstellungen konnten nicht gespeichert werden: {exc}",
                confirmed_settings={},
                device_config_path=device_config_path,
            )
        except OSError as exc:
            logger.warning("OS error saving device settings: %s", exc)
            return DeviceSettingsApplyResult(
                success=False,
                message=f"Einstellungen konnten nicht gespeichert werden: {exc}",
                confirmed_settings={},
                device_config_path=device_config_path,
            )
        except json.JSONDecodeError as exc:
            logger.warning("Invalid JSON in device settings file: %s", exc)
            return DeviceSettingsApplyResult(
                success=False,
                message=f"device.json ist ungültiges JSON: {exc}",
                confirmed_settings={},
                device_config_path=device_config_path,
            )

        restart_error = self._restart_inkypi_service()
        if restart_error is not None:
            return DeviceSettingsApplyResult(
                success=False,
                message=(
                    "Einstellungen wurden gespeichert, aber InkyPi konnte nicht neu geladen werden: "
                    f"{restart_error}"
                ),
                confirmed_settings=confirmed,
                device_config_path=device_config_path,
                saved=True,
            )

        if not refresh_current:
            return DeviceSettingsApplyResult(
                success=True,
                message="Einstellungen wurden gespeichert und InkyPi wurde neu geladen.",
                confirmed_settings=confirmed,
                device_config_path=device_config_path,
                saved=True,
                reloaded=True,
                refresh_skipped=True,
            )

        if not self.storage.current_payload_path.exists():
            return DeviceSettingsApplyResult(
                success=True,
                message=(
                    "Einstellungen wurden gespeichert und InkyPi wurde neu geladen. "
                    "Es gibt noch kein aktuelles Bild, daher wurde keine Live-Aktualisierung ausgelost."
                ),
                confirmed_settings=confirmed,
                device_config_path=device_config_path,
                saved=True,
                reloaded=True,
                refresh_skipped=True,
            )

        refresh_result = self._trigger_display_update(self.storage.current_payload_path)
        if not refresh_result.success:
            return DeviceSettingsApplyResult(
                success=False,
                message=(
                    "Einstellungen wurden gespeichert und InkyPi wurde neu geladen, "
                    f"aber die Anzeige-Aktualisierung ist fehlgeschlagen: {refresh_result.message}"
                ),
                confirmed_settings=confirmed,
                device_config_path=device_config_path,
                saved=True,
                reloaded=True,
            )

        return DeviceSettingsApplyResult(
            success=True,
            message="Einstellungen wurden gespeichert, InkyPi wurde neu geladen und die Anzeige aktualisiert.",
            confirmed_settings=confirmed,
            device_config_path=device_config_path,
            saved=True,
            reloaded=True,
            refreshed=True,
        )

    def refresh_only(self) -> DisplayResult:
        return self._trigger_display_update(self.storage.current_payload_path)

    def _trigger_display_update(self, payload_path: Path) -> DisplayResult:
        try:
            payload = self._load_payload(payload_path)
        except json.JSONDecodeError as exc:
            return DisplayResult(False, f"InkyPi payload is not valid JSON: {exc}")

        if payload is None:
            return DisplayResult(False, f"InkyPi payload does not exist: {payload_path}")

        orientation_hint = str(payload.get("orientation_hint", "horizontal")).strip() or "horizontal"
        orientation_result = self._patch_device_orientation(orientation_hint)
        if orientation_result is not None:
            return orientation_result

        if self.config.update_method == "http_update_now":
            logger.info("Triggering display via HTTP POST to %s", self.config.update_now_url)
            return self._post_update_now(payload_path)

        command = self._format_refresh_command(payload_path, self.storage.current_image_path)
        logger.info("Triggering display via command: %s", command)
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Refresh command timed out after 60s")
            return DisplayResult(False, "InkyPi refresh command timed out after 60 seconds")
        if completed.returncode != 0:
            stderr = completed.stderr.strip() or completed.stdout.strip() or "unknown refresh error"
            return DisplayResult(False, f"InkyPi refresh failed: {stderr}")
        return DisplayResult(True, completed.stdout.strip() or "refresh command completed successfully")

    def _post_update_now(self, payload_path: Path) -> DisplayResult:
        form = parse.urlencode(
            {
                "plugin_id": self.config.plugin_id,
                "payload_path": str(payload_path),
            }
        ).encode("utf-8")
        http_request = request.Request(
            self.config.update_now_url,
            data=form,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        try:
            with request.urlopen(http_request, timeout=60) as response:
                body = response.read().decode("utf-8", errors="replace")
                return self._parse_http_response(body, response.status)
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            parsed = self._parse_http_response(body, exc.code)
            if parsed.success:
                return DisplayResult(False, f"InkyPi update_now returned HTTP {exc.code}")
            return parsed
        except error.URLError as exc:
            return DisplayResult(False, f"InkyPi update_now request failed: {exc.reason}")

    def _parse_http_response(self, body: str, status_code: int) -> DisplayResult:
        text = body.strip()
        parsed_json: dict[str, object] | None = None

        if text:
            try:
                candidate = json.loads(text)
            except json.JSONDecodeError:
                candidate = None
            if isinstance(candidate, dict):
                parsed_json = candidate

        if status_code < 200 or status_code >= 300:
            if parsed_json and parsed_json.get("error"):
                return DisplayResult(False, f"InkyPi update_now failed: {parsed_json['error']}")
            return DisplayResult(False, f"InkyPi update_now failed with HTTP {status_code}: {text or 'no response body'}")

        if parsed_json and parsed_json.get("error"):
            return DisplayResult(False, f"InkyPi update_now failed: {parsed_json['error']}")
        if parsed_json and parsed_json.get("message"):
            return DisplayResult(True, str(parsed_json["message"]))
        if text:
            return DisplayResult(True, text)
        return DisplayResult(True, "InkyPi update_now completed successfully")

    def _write_bridge_payload(self, request: DisplayRequest) -> Path:
        self.storage.inkypi_payload_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(request.composed_path, self.storage.current_image_path)
        orientation_hint = self._detect_orientation_hint(self.storage.current_image_path)

        payload = request.to_payload()
        payload["prepared_image_path"] = str(self.storage.current_image_path)
        payload["bridge_image_path"] = str(self.storage.current_image_path)
        payload["payload_path"] = str(self.storage.current_payload_path)
        payload["plugin_id"] = self.config.plugin_id
        payload["orientation_hint"] = orientation_hint
        payload["caption_bar_height"] = self.display_config.caption_height if request.show_caption else 0
        payload["caption_font_size"] = self.display_config.caption_font_size
        payload["caption_character_limit"] = self.display_config.caption_character_limit
        payload["caption_margin"] = self.display_config.margin
        payload["caption_max_lines"] = self.display_config.max_caption_lines
        payload["metadata_font_size"] = self.display_config.metadata_font_size
        payload["caption_text_color"] = self.display_config.text_color
        payload["caption_background_color"] = "#FFFFFF"
        payload["font_path"] = self.display_config.font_path
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

    def _load_payload(self, payload_path: Path) -> dict[str, object] | None:
        if not payload_path.exists():
            return None
        return json.loads(payload_path.read_text(encoding="utf-8"))

    def _detect_orientation_hint(self, image_path: Path) -> str:
        with Image.open(image_path) as image:
            return "vertical" if image.height > image.width else "horizontal"

    def _device_config_path(self) -> Path:
        return self.layout.device_config_path.resolve(strict=False)

    def _patch_device_orientation(self, orientation_hint: str) -> DisplayResult | None:
        device_config_path = self._device_config_path()
        try:
            data = json.loads(device_config_path.read_text(encoding="utf-8")) if device_config_path.exists() else {}
            if data.get("orientation") == orientation_hint:
                return None

            data["orientation"] = orientation_hint
            device_config_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=device_config_path.parent,
                delete=False,
            ) as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.write("\n")
                temp_path = Path(handle.name)
            temp_path.replace(device_config_path)
            return None
        except PermissionError as exc:
            logger.warning("Permission denied patching device orientation: %s", exc)
            return DisplayResult(False, f"Failed to update InkyPi orientation setting: {exc}")
        except OSError as exc:
            logger.warning("OS error patching device config: %s", exc)
            return DisplayResult(False, f"Failed to update InkyPi device config: {exc}")
        except json.JSONDecodeError as exc:
            logger.warning("Invalid JSON in device config: %s", exc)
            return DisplayResult(False, f"InkyPi device config is invalid JSON: {exc}")

    def _format_refresh_command(self, payload_path: Path, image_path: Path) -> list[str]:
        command = self.config.refresh_command.format(
            payload_path=payload_path,
            image_path=image_path,
            repo_path=self.config.repo_path,
            install_path=self.config.install_path,
            plugin_id=self.config.plugin_id,
        )
        return shlex.split(command)

    def _restart_inkypi_service(self) -> str | None:
        sudo_bin = shutil.which("sudo")
        if sudo_bin is None:
            return "sudo ist nicht verfugbar."

        restart_command = [
            sudo_bin,
            "-n",
            self._systemctl_bin,
            "restart",
            INKYPI_SERVICE_NAME,
        ]
        try:
            restart_completed = subprocess.run(
                restart_command,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return "Neustart von inkypi.service hat das Zeitlimit uberschritten."

        if restart_completed.returncode != 0:
            stderr = restart_completed.stderr.strip() or restart_completed.stdout.strip() or "unbekannter Fehler"
            if "password is required" in stderr.lower() or "a password is required" in stderr.lower():
                return (
                    "nicht-interaktive sudo-Rechte fur inkypi.service fehlen. "
                    "Fuhre scripts/setup_inkypi.sh erneut aus."
                )
            return stderr

        deadline = time.monotonic() + INKYPI_RESTART_TIMEOUT_SECONDS
        status_command = [
            sudo_bin,
            "-n",
            self._systemctl_bin,
            "is-active",
            INKYPI_SERVICE_NAME,
        ]
        last_status = "inkypi.service ist nicht aktiv geworden."
        while time.monotonic() < deadline:
            try:
                status_completed = subprocess.run(
                    status_command,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                last_status = "Abfrage von inkypi.service hat das Zeitlimit uberschritten."
                time.sleep(1)
                continue
            if status_completed.returncode == 0 and status_completed.stdout.strip() == "active":
                return None
            last_status = status_completed.stderr.strip() or status_completed.stdout.strip() or last_status
            time.sleep(1)

        return last_status
