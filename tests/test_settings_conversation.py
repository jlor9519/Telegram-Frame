from __future__ import annotations

import unittest
from types import SimpleNamespace

from telegram.ext import ConversationHandler

from app.models import DeviceSettingsApplyResult
from app.settings_conversation import (
    PENDING_SETTINGS_KEY,
    WAITING_FOR_SETTINGS_CHOICE,
    WAITING_FOR_SETTINGS_VALUE,
    receive_settings_value,
    settings_entry,
)


class SettingsConversationTests(unittest.IsolatedAsyncioTestCase):
    async def test_settings_entry_rejects_non_admin(self) -> None:
        services = _FakeServices(is_admin=False)
        update = _FakeUpdate("/settings", user_id=11)
        context = _FakeContext(services)

        result = await settings_entry(update, context)

        self.assertIsNone(result)
        self.assertEqual(update.effective_message.replies, ["Dieser Befehl ist nur für Admins verfügbar."])

    async def test_settings_entry_shows_only_persistent_image_tuning_options(self) -> None:
        services = _FakeServices(is_admin=True)
        update = _FakeUpdate("/settings", user_id=11)
        context = _FakeContext(services)

        result = await settings_entry(update, context)

        self.assertEqual(result, WAITING_FOR_SETTINGS_CHOICE)
        self.assertEqual(len(update.effective_message.replies), 1)
        reply = update.effective_message.replies[0]
        self.assertIn("1. Sättigung", reply)
        self.assertIn("2. Kontrast", reply)
        self.assertIn("3. Schärfe", reply)
        self.assertIn("4. Helligkeit", reply)
        self.assertNotIn("Ausrichtung", reply)

    async def test_receive_settings_value_applies_and_confirms_value(self) -> None:
        services = _FakeServices(is_admin=True)
        services.display.apply_result = DeviceSettingsApplyResult(
            success=True,
            message="Einstellungen wurden gespeichert, InkyPi wurde neu geladen und die Anzeige aktualisiert.",
            confirmed_settings={"image_settings": {"saturation": 1.8}},
            device_config_path=services.display.device_config_path,
            saved=True,
            reloaded=True,
            refreshed=True,
        )
        update = _FakeUpdate("1.8", user_id=11)
        context = _FakeContext(services)
        context.user_data[PENDING_SETTINGS_KEY] = 0

        result = await receive_settings_value(update, context)

        self.assertEqual(result, ConversationHandler.END)
        self.assertEqual(
            services.display.last_updates,
            {"image_settings": {"saturation": 1.8}},
        )
        self.assertEqual(services.display.last_refresh_current, True)
        self.assertEqual(len(update.effective_message.replies), 1)
        reply = update.effective_message.replies[0]
        self.assertIn("Sättigung ist jetzt 1.8", reply)
        self.assertIn("Anzeige aktualisiert", reply)

    async def test_receive_settings_value_rejects_invalid_float(self) -> None:
        services = _FakeServices(is_admin=True)
        update = _FakeUpdate("abc", user_id=11)
        context = _FakeContext(services)
        context.user_data[PENDING_SETTINGS_KEY] = 0

        result = await receive_settings_value(update, context)

        self.assertEqual(result, WAITING_FOR_SETTINGS_VALUE)
        self.assertEqual(context.user_data[PENDING_SETTINGS_KEY], 0)
        self.assertEqual(len(update.effective_message.replies), 1)
        self.assertIn("Ungültiger Wert", update.effective_message.replies[0])
        self.assertIsNone(services.display.last_updates)


class _FakeAuth:
    def __init__(self, *, is_admin: bool):
        self._is_admin = is_admin
        self.synced_user_ids: list[int] = []

    def sync_user(self, user) -> None:
        self.synced_user_ids.append(user.id)

    def is_admin(self, user_id: int) -> bool:
        return self._is_admin


class _FakeDisplay:
    def __init__(self) -> None:
        self.device_config_path = "/tmp/device.json"
        self.settings = {
            "image_settings": {
                "saturation": 1.4,
                "contrast": 1.4,
                "sharpness": 1.2,
                "brightness": 1.1,
            }
        }
        self.apply_result = DeviceSettingsApplyResult(
            success=True,
            message="ok",
            confirmed_settings=self.settings,
            device_config_path=self.device_config_path,
            saved=True,
            reloaded=True,
            refreshed=True,
        )
        self.last_updates: dict[str, object] | None = None
        self.last_refresh_current: bool | None = None

    def read_device_settings(self) -> dict[str, object]:
        return self.settings

    def apply_device_settings(
        self,
        updates: dict[str, object],
        *,
        refresh_current: bool = True,
    ) -> DeviceSettingsApplyResult:
        self.last_updates = updates
        self.last_refresh_current = refresh_current
        return self.apply_result


class _FakeServices:
    def __init__(self, *, is_admin: bool):
        self.auth = _FakeAuth(is_admin=is_admin)
        self.display = _FakeDisplay()


class _FakeMessage:
    def __init__(self, text: str):
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


class _FakeUser:
    def __init__(self, user_id: int):
        self.id = user_id


class _FakeUpdate:
    def __init__(self, text: str, *, user_id: int):
        self.effective_user = _FakeUser(user_id)
        self.effective_message = _FakeMessage(text)


class _FakeContext:
    def __init__(self, services: _FakeServices):
        self.application = SimpleNamespace(bot_data={"services": services})
        self.user_data: dict[str, object] = {}


if __name__ == "__main__":
    unittest.main()
