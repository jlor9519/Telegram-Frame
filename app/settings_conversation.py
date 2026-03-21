from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from app.auth import require_admin
from app.commands import get_services

WAITING_FOR_SETTINGS_CHOICE, WAITING_FOR_SETTINGS_VALUE = range(10, 12)
PENDING_SETTINGS_KEY = "pending_settings_choice"


@dataclass(slots=True)
class _SettingDef:
    label: str
    key: str               # top-level key in device.json
    subkey: str | None     # key inside image_settings, or None
    kind: str              # "float" | "orientation"


_SETTINGS: list[_SettingDef] = [
    _SettingDef("Sättigung",    "image_settings", "saturation", "float"),
    _SettingDef("Kontrast",     "image_settings", "contrast",   "float"),
    _SettingDef("Schärfe",      "image_settings", "sharpness",  "float"),
    _SettingDef("Helligkeit",   "image_settings", "brightness", "float"),
    _SettingDef("Ausrichtung",  "orientation",    None,         "orientation"),
]


def _get_current_value(settings: dict[str, Any], s: _SettingDef) -> str:
    if s.kind == "orientation":
        orientation = str(settings.get("orientation", "?"))
        inverted = str(settings.get("inverted_image", "?")).lower()
        return f"{orientation} (inverted_image: {inverted})"
    if s.subkey:
        return str(settings.get(s.key, {}).get(s.subkey, "?"))
    return str(settings.get(s.key, "?"))


def _format_settings_list(settings: dict[str, Any]) -> str:
    lines = ["Aktuelle InkyPi-Einstellungen:", ""]
    for i, s in enumerate(_SETTINGS, 1):
        lines.append(f"{i}. {s.label}: {_get_current_value(settings, s)}")
    lines.append("")
    lines.append("Welche Einstellung möchtest du ändern? Antworte mit der Nummer oder /cancel.")
    return "\n".join(lines)


def _normalize_orientation_value(text: str) -> str | None:
    normalized = " ".join(text.strip().lower().split())
    mapping = {
        "horizontal": "horizontal",
        "landscape": "horizontal",
        "waagerecht": "horizontal",
        "querformat": "horizontal",
        "vertical": "vertical",
        "vertikal": "vertical",
        "hochformat": "vertical",
        "portrait": "vertical",
        "porträt": "vertical",
    }
    return mapping.get(normalized)


@require_admin
async def settings_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    services = get_services(context)
    if update.effective_message is None:
        return ConversationHandler.END
    try:
        device_settings = services.display.read_device_settings()
    except Exception as exc:
        logger.exception("Failed to read device settings")
        await update.effective_message.reply_text(f"Fehler beim Lesen der Einstellungen: {exc}")
        return ConversationHandler.END
    await update.effective_message.reply_text(_format_settings_list(device_settings))
    return WAITING_FOR_SETTINGS_CHOICE


async def receive_settings_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_message is None:
        return ConversationHandler.END
    text = (update.effective_message.text or "").strip()
    try:
        choice = int(text)
    except ValueError:
        await update.effective_message.reply_text(
            f"Bitte antworte mit einer Zahl zwischen 1 und {len(_SETTINGS)}, oder nutze /cancel."
        )
        return WAITING_FOR_SETTINGS_CHOICE
    if choice < 1 or choice > len(_SETTINGS):
        await update.effective_message.reply_text(
            f"Ungültige Auswahl. Bitte wähle eine Zahl zwischen 1 und {len(_SETTINGS)}, oder nutze /cancel."
        )
        return WAITING_FOR_SETTINGS_CHOICE

    s = _SETTINGS[choice - 1]
    context.user_data[PENDING_SETTINGS_KEY] = choice - 1

    services = get_services(context)
    current = _get_current_value(services.display.read_device_settings(), s)
    if s.kind == "orientation":
        await update.effective_message.reply_text(
            f"Aktueller Wert für {s.label}: {current}\n"
            "Gib den neuen Wert ein: horizontal oder vertical."
        )
    else:
        await update.effective_message.reply_text(
            f"Aktueller Wert für {s.label}: {current}\n"
            "Gib den neuen Wert ein (z.B. 1.0, 1.4, 2.0):"
        )
    return WAITING_FOR_SETTINGS_VALUE


async def receive_settings_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_message is None:
        return ConversationHandler.END
    idx = context.user_data.pop(PENDING_SETTINGS_KEY, None)
    if idx is None:
        return ConversationHandler.END

    s = _SETTINGS[idx]
    text = (update.effective_message.text or "").strip().lower()
    services = get_services(context)

    if s.kind == "orientation":
        orientation = _normalize_orientation_value(text)
        if orientation is None:
            await update.effective_message.reply_text(
                "Ungültiger Wert. Bitte gib horizontal oder vertical ein, oder nutze /cancel."
            )
            context.user_data[PENDING_SETTINGS_KEY] = idx
            return WAITING_FOR_SETTINGS_VALUE
        updates = {
            "orientation": orientation,
            "inverted_image": orientation == "vertical",
        }
        requested_value: str | float = orientation
    else:
        try:
            value = float(text.replace(",", "."))
        except ValueError:
            await update.effective_message.reply_text(
                "Ungültiger Wert. Bitte gib eine Zahl ein (z.B. 1.0), oder nutze /cancel."
            )
            context.user_data[PENDING_SETTINGS_KEY] = idx
            return WAITING_FOR_SETTINGS_VALUE
        if value < 0.1 or value > 3.0:
            await update.effective_message.reply_text(
                "Der Wert muss zwischen 0.1 und 3.0 liegen. Bitte erneut eingeben oder /cancel."
            )
            context.user_data[PENDING_SETTINGS_KEY] = idx
            return WAITING_FOR_SETTINGS_VALUE

        updates = {"image_settings": {str(s.subkey): value}}
        requested_value = value

    try:
        result = services.display.apply_device_settings(updates, refresh_current=True)
    except Exception as exc:
        logger.exception("Failed to write device settings")
        await update.effective_message.reply_text(f"Fehler beim Speichern der Einstellungen: {exc}")
        return ConversationHandler.END

    confirmed_value = _get_current_value(result.confirmed_settings, s) if result.confirmed_settings else str(requested_value)
    path_note = f" (device.json: {result.device_config_path})" if result.device_config_path else ""
    status_prefix = (
        f"{s.label} ist jetzt {confirmed_value}"
        if result.success
        else f"{s.label} wurde als {confirmed_value} gespeichert"
    )
    await update.effective_message.reply_text(f"{status_prefix}{path_note}.\n{result.message}")
    return ConversationHandler.END


async def _settings_unexpected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    state = context.user_data.get(PENDING_SETTINGS_KEY)
    if update.effective_message is not None:
        await update.effective_message.reply_text("Bitte beantworte die aktuelle Frage oder nutze /cancel.")
    return WAITING_FOR_SETTINGS_VALUE if state is not None else WAITING_FOR_SETTINGS_CHOICE


async def _settings_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop(PENDING_SETTINGS_KEY, None)
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "Einstellungs-Sitzung nach 2 Minuten Inaktivität beendet. Nutze /settings um neu zu starten."
        )
    return ConversationHandler.END


async def settings_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop(PENDING_SETTINGS_KEY, None)
    if update.effective_message is not None:
        await update.effective_message.reply_text("Einstellungs-Änderung abgebrochen.")
    return ConversationHandler.END


def build_settings_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("settings", settings_entry)],
        states={
            WAITING_FOR_SETTINGS_CHOICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_settings_choice),
                MessageHandler(filters.ALL & ~filters.COMMAND, _settings_unexpected),
            ],
            WAITING_FOR_SETTINGS_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_settings_value),
                MessageHandler(filters.ALL & ~filters.COMMAND, _settings_unexpected),
            ],
            ConversationHandler.TIMEOUT: [
                MessageHandler(filters.ALL, _settings_timeout),
            ],
        },
        fallbacks=[CommandHandler("cancel", settings_cancel)],
        allow_reentry=True,
        name="settings",
        persistent=False,
        conversation_timeout=120,
    )
