from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from app.auth import require_whitelist
from app.commands import get_reservation, get_services
from app.database import utcnow_iso
from app.models import DisplayError, DisplayRequest, ImageRecord, RenderError

WAITING_FOR_TEXT_CHOICE, WAITING_FOR_LOCATION, WAITING_FOR_TAKEN_AT, WAITING_FOR_CAPTION = range(4)
PENDING_SUBMISSION_KEY = "pending_submission"


@require_whitelist(conversation=True)
async def photo_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    services = get_services(context)
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None or not message.photo:
        return ConversationHandler.END

    reservation = get_reservation(context)
    if reservation.owner_user_id is not None and reservation.owner_user_id != user.id:
        await message.reply_text(
            "Ein anderes Foto wird gerade verarbeitet. Bitte warte einen Moment und sende dein Foto erneut."
        )
        return ConversationHandler.END

    if context.user_data.get(PENDING_SUBMISSION_KEY):
        await message.reply_text("Du hast bereits einen Upload in Bearbeitung. Beantworte die Fragen oder nutze /cancel.")
        return WAITING_FOR_TEXT_CHOICE

    photo = message.photo[-1]
    image_id = services.storage.generate_image_id()
    original_path = services.storage.original_path(image_id)
    reservation.owner_user_id = user.id
    reservation.image_id = image_id

    try:
        logger.info("Downloading photo %s from user %d", image_id, user.id)
        telegram_file = await photo.get_file()
        await telegram_file.download_to_drive(custom_path=str(original_path))
    except Exception as exc:  # pragma: no cover - depends on Telegram runtime
        logger.exception("Failed to download photo %s from Telegram", image_id)
        reservation.owner_user_id = None
        reservation.image_id = None
        await message.reply_text(f"Fehler beim Herunterladen des Fotos von Telegram: {exc}")
        return ConversationHandler.END

    context.user_data[PENDING_SUBMISSION_KEY] = {
        "image_id": image_id,
        "telegram_file_id": photo.file_id,
        "original_path": str(original_path),
    }
    await message.reply_text("Möchtest du Text hinzufügen (Ort, Datum, Bildunterschrift)? Antworte mit Ja/J oder Nein/N.")
    return WAITING_FOR_TEXT_CHOICE


async def receive_text_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    pending = context.user_data.get(PENDING_SUBMISSION_KEY)
    if update.effective_message is None or pending is None:
        return ConversationHandler.END
    text = (update.effective_message.text or "").strip().lower()
    if text in ("ja", "j"):
        await update.effective_message.reply_text("Wo wurde dieses Foto aufgenommen?")
        return WAITING_FOR_LOCATION
    if text in ("nein", "n"):
        return await _submit_photo(update, context, show_caption=False)
    await update.effective_message.reply_text("Bitte antworte mit Ja/J oder Nein/N, oder nutze /cancel.")
    return WAITING_FOR_TEXT_CHOICE


async def receive_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    pending = context.user_data.get(PENDING_SUBMISSION_KEY)
    if update.effective_message is None or pending is None:
        return ConversationHandler.END
    pending["location"] = (update.effective_message.text or "").strip()
    await update.effective_message.reply_text("Wann wurde es aufgenommen? Zum Beispiel: 2026-03-15 oder Sommer 2025")
    return WAITING_FOR_TAKEN_AT


async def receive_taken_at(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    pending = context.user_data.get(PENDING_SUBMISSION_KEY)
    if update.effective_message is None or pending is None:
        return ConversationHandler.END
    pending["taken_at"] = (update.effective_message.text or "").strip()
    await update.effective_message.reply_text("Welche Bildunterschrift soll unter dem Foto angezeigt werden?")
    return WAITING_FOR_CAPTION


async def receive_caption(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    pending = context.user_data.get(PENDING_SUBMISSION_KEY)
    if update.effective_message is None or pending is None:
        return ConversationHandler.END
    pending["caption"] = (update.effective_message.text or "").strip()
    return await _submit_photo(
        update,
        context,
        location=pending["location"],
        taken_at=pending["taken_at"],
        caption=pending["caption"],
        show_caption=True,
    )


async def _submit_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    location: str = "",
    taken_at: str = "",
    caption: str = "",
    show_caption: bool = True,
) -> int:
    services = get_services(context)
    user = update.effective_user
    message = update.effective_message
    pending = context.user_data.get(PENDING_SUBMISSION_KEY)
    if user is None or message is None or pending is None:
        return ConversationHandler.END

    record = ImageRecord(
        image_id=pending["image_id"],
        telegram_file_id=pending["telegram_file_id"],
        local_original_path=pending["original_path"],
        local_rendered_path=None,
        dropbox_original_path=None,
        dropbox_rendered_path=None,
        location=location,
        taken_at=taken_at,
        caption=caption,
        uploaded_by=user.id,
        created_at=utcnow_iso(),
        status="processing",
        last_error=None,
    )
    services.database.upsert_image(record)
    await message.reply_text("Dein Foto wird jetzt verarbeitet.")

    rendered_path = services.storage.rendered_path(record.image_id)
    try:
        record, warnings = await _process_image(services, record, rendered_path, show_caption=show_caption)
        services.database.upsert_image(record)
        await message.reply_text(_build_success_reply(record, warnings))
        return ConversationHandler.END
    except Exception as exc:
        logger.exception("Processing failed for image %s", record.image_id)
        record.status = "failed"
        record.last_error = str(exc)
        record.local_rendered_path = str(rendered_path) if rendered_path.exists() else None
        services.database.upsert_image(record)
        await message.reply_text(f"Verarbeitung fehlgeschlagen: {exc}")
        return ConversationHandler.END
    finally:
        reservation = get_reservation(context)
        if reservation.owner_user_id == user.id:
            reservation.owner_user_id = None
            reservation.image_id = None
        context.user_data.pop(PENDING_SUBMISSION_KEY, None)


async def _process_image(
    services: Any, record: ImageRecord, rendered_path: Path, *, show_caption: bool = True
) -> tuple[ImageRecord, list[str]]:
    warnings: list[str] = []

    logger.info("Rendering image %s", record.image_id)
    try:
        await asyncio.to_thread(
            services.renderer.render,
            Path(record.local_original_path),
            rendered_path,
            location=record.location,
            taken_at=record.taken_at,
            caption=record.caption,
        )
    except OSError as exc:
        raise RenderError(f"Failed to render image: {exc}") from exc
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
        show_caption=show_caption,
    )
    logger.info("Sending image %s to display", record.image_id)
    display_result = await asyncio.to_thread(services.display.display, display_request)
    if not display_result.success:
        logger.warning("Display failed for image %s: %s", record.image_id, display_result.message)
        record.status = "display_failed"
        record.last_error = display_result.message
        return record, warnings

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
    services.storage.cleanup_rendered_cache()
    return record, warnings


def _build_success_reply(record: ImageRecord, warnings: list[str]) -> str:
    if record.status == "display_failed":
        return f"Foto gerendert, aber die Anzeige konnte nicht aktualisiert werden: {record.last_error}"
    lines = [
        "Das Foto wurde erfolgreich an den Rahmen gesendet.",
        f"Bild-ID: {record.image_id}",
    ]
    if warnings:
        lines.append("Warnungen:")
        lines.extend(f"- {w}" for w in warnings)
    return "\n".join(lines)


def _make_unexpected_handler(state: int):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        if update.effective_message is not None:
            await update.effective_message.reply_text("Bitte beantworte die aktuelle Frage oder nutze /cancel.")
        return state

    return handler


_unexpected_text_choice = _make_unexpected_handler(WAITING_FOR_TEXT_CHOICE)
_unexpected_location = _make_unexpected_handler(WAITING_FOR_LOCATION)
_unexpected_taken_at = _make_unexpected_handler(WAITING_FOR_TAKEN_AT)
_unexpected_caption = _make_unexpected_handler(WAITING_FOR_CAPTION)


async def _conversation_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user if update else None
    reservation = get_reservation(context)
    if user and reservation.owner_user_id == user.id:
        reservation.owner_user_id = None
        reservation.image_id = None
    if context.user_data:
        context.user_data.pop(PENDING_SUBMISSION_KEY, None)
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "Dein Upload ist nach 5 Minuten Inaktivität abgelaufen. "
            "Sende das Foto erneut, um neu zu starten."
        )
    return ConversationHandler.END


def build_photo_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[MessageHandler(filters.PHOTO & ~filters.COMMAND, photo_entry)],
        states={
            WAITING_FOR_TEXT_CHOICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text_choice),
                MessageHandler(filters.ALL, _unexpected_text_choice),
            ],
            WAITING_FOR_LOCATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_location),
                MessageHandler(filters.ALL, _unexpected_location),
            ],
            WAITING_FOR_TAKEN_AT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_taken_at),
                MessageHandler(filters.ALL, _unexpected_taken_at),
            ],
            WAITING_FOR_CAPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_caption),
                MessageHandler(filters.ALL, _unexpected_caption),
            ],
            ConversationHandler.TIMEOUT: [
                MessageHandler(filters.ALL, _conversation_timeout),
            ],
        },
        fallbacks=[CommandHandler("cancel", unexpected_cancel)],
        allow_reentry=False,
        name="photo_upload",
        persistent=False,
        conversation_timeout=300,
    )


async def unexpected_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from app.commands import cancel_command

    return await cancel_command(update, context)
