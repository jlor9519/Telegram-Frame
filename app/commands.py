from __future__ import annotations

import asyncio
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from app.models import AppServices, DisplayRequest, ProcessingReservation


def get_services(context: ContextTypes.DEFAULT_TYPE) -> AppServices:
    return context.application.bot_data["services"]


def get_reservation(context: ContextTypes.DEFAULT_TYPE) -> ProcessingReservation:
    return context.application.bot_data["processing_reservation"]


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context)
    user = update.effective_user
    if user is None or update.effective_message is None:
        return
    services.auth.sync_user(user)
    if not services.auth.is_whitelisted(user.id):
        await update.effective_message.reply_text(
            "You are not whitelisted for this photo frame yet. Ask an admin to add your Telegram user ID."
        )
        return

    await update.effective_message.reply_text(
        "\n".join(
            [
                "Send a photo to start the upload flow.",
                "I will ask for:",
                "- where the photo was taken",
                "- when it was taken",
                "- what caption should appear on the display",
                "",
                "Commands:",
                "/help - show this message",
                "/status - show health summary",
                "/myid - show your Telegram numeric user ID",
                "/latest - redisplay the latest successful image",
                "/refresh - trigger an InkyPi refresh using the current bridge payload",
                "/cancel - cancel the active upload flow",
            ]
        )
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context)
    user = update.effective_user
    if user is None or update.effective_message is None:
        return
    services.auth.sync_user(user)
    if not services.auth.is_whitelisted(user.id):
        await update.effective_message.reply_text("You are not authorized to use this bot.")
        return

    latest = services.database.get_latest_image()
    reservation = get_reservation(context)
    latest_summary = "none yet"
    if latest:
        latest_summary = f"{latest.image_id} ({latest.status})"

    active_owner = reservation.owner_user_id if reservation.owner_user_id is not None else "idle"
    await update.effective_message.reply_text(
        "\n".join(
            [
                "Photo frame status",
                f"- database: {'ok' if services.database.healthcheck() else 'error'}",
                f"- whitelisted users: {services.database.count_whitelisted_users()}",
                f"- dropbox: {services.dropbox.health_summary()}",
                f"- latest image: {latest_summary}",
                f"- current reservation: {active_owner}",
                f"- payload file: {services.config.storage.current_payload_path}",
                f"- refresh command: {services.config.inkypi.refresh_command}",
            ]
        )
    )


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.effective_message is None:
        return
    await update.effective_message.reply_text(f"Your Telegram user ID is: {user.id}")


async def whitelist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context)
    user = update.effective_user
    if user is None or update.effective_message is None:
        return
    services.auth.sync_user(user)
    if not services.auth.is_admin(user.id):
        await update.effective_message.reply_text("Only admin users can whitelist other Telegram users.")
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /whitelist <telegram_user_id>")
        return

    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("The user ID must be numeric, for example: /whitelist 123456789")
        return

    services.auth.whitelist_user(target_user_id)
    await update.effective_message.reply_text(f"User {target_user_id} is now whitelisted.")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if user is None or update.effective_message is None:
        return ConversationHandler.END

    reservation = get_reservation(context)
    if reservation.owner_user_id == user.id:
        reservation.owner_user_id = None
        reservation.image_id = None
    context.user_data.clear()
    await update.effective_message.reply_text("Cancelled the current upload flow.")
    return ConversationHandler.END


async def latest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context)
    user = update.effective_user
    if user is None or update.effective_message is None:
        return
    services.auth.sync_user(user)
    if not services.auth.is_whitelisted(user.id):
        await update.effective_message.reply_text("You are not authorized to use this bot.")
        return

    latest = services.database.get_latest_image()
    if latest is None or not latest.local_rendered_path:
        await update.effective_message.reply_text("There is no rendered image available yet.")
        return

    request = DisplayRequest(
        image_id=latest.image_id,
        original_path=Path(latest.local_original_path),
        composed_path=Path(latest.local_rendered_path),
        location=latest.location,
        taken_at=latest.taken_at,
        caption=latest.caption,
        created_at=latest.created_at,
        uploaded_by=latest.uploaded_by,
    )
    result = await asyncio.to_thread(services.display.display, request)
    await update.effective_message.reply_text(
        "Redisplay succeeded." if result.success else f"Redisplay failed: {result.message}"
    )


async def refresh_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context)
    user = update.effective_user
    if user is None or update.effective_message is None:
        return
    services.auth.sync_user(user)
    if not services.auth.is_whitelisted(user.id):
        await update.effective_message.reply_text("You are not authorized to use this bot.")
        return

    result = await asyncio.to_thread(services.display.refresh_current)
    await update.effective_message.reply_text(
        "Refresh triggered." if result.success else f"Refresh failed: {result.message}"
    )


async def stray_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context)
    user = update.effective_user
    if user is None or update.effective_message is None:
        return
    services.auth.sync_user(user)
    if services.auth.is_whitelisted(user.id):
        await update.effective_message.reply_text("Send a photo to start a new upload, or use /help.")
    else:
        await update.effective_message.reply_text(
            "You are not whitelisted for this photo frame. Use /myid and share that ID with an admin."
        )

