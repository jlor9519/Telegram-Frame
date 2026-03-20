from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from app.auth import require_admin, require_whitelist
from app.models import AppServices, ProcessingReservation


def get_services(context: ContextTypes.DEFAULT_TYPE) -> AppServices:
    return context.application.bot_data["services"]


def get_reservation(context: ContextTypes.DEFAULT_TYPE) -> ProcessingReservation:
    return context.application.bot_data["processing_reservation"]


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
                "/settings - Anzeigeeinstellungen anzeigen/ändern",
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
    services = get_services(context)
    result = await asyncio.to_thread(services.display.refresh_only)
    await update.effective_message.reply_text(
        "Aktualisierung ausgelöst." if result.success else f"Aktualisierung fehlgeschlagen: {result.message}"
    )


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
