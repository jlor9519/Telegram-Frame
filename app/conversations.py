from __future__ import annotations

import asyncio
from pathlib import Path

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from app.commands import get_reservation, get_services
from app.database import utcnow_iso
from app.models import DisplayRequest, ImageRecord

WAITING_FOR_LOCATION, WAITING_FOR_TAKEN_AT, WAITING_FOR_CAPTION = range(3)
PENDING_SUBMISSION_KEY = "pending_submission"


async def photo_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    services = get_services(context)
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None or not message.photo:
        return ConversationHandler.END

    services.auth.sync_user(user)
    if not services.auth.is_whitelisted(user.id):
        await message.reply_text("You are not authorized to submit photos to this frame.")
        return ConversationHandler.END

    reservation = get_reservation(context)
    if reservation.owner_user_id is not None and reservation.owner_user_id != user.id:
        await message.reply_text(
            "Another photo is currently being processed. Please wait a moment and send yours again."
        )
        return ConversationHandler.END

    if context.user_data.get(PENDING_SUBMISSION_KEY):
        await message.reply_text("You already have an upload in progress. Reply to the prompts or use /cancel.")
        return WAITING_FOR_LOCATION

    photo = message.photo[-1]
    image_id = services.storage.generate_image_id()
    original_path = services.storage.original_path(image_id)
    reservation.owner_user_id = user.id
    reservation.image_id = image_id

    try:
        telegram_file = await photo.get_file()
        await telegram_file.download_to_drive(custom_path=str(original_path))
    except Exception as exc:  # pragma: no cover - depends on Telegram runtime
        reservation.owner_user_id = None
        reservation.image_id = None
        await message.reply_text(f"Failed to download the photo from Telegram: {exc}")
        return ConversationHandler.END

    context.user_data[PENDING_SUBMISSION_KEY] = {
        "image_id": image_id,
        "telegram_file_id": photo.file_id,
        "original_path": str(original_path),
    }
    await message.reply_text("Where was this photo taken?")
    return WAITING_FOR_LOCATION


async def receive_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    pending = context.user_data.get(PENDING_SUBMISSION_KEY)
    if update.effective_message is None or pending is None:
        return ConversationHandler.END
    pending["location"] = (update.effective_message.text or "").strip()
    await update.effective_message.reply_text("When was it taken? For example: 2026-03-15 or Summer 2025")
    return WAITING_FOR_TAKEN_AT


async def receive_taken_at(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    pending = context.user_data.get(PENDING_SUBMISSION_KEY)
    if update.effective_message is None or pending is None:
        return ConversationHandler.END
    pending["taken_at"] = (update.effective_message.text or "").strip()
    await update.effective_message.reply_text("What caption should be shown under the photo?")
    return WAITING_FOR_CAPTION


async def receive_caption(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    services = get_services(context)
    user = update.effective_user
    message = update.effective_message
    pending = context.user_data.get(PENDING_SUBMISSION_KEY)
    if user is None or message is None or pending is None:
        return ConversationHandler.END

    pending["caption"] = (message.text or "").strip()
    created_at = utcnow_iso()
    record = ImageRecord(
        image_id=pending["image_id"],
        telegram_file_id=pending["telegram_file_id"],
        local_original_path=pending["original_path"],
        local_rendered_path=None,
        dropbox_original_path=None,
        dropbox_rendered_path=None,
        location=pending["location"],
        taken_at=pending["taken_at"],
        caption=pending["caption"],
        uploaded_by=user.id,
        created_at=created_at,
        status="processing",
        last_error=None,
    )
    services.database.upsert_image(record)
    await message.reply_text("Processing your photo now.")

    warnings: list[str] = []
    rendered_path = services.storage.rendered_path(record.image_id)
    try:
        await asyncio.to_thread(
            services.renderer.render,
            Path(record.local_original_path),
            rendered_path,
            location=record.location,
            taken_at=record.taken_at,
            caption=record.caption,
        )
        record.local_rendered_path = str(rendered_path)

        if services.dropbox.enabled:
            try:
                record.dropbox_original_path = await asyncio.to_thread(
                    services.dropbox.upload_original,
                    Path(record.local_original_path),
                )
            except Exception as exc:  # pragma: no cover - network/runtime dependent
                warnings.append(f"Dropbox original upload failed: {exc}")

        display_request = DisplayRequest(
            image_id=record.image_id,
            original_path=Path(record.local_original_path),
            composed_path=rendered_path,
            location=record.location,
            taken_at=record.taken_at,
            caption=record.caption,
            created_at=record.created_at,
            uploaded_by=record.uploaded_by,
        )
        display_result = await asyncio.to_thread(services.display.display, display_request)
        if not display_result.success:
            record.status = "display_failed"
            record.last_error = display_result.message
            services.database.upsert_image(record)
            await message.reply_text(f"Photo rendered, but display refresh failed: {display_result.message}")
            return ConversationHandler.END

        if services.dropbox.enabled and services.config.dropbox.upload_rendered:
            try:
                record.dropbox_rendered_path = await asyncio.to_thread(
                    services.dropbox.upload_rendered,
                    rendered_path,
                )
            except Exception as exc:  # pragma: no cover - network/runtime dependent
                warnings.append(f"Dropbox rendered upload failed: {exc}")

        record.status = "displayed_with_warnings" if warnings else "displayed"
        record.last_error = " | ".join(warnings) if warnings else None
        services.database.upsert_image(record)
        services.storage.cleanup_rendered_cache()

        success_lines = [
            "The photo was sent to the frame successfully.",
            f"Image ID: {record.image_id}",
        ]
        if warnings:
            success_lines.append("Warnings:")
            success_lines.extend(f"- {warning}" for warning in warnings)
        await message.reply_text("\n".join(success_lines))
        return ConversationHandler.END
    except Exception as exc:
        record.status = "failed"
        record.last_error = str(exc)
        record.local_rendered_path = str(rendered_path) if rendered_path.exists() else None
        services.database.upsert_image(record)
        await message.reply_text(f"Processing failed: {exc}")
        return ConversationHandler.END
    finally:
        reservation = get_reservation(context)
        if reservation.owner_user_id == user.id:
            reservation.owner_user_id = None
            reservation.image_id = None
        context.user_data.pop(PENDING_SUBMISSION_KEY, None)


async def unexpected_location_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_message is not None:
        await update.effective_message.reply_text("Please answer the current question, or use /cancel.")
    return WAITING_FOR_LOCATION


async def unexpected_taken_at_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_message is not None:
        await update.effective_message.reply_text("Please answer the current question, or use /cancel.")
    return WAITING_FOR_TAKEN_AT


async def unexpected_caption_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_message is not None:
        await update.effective_message.reply_text("Please answer the current question, or use /cancel.")
    return WAITING_FOR_CAPTION


def build_photo_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[MessageHandler(filters.PHOTO & ~filters.COMMAND, photo_entry)],
        states={
            WAITING_FOR_LOCATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_location),
                MessageHandler(filters.ALL, unexpected_location_input),
            ],
            WAITING_FOR_TAKEN_AT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_taken_at),
                MessageHandler(filters.ALL, unexpected_taken_at_input),
            ],
            WAITING_FOR_CAPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_caption),
                MessageHandler(filters.ALL, unexpected_caption_input),
            ],
        },
        fallbacks=[CommandHandler("cancel", unexpected_cancel)],
        allow_reentry=False,
        name="photo_upload",
        persistent=False,
    )


async def unexpected_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from app.commands import cancel_command

    return await cancel_command(update, context)
