#!/usr/bin/env python3
"""Display sync daemon — polls Dropbox for new display payloads and triggers InkyPi.

Runs on the display Pi. Checks Dropbox for updated current.json + current.png,
downloads them locally, patches paths, and calls the local InkyPi update_now endpoint.

Usage:
    python scripts/display_sync.py [--once] [--interval SECONDS]

    --once       Run a single sync check and exit (useful for cron or startup scripts)
    --interval   Override the poll interval from config (default: 60 seconds)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import signal
import sys
import tempfile
import time
from pathlib import Path
from urllib import error, parse, request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("display_sync")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import dropbox
    from dropbox.files import WriteMode  # noqa: F401
except ImportError:
    logger.error("dropbox package not installed. Run: pip install 'dropbox>=12,<13'")
    sys.exit(1)

try:
    import yaml
except ImportError:
    logger.error("pyyaml package not installed. Run: pip install pyyaml")
    sys.exit(1)

from dotenv import load_dotenv

DEFAULT_POLL_INTERVAL = 60
DEFAULT_UPDATE_NOW_URL = "http://127.0.0.1/update_now"
DEFAULT_PLUGIN_ID = "telegram_frame"
APPLIED_REVISION_FILENAME = ".display_sync_applied_revision"

_shutdown = False


def _handle_signal(signum: int, frame: object) -> None:
    global _shutdown
    logger.info("Received signal %s, shutting down gracefully", signum)
    _shutdown = True


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


def load_sync_config(config_path: Path) -> dict:
    """Load relevant config values from config.yaml + .env."""
    env_path = Path(os.getenv("PHOTO_FRAME_ENV_FILE") or os.getenv("ENV_FILE") or PROJECT_ROOT / ".env")
    load_dotenv(env_path)

    if not config_path.exists():
        logger.error("Config file not found: %s", config_path)
        sys.exit(1)

    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    dropbox_section = raw.get("dropbox", {})
    token_env = str(dropbox_section.get("access_token_env", "DROPBOX_ACCESS_TOKEN"))
    token = os.getenv(token_env, "").strip() or None
    refresh_token_env = str(dropbox_section.get("refresh_token_env", "DROPBOX_REFRESH_TOKEN"))
    refresh_token = os.getenv(refresh_token_env, "").strip() or None
    app_key = str(dropbox_section.get("app_key", "")).strip() or None

    has_refresh = refresh_token and app_key
    if not has_refresh and not token:
        logger.error("No Dropbox credentials found. Set %s + dropbox.app_key, or %s", refresh_token_env, token_env)
        sys.exit(1)

    root_path = str(dropbox_section.get("root_path", "/photo-frame")).rstrip("/") or "/photo-frame"

    storage_section = raw.get("storage", {})
    payload_dir = storage_section.get("inkypi_payload_dir", "data/inkypi")
    payload_path = Path(payload_dir)
    if not payload_path.is_absolute():
        payload_path = PROJECT_ROOT / payload_path

    inkypi_section = raw.get("inkypi", {})
    update_now_url = str(inkypi_section.get("update_now_url", DEFAULT_UPDATE_NOW_URL)).strip()
    plugin_id = str(inkypi_section.get("plugin_id", DEFAULT_PLUGIN_ID))

    sync_section = raw.get("display_sync", {})
    poll_interval = int(sync_section.get("poll_interval", DEFAULT_POLL_INTERVAL))

    return {
        "dropbox_token": token,
        "dropbox_refresh_token": refresh_token,
        "dropbox_app_key": app_key,
        "root_path": root_path,
        "payload_dir": payload_path,
        "update_now_url": update_now_url,
        "plugin_id": plugin_id,
        "poll_interval": poll_interval,
    }


def get_local_revision(payload_path: Path) -> str:
    """Read the revision field from the local current.json, or empty string."""
    try:
        data = json.loads(payload_path.read_text(encoding="utf-8"))
        return str(data.get("revision", ""))
    except (json.JSONDecodeError, OSError):
        return ""


def _applied_revision_path(payload_dir: Path) -> Path:
    return payload_dir / APPLIED_REVISION_FILENAME


def get_applied_revision(payload_dir: Path) -> str:
    path = _applied_revision_path(payload_dir)
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def set_applied_revision(payload_dir: Path, revision: str) -> None:
    path = _applied_revision_path(payload_dir)
    payload_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=payload_dir, delete=False) as tmp:
        tmp.write(revision.strip() + "\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def resolve_revision(payload: dict, payload_bytes: bytes) -> str:
    revision = str(payload.get("revision", "")).strip()
    if revision:
        return revision
    return hashlib.sha256(payload_bytes).hexdigest()[:16]


def download_and_patch(
    client: dropbox.Dropbox,
    root_path: str,
    payload_dir: Path,
) -> str | None:
    """Ensure current.json + current.png are ready locally. Returns the pending revision."""
    remote_json = f"{root_path}/display/current.json".replace("//", "/")
    remote_png = f"{root_path}/display/current.png".replace("//", "/")

    local_json = payload_dir / "current.json"
    local_png = payload_dir / "current.png"

    # Check remote revision first
    try:
        _, response = client.files_download(remote_json)
    except Exception as exc:
        logger.warning("Failed to download %s: %s", remote_json, exc)
        return None

    try:
        remote_payload = json.loads(response.content)
    except json.JSONDecodeError as exc:
        logger.warning("Remote payload is not valid JSON: %s", exc)
        return None

    remote_revision = resolve_revision(remote_payload, response.content)
    remote_payload["revision"] = remote_revision
    applied_revision = get_applied_revision(payload_dir)

    if remote_revision == applied_revision:
        logger.debug("Revision already applied (%s), skipping", remote_revision)
        return None

    local_revision = get_local_revision(local_json)
    if remote_revision == local_revision and local_png.exists():
        logger.info("Revision %s already downloaded locally, retrying display trigger", remote_revision)
        return remote_revision

    logger.info("New revision detected: %s (last applied: %s)", remote_revision, applied_revision or "(none)")

    # Download image
    try:
        _, img_response = client.files_download(remote_png)
    except Exception as exc:
        logger.warning("Failed to download %s: %s", remote_png, exc)
        return None

    # Write image atomically
    payload_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=payload_dir, delete=False) as tmp:
        tmp.write(img_response.content)
        tmp_path = Path(tmp.name)
    tmp_path.replace(local_png)
    logger.info("Downloaded %s (%d bytes)", local_png.name, len(img_response.content))

    # Patch payload paths to local absolute paths
    remote_payload["prepared_image_path"] = str(local_png)
    remote_payload["bridge_image_path"] = str(local_png)
    remote_payload["payload_path"] = str(local_json)

    # Write payload atomically
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=payload_dir, delete=False) as tmp:
        json.dump(remote_payload, tmp, indent=2, sort_keys=True)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(local_json)
    logger.info("Downloaded and patched %s", local_json.name)

    return remote_revision


def trigger_update(update_now_url: str, plugin_id: str, payload_path: Path) -> bool:
    """POST to InkyPi's update_now endpoint. Returns True on success."""
    form = parse.urlencode({
        "plugin_id": plugin_id,
        "payload_path": str(payload_path),
    }).encode("utf-8")
    http_request = request.Request(
        update_now_url,
        data=form,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with request.urlopen(http_request, timeout=60) as response:
            body = response.read().decode("utf-8", errors="replace")
            logger.info("InkyPi update_now response (%d): %s", response.status, body[:200])
            return response.status < 300
    except error.HTTPError as exc:
        logger.warning("InkyPi update_now returned HTTP %d", exc.code)
        return False
    except error.URLError as exc:
        logger.warning("InkyPi update_now failed: %s", exc.reason)
        return False


def sync_once(config: dict) -> bool:
    """Run a single sync cycle. Returns True if a new image was displayed."""
    if config.get("dropbox_refresh_token") and config.get("dropbox_app_key"):
        client = dropbox.Dropbox(
            oauth2_refresh_token=config["dropbox_refresh_token"],
            app_key=config["dropbox_app_key"],
        )
    else:
        client = dropbox.Dropbox(config["dropbox_token"])
    payload_dir = config["payload_dir"]

    revision = download_and_patch(client, config["root_path"], payload_dir)
    if not revision:
        logger.info("No new display payload")
        return False

    local_json = payload_dir / "current.json"
    ok = trigger_update(config["update_now_url"], config["plugin_id"], local_json)
    if ok:
        try:
            set_applied_revision(payload_dir, revision)
        except OSError as exc:
            logger.warning("Display updated, but failed to persist applied revision %s: %s", revision, exc)
            return False
        logger.info("Display updated successfully")
    else:
        logger.warning("Display update trigger failed — will retry revision %s on the next sync", revision)
    return ok


def run_daemon(config: dict, interval: int) -> None:
    """Run the sync loop until shutdown signal."""
    logger.info("Display sync daemon starting (interval: %ds)", interval)

    # Immediate first check
    try:
        sync_once(config)
    except Exception:
        logger.exception("Error during initial sync")

    while not _shutdown:
        deadline = time.monotonic() + interval
        while not _shutdown and time.monotonic() < deadline:
            time.sleep(min(5, deadline - time.monotonic()))

        if _shutdown:
            break

        try:
            sync_once(config)
        except Exception:
            logger.exception("Error during sync cycle")

    logger.info("Display sync daemon stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description="Display sync daemon for Dropbox-based two-Pi setup")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    parser.add_argument("--once", action="store_true", help="Run a single sync check and exit")
    parser.add_argument("--interval", type=int, default=None, help="Override poll interval (seconds)")
    args = parser.parse_args()

    config_path = Path(
        args.config
        or os.getenv("PHOTO_FRAME_CONFIG")
        or os.getenv("CONFIG_FILE")
        or PROJECT_ROOT / "config" / "config.yaml"
    )
    config = load_sync_config(config_path)

    interval = args.interval or config["poll_interval"]

    if args.once:
        sync_once(config)
    else:
        run_daemon(config, interval)


if __name__ == "__main__":
    main()
