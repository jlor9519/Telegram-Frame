from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from telegram.ext import ConversationHandler

from app.commands import _navigate_locked, cancel_command, refresh_command
from app.conversations import _conversation_timeout
from app.models import DisplayResult, ImageRecord, ProcessingReservation


class RemoteDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_command_reports_dropbox_failure_in_remote_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            services = _build_services(Path(tmpdir), upload_ok=False)
            update = _FakeUpdate("/refresh", user_id=11)
            context = _FakeContext(services)

            await refresh_command(update, context)

            self.assertEqual(len(update.effective_message.replies), 1)
            self.assertIn("Dropbox", update.effective_message.replies[0])

    async def test_navigation_reports_dropbox_failure_in_remote_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            services = _build_services(Path(tmpdir), upload_ok=False)
            update = _FakeUpdate("/next", user_id=11)
            context = _FakeContext(services)

            await _navigate_locked(update, context, "next")

            self.assertEqual(len(update.effective_message.replies), 1)
            self.assertIn("Dropbox", update.effective_message.replies[0])

    async def test_cancel_command_deletes_pending_original(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            services = _build_services(Path(tmpdir), upload_ok=True)
            update = _FakeUpdate("/cancel", user_id=11)
            context = _FakeContext(services)
            pending_file = Path(tmpdir) / "pending.jpg"
            pending_file.write_bytes(b"pending")
            context.user_data["pending_submission"] = {"original_path": str(pending_file)}
            context.application.bot_data["processing_reservation"] = ProcessingReservation(owner_user_id=11, image_id="img-1")

            result = await cancel_command(update, context)

            self.assertEqual(result, ConversationHandler.END)
            self.assertFalse(pending_file.exists())
            self.assertEqual(context.user_data, {})
            reservation = context.application.bot_data["processing_reservation"]
            self.assertIsNone(reservation.owner_user_id)
            self.assertIsNone(reservation.image_id)

    async def test_conversation_timeout_deletes_pending_original(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            services = _build_services(Path(tmpdir), upload_ok=True)
            update = _FakeUpdate("timeout", user_id=11)
            context = _FakeContext(services)
            pending_file = Path(tmpdir) / "pending-timeout.jpg"
            pending_file.write_bytes(b"pending")
            context.user_data["pending_submission"] = {"original_path": str(pending_file)}
            context.application.bot_data["processing_reservation"] = ProcessingReservation(owner_user_id=11, image_id="img-2")

            result = await _conversation_timeout(update, context)

            self.assertEqual(result, ConversationHandler.END)
            self.assertFalse(pending_file.exists())
            self.assertNotIn("pending_submission", context.user_data)
            self.assertIn("abgelaufen", update.effective_message.replies[0])


class _FakeAuth:
    def sync_user(self, user) -> None:
        return None

    def is_whitelisted(self, user_id: int) -> bool:
        return True


class _FakeDisplay:
    def __init__(self) -> None:
        self.refresh_result = DisplayResult(True, "ok")
        self.display_result = DisplayResult(True, "ok")

    def refresh_only(self) -> DisplayResult:
        return self.refresh_result

    def display(self, request) -> DisplayResult:
        return self.display_result


class _FakeDropbox:
    def __init__(self, *, upload_ok: bool) -> None:
        self.enabled = True
        self._upload_ok = upload_ok
        self.last_error = "Dropbox upload failed during test." if not upload_ok else None

    def upload_display_payload(self, payload_path: Path, image_path: Path) -> bool:
        return self._upload_ok

    def health_summary(self) -> str:
        return "connected" if self._upload_ok else "auth_failed"


class _FakeDatabase:
    def __init__(self, target: ImageRecord) -> None:
        self._target = target

    def get_adjacent_image(self, current_image_id: str, direction: str) -> ImageRecord | None:
        return self._target

    def count_displayed_images(self) -> int:
        return 2

    def get_displayed_image_position(self, image_id: str) -> int:
        return 2

    def get_setting(self, key: str) -> str | None:
        if key == "image_fit_mode":
            return "fill"
        return None

    def set_setting(self, key: str, value: str) -> None:
        return None

    def upsert_image(self, record: ImageRecord) -> None:
        self._target = record

    def get_image_by_id(self, image_id: str) -> ImageRecord | None:
        if image_id == self._target.image_id:
            return self._target
        return None


class _FakeServices:
    def __init__(self, config, database: _FakeDatabase, display: _FakeDisplay, dropbox: _FakeDropbox) -> None:
        self.config = config
        self.database = database
        self.display = display
        self.dropbox = dropbox
        self.auth = _FakeAuth()
        self.storage = SimpleNamespace(rendered_path=lambda image_id: Path("/tmp") / f"{image_id}.png")
        self.renderer = None


class _FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


class _FakeUser:
    def __init__(self, user_id: int) -> None:
        self.id = user_id


class _FakeUpdate:
    def __init__(self, text: str, *, user_id: int) -> None:
        self.effective_user = _FakeUser(user_id)
        self.effective_message = _FakeMessage(text)


class _FakeContext:
    def __init__(self, services: _FakeServices) -> None:
        self.application = SimpleNamespace(
            bot_data={
                "services": services,
                "display_lock": asyncio.Lock(),
                "processing_reservation": ProcessingReservation(),
            }
        )
        self.user_data: dict[str, object] = {}
        self.args: list[str] = []


def _build_services(tmpdir_path: Path, *, upload_ok: bool) -> _FakeServices:
    current_payload_path = tmpdir_path / "inkypi" / "current.json"
    current_image_path = tmpdir_path / "inkypi" / "current.png"
    current_payload_path.parent.mkdir(parents=True, exist_ok=True)
    current_image_path.write_bytes(b"png")
    current_payload_path.write_text(json.dumps({"image_id": "current"}), encoding="utf-8")

    rendered_path = tmpdir_path / "rendered" / "next.png"
    rendered_path.parent.mkdir(parents=True, exist_ok=True)
    rendered_path.write_bytes(b"rendered")
    original_path = tmpdir_path / "incoming" / "next.jpg"
    original_path.parent.mkdir(parents=True, exist_ok=True)
    original_path.write_bytes(b"original")

    target = ImageRecord(
        image_id="next",
        telegram_file_id="file-next",
        local_original_path=str(original_path),
        local_rendered_path=str(rendered_path),
        dropbox_original_path=None,
        dropbox_rendered_path=None,
        location="Berlin",
        taken_at="2026-03-18",
        caption="Caption",
        uploaded_by=11,
        created_at="2026-03-18T12:00:00+00:00",
        status="displayed",
        last_error=None,
    )

    config = _FakeConfig(current_payload_path=current_payload_path, current_image_path=current_image_path)
    return _FakeServices(
        config=config,
        database=_FakeDatabase(target),
        display=_FakeDisplay(),
        dropbox=_FakeDropbox(upload_ok=upload_ok),
    )


class _FakeConfig:
    def __init__(self, *, current_payload_path: Path, current_image_path: Path) -> None:
        self.storage = SimpleNamespace(
            current_payload_path=current_payload_path,
            current_image_path=current_image_path,
        )
        self.inkypi = SimpleNamespace(update_method="none")

    def uses_remote_display_transport(self) -> bool:
        return True


if __name__ == "__main__":
    unittest.main()
