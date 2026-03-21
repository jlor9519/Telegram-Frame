from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from app.auth import require_admin, require_whitelist
from app.models import AppServices, DisplayRequest, ProcessingReservation


def get_services(context: ContextTypes.DEFAULT_TYPE) -> AppServices:
    return context.application.bot_data["services"]


def get_reservation(context: ContextTypes.DEFAULT_TYPE) -> ProcessingReservation:
    return context.application.bot_data["processing_reservation"]


def get_display_lock(context: ContextTypes.DEFAULT_TYPE) -> asyncio.Lock:
    return context.application.bot_data["display_lock"]


@require_whitelist
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "\n".join(
            [
                "Sende ein Foto, um den Upload-Prozess zu starten.",
                "Ich frage optional nach:",
                "- wo das Foto aufgenommen wurde",
                "- wann es aufgenommen wurde",
                "- welche Bildunterschrift angezeigt werden soll",
                "",
                "Befehle:",
                "/help - diese Nachricht anzeigen",
                "/next - nächstes Bild anzeigen",
                "/prev - vorheriges Bild anzeigen",
                "/delete - aktuelles Bild löschen",
                "/refresh - aktuelles Bild neu laden",
                "/settings - Anzeigeeinstellungen anzeigen/ändern (nur Admins)",
                "/status - Systemstatus anzeigen",
                "/myid - deine Telegram-Nutzer-ID anzeigen",
                "/cancel - den laufenden Upload abbrechen",
            ]
        )
    )


@require_whitelist
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context)
    latest = services.database.get_latest_image()
    reservation = get_reservation(context)
    latest_summary = "noch keines"
    if latest:
        latest_summary = f"{latest.image_id} ({latest.status})"

    active_owner = reservation.owner_user_id if reservation.owner_user_id is not None else "idle"
    if services.config.inkypi.update_method == "http_update_now":
        update_target = services.config.inkypi.update_now_url
    else:
        update_target = services.config.inkypi.refresh_command
    await update.effective_message.reply_text(
        "\n".join(
            [
                "Fotorahmen-Status",
                f"- Datenbank: {'ok' if services.database.healthcheck() else 'Fehler'}",
                f"- Freigegebene Nutzer: {services.database.count_whitelisted_users()}",
                f"- Dropbox: {services.dropbox.health_summary()}",
                f"- Letztes Bild: {latest_summary}",
                f"- Aktive Reservierung: {active_owner}",
                f"- Payload-Datei: {services.config.storage.current_payload_path}",
                f"- InkyPi-Updatemethode: {services.config.inkypi.update_method}",
                f"- InkyPi-Updateziel: {update_target}",
            ]
        )
    )


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.effective_message is None:
        return
    await update.effective_message.reply_text(f"Deine Telegram-Nutzer-ID lautet: {user.id}")


@require_admin
async def whitelist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context)
    if not context.args:
        await update.effective_message.reply_text("Verwendung: /whitelist <telegram_user_id>")
        return

    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("Die Nutzer-ID muss numerisch sein, zum Beispiel: /whitelist 123456789")
        return

    services.auth.whitelist_user(target_user_id)
    logger.info("User %d whitelisted by admin %d", target_user_id, update.effective_user.id)
    await update.effective_message.reply_text(f"Nutzer {target_user_id} wurde freigegeben.")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if user is None or update.effective_message is None:
        return ConversationHandler.END

    reservation = get_reservation(context)
    if reservation.owner_user_id == user.id:
        reservation.owner_user_id = None
        reservation.image_id = None
    context.user_data.clear()
    await update.effective_message.reply_text("Der aktuelle Upload wurde abgebrochen.")
    return ConversationHandler.END



@require_whitelist
async def refresh_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lock = get_display_lock(context)
    if lock.locked():
        await update.effective_message.reply_text("Eine Aktualisierung läuft bereits. Bitte warten.")
        return
    async with lock:
        services = get_services(context)
        result = await asyncio.to_thread(services.display.refresh_only)
        await update.effective_message.reply_text(
            "Aktualisierung ausgelöst." if result.success else f"Aktualisierung fehlgeschlagen: {result.message}"
        )


async def _navigate(update: Update, context: ContextTypes.DEFAULT_TYPE, direction: str) -> None:
    message = update.effective_message
    if message is None:
        return

    lock = get_display_lock(context)
    if lock.locked():
        await message.reply_text("Eine Aktualisierung läuft bereits. Bitte warten.")
        return
    async with lock:
        await _navigate_locked(update, context, direction)


async def _navigate_locked(update: Update, context: ContextTypes.DEFAULT_TYPE, direction: str) -> None:
    services = get_services(context)
    message = update.effective_message
    if message is None:
        return

    payload_path = services.config.storage.current_payload_path
    if not payload_path.exists():
        await message.reply_text("Noch kein Bild vorhanden.")
        return

    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        await message.reply_text("Aktuelle Payload-Datei konnte nicht gelesen werden.")
        return

    current_image_id = payload.get("image_id")
    if not current_image_id:
        await message.reply_text("Kein aktuelles Bild erkannt.")
        return

    target = services.database.get_adjacent_image(current_image_id, direction)
    if target is None:
        await message.reply_text("Kein weiteres Bild vorhanden.")
        return

    rendered_path = Path(target.local_rendered_path) if target.local_rendered_path else None
    original_path = Path(target.local_original_path)

    if rendered_path is None or not rendered_path.exists():
        if not original_path.exists():
            await message.reply_text(f"Bilddatei für {target.image_id} nicht mehr vorhanden.")
            return
        rendered_path = services.storage.rendered_path(target.image_id)
        await asyncio.to_thread(
            services.renderer.render,
            original_path,
            rendered_path,
            location=target.location,
            taken_at=target.taken_at,
            caption=target.caption,
        )
        target.local_rendered_path = str(rendered_path)
        services.database.upsert_image(target)

    show_caption = bool(target.caption or target.location or target.taken_at)
    display_request = DisplayRequest(
        image_id=target.image_id,
        original_path=original_path,
        composed_path=rendered_path,
        location=target.location,
        taken_at=target.taken_at,
        caption=target.caption,
        created_at=target.created_at,
        uploaded_by=target.uploaded_by,
        show_caption=show_caption,
    )

    result = await asyncio.to_thread(services.display.display, display_request)

    total = services.database.count_displayed_images()
    position = services.database.get_displayed_image_position(target.image_id)
    if result.success:
        await message.reply_text(f"Bild {position} von {total}: {target.image_id}")
    else:
        await message.reply_text(f"Anzeige fehlgeschlagen: {result.message}")


@require_whitelist
async def next_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _navigate(update, context, "next")


@require_whitelist
async def prev_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _navigate(update, context, "prev")


@require_whitelist
async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    services = get_services(context)
    payload_path = services.config.storage.current_payload_path
    if not payload_path.exists():
        await message.reply_text("Kein Bild zum Löschen vorhanden.")
        return

    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        await message.reply_text("Aktuelle Payload-Datei konnte nicht gelesen werden.")
        return

    current_image_id = payload.get("image_id")
    if not current_image_id:
        await message.reply_text("Kein aktuelles Bild erkannt.")
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Ja, löschen", callback_data=f"delete_confirm:{current_image_id}"),
            InlineKeyboardButton("Abbrechen", callback_data="delete_cancel"),
        ],
    ])

    # Send the current image as a preview so the user knows what they're deleting
    image_path = services.config.storage.current_image_path
    record = services.database.get_image_by_id(current_image_id)
    if not image_path.exists() and record and record.local_rendered_path:
        image_path = Path(record.local_rendered_path)
    if not image_path.exists() and record:
        image_path = Path(record.local_original_path)

    if image_path.exists():
        with open(image_path, "rb") as photo:
            await message.reply_photo(
                photo=photo,
                caption=f"Bild {current_image_id} wirklich löschen?",
                reply_markup=keyboard,
            )
    else:
        await message.reply_text(
            f"Bild {current_image_id} wirklich löschen?",
            reply_markup=keyboard,
        )


async def delete_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    lock = get_display_lock(context)
    if lock.locked():
        await query.edit_message_caption(caption="Eine Aktualisierung läuft bereits. Bitte warten.")
        return

    async with lock:
        image_id = query.data.split(":", 1)[1] if ":" in query.data else ""
        services = get_services(context)

        record = services.database.get_image_by_id(image_id)

        # Find replacement before deleting
        replacement = services.database.get_adjacent_image(image_id, "next")
        if replacement is None:
            replacement = services.database.get_adjacent_image(image_id, "prev")

        if replacement is None:
            await query.edit_message_caption(
                caption="Das letzte Bild kann nicht gelöscht werden. Lade zuerst ein neues Bild hoch."
            )
            return

        await query.edit_message_caption(caption=f"Wird gelöscht...")

        # Delete from database
        services.database.delete_image(image_id)

        # Delete local files
        if record:
            for file_path_str in (record.local_original_path, record.local_rendered_path):
                if file_path_str:
                    Path(file_path_str).unlink(missing_ok=True)

        rendered_path = Path(replacement.local_rendered_path) if replacement.local_rendered_path else None
        original_path = Path(replacement.local_original_path)

        if rendered_path is None or not rendered_path.exists():
            if not original_path.exists():
                await query.edit_message_caption(
                    caption=f"Bild {image_id} gelöscht. Nächstes Bild nicht verfügbar."
                )
                return
            rendered_path = services.storage.rendered_path(replacement.image_id)
            await asyncio.to_thread(
                services.renderer.render,
                original_path,
                rendered_path,
                location=replacement.location,
                taken_at=replacement.taken_at,
                caption=replacement.caption,
            )
            replacement.local_rendered_path = str(rendered_path)
            services.database.upsert_image(replacement)

        show_caption = bool(replacement.caption or replacement.location or replacement.taken_at)
        display_request = DisplayRequest(
            image_id=replacement.image_id,
            original_path=original_path,
            composed_path=rendered_path,
            location=replacement.location,
            taken_at=replacement.taken_at,
            caption=replacement.caption,
            created_at=replacement.created_at,
            uploaded_by=replacement.uploaded_by,
            show_caption=show_caption,
        )
        await asyncio.to_thread(services.display.display, display_request)
        total = services.database.count_displayed_images()
        await query.edit_message_caption(
            caption=f"Bild {image_id} gelöscht. Zeige jetzt {replacement.image_id} ({total} Bilder verbleibend)."
        )


async def delete_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    await query.edit_message_caption(caption="Löschen abgebrochen.")


async def stray_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context)
    user = update.effective_user
    if user is None or update.effective_message is None:
        return
    services.auth.sync_user(user)
    if services.auth.is_whitelisted(user.id):
        await update.effective_message.reply_text("Sende ein Foto, um einen neuen Upload zu starten, oder nutze /help.")
    else:
        await update.effective_message.reply_text(
            "Du bist für diesen Fotorahmen nicht freigegeben. Nutze /myid und teile deine ID mit einem Admin."
        )
