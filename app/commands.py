from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from app.auth import require_admin, require_whitelist
from app.database import utcnow_iso
from app.models import AppServices, DisplayRequest, DisplayResult, ImageRecord, ProcessingReservation


def get_services(context: ContextTypes.DEFAULT_TYPE) -> AppServices:
    return context.application.bot_data["services"]


def get_reservation(context: ContextTypes.DEFAULT_TYPE) -> ProcessingReservation:
    return context.application.bot_data["processing_reservation"]


def get_display_lock(context: ContextTypes.DEFAULT_TYPE) -> asyncio.Lock:
    return context.application.bot_data["display_lock"]


async def sync_display_payload_to_dropbox(services: AppServices) -> tuple[bool, str | None]:
    if not services.dropbox.enabled:
        if services.config.uses_remote_display_transport():
            return False, "Dropbox ist für den Remote-Transport nicht konfiguriert."
        return True, None

    uploaded = await asyncio.to_thread(
        services.dropbox.upload_display_payload,
        services.config.storage.current_payload_path,
        services.config.storage.current_image_path,
    )
    if uploaded:
        return True, None

    detail = services.dropbox.last_error or "unbekannter Dropbox-Fehler"
    if services.config.uses_remote_display_transport():
        return False, f"Dropbox-Synchronisierung zum Display-Pi fehlgeschlagen: {detail}"
    return True, f"Dropbox-Warnung: {detail}"


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
                "/list - nächste Bilder und Zeitplan anzeigen",
                "/delete - aktuelles Bild löschen",
                "/refresh - aktuelles Bild neu laden",
                "/settings - Anzeigeeinstellungen anzeigen/ändern (nur Admins)",
                "/restore - Bilder von Dropbox wiederherstellen (nur Admins)",
                "/users - freigegebene Nutzer anzeigen (nur Admins)",
                "/unwhitelist - Nutzer entfernen (nur Admins)",
                "/status - Systemstatus anzeigen",
                "/myid - deine Telegram-Nutzer-ID anzeigen",
                "/cancel - den laufenden Upload abbrechen",
            ]
        )
    )


def _format_duration(since_iso: str | None) -> str:
    if not since_iso:
        return "unbekannt"
    from datetime import datetime, timezone
    try:
        since = datetime.fromisoformat(since_iso)
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - since
        total_seconds = max(0, int(delta.total_seconds()))
        minutes = total_seconds // 60
        hours = minutes // 60
        days = hours // 24
        if days >= 1:
            return f"seit {days} {'Tag' if days == 1 else 'Tagen'}"
        if hours >= 1:
            remaining_minutes = minutes % 60
            if remaining_minutes:
                return f"seit {hours} Std. {remaining_minutes} Min."
            return f"seit {hours} {'Stunde' if hours == 1 else 'Stunden'}"
        if minutes >= 1:
            return f"seit {minutes} {'Minute' if minutes == 1 else 'Minuten'}"
        return "seit weniger als einer Minute"
    except (ValueError, TypeError):
        return "unbekannt"


@require_whitelist
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context)

    db_ok = services.database.healthcheck()
    storage_ok = services.storage.healthcheck()
    payload_ok = services.display.payload_exists()

    if services.config.uses_remote_display_transport():
        inkypi_line = "– via Dropbox"
    else:
        inkypi_reachable = await asyncio.to_thread(services.display.ping_inkypi)
        if inkypi_reachable is None:
            inkypi_line = "– lokal"
        elif inkypi_reachable:
            inkypi_line = "✓ erreichbar"
        else:
            inkypi_line = "✗ nicht erreichbar"

    dropbox_status = await asyncio.to_thread(services.dropbox.health_summary)
    if dropbox_status == "disabled":
        dropbox_line = "✗ deaktiviert"
    elif dropbox_status == "not_configured":
        dropbox_line = "✗ nicht konfiguriert"
    elif dropbox_status == "connected":
        dropbox_line = "✓ verbunden"
    else:
        dropbox_line = "✗ Auth fehlgeschlagen"

    image_count = services.database.count_displayed_images()
    displayed_at = services.database.get_setting("current_image_displayed_at")
    user_count = services.database.count_whitelisted_users()

    await update.effective_message.reply_text(
        "\n".join(
            [
                "Fotorahmen-Status",
                "",
                "Dienste:",
                f"- Datenbank: {'✓ ok' if db_ok else '✗ Fehler'}",
                f"- Speicher: {'✓ ok' if storage_ok else '✗ Fehler'}",
                f"- InkyPi: {inkypi_line}",
                f"- InkyPi-Payload: {'✓ vorhanden' if payload_ok else '✗ nicht gefunden'}",
                f"- Dropbox: {dropbox_line}",
                "",
                "Bilder:",
                f"- In Rotation: {image_count} {'Bild' if image_count == 1 else 'Bilder'}",
                f"- Aktuelles Bild: {_format_duration(displayed_at)}",
                "",
                "Nutzer:",
                f"- Freigegebene Nutzer: {user_count}",
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

    pending = context.user_data.get("pending_submission")
    if isinstance(pending, dict):
        original_path = pending.get("original_path")
        if original_path:
            Path(original_path).unlink(missing_ok=True)

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
        success_text = "Aktualisierung ausgelöst."
        if result.success:
            payload_ok, payload_message = await sync_display_payload_to_dropbox(services)
            if not payload_ok:
                result = DisplayResult(False, payload_message or "Dropbox-Synchronisierung fehlgeschlagen.")
            else:
                if services.config.uses_remote_display_transport():
                    success_text = "Aktualisierung an den Display-Pi via Dropbox übertragen."
        await update.effective_message.reply_text(
            success_text if result.success else _friendly_display_error(result.message)
        )


def _friendly_display_error(message: str) -> str:
    lower = message.lower()
    if "dropbox" in lower:
        return message
    if any(p in lower for p in (
        "request failed", "timed out", "connection refused",
        "no route to host", "network is unreachable",
    )):
        return "Display nicht erreichbar. Bitte prüfe die Verbindung zum Pi."
    return f"Anzeige fehlgeschlagen: {message}"


def _format_interval(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} Sekunden"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} {'Minute' if minutes == 1 else 'Minuten'}"
    hours = minutes // 60
    rem_min = minutes % 60
    if hours < 24:
        if rem_min:
            return f"{hours} Std. {rem_min} Min."
        return f"{hours} {'Stunde' if hours == 1 else 'Stunden'}"
    days = hours // 24
    rem_hours = hours % 24
    if rem_hours:
        return f"{days} {'Tag' if days == 1 else 'Tage'} {rem_hours} Std."
    return f"{days} {'Tag' if days == 1 else 'Tage'}"


@require_whitelist
async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    services = get_services(context)

    payload_path = services.config.storage.current_payload_path
    if not payload_path.exists():
        await message.reply_text("Noch kein Bild vorhanden.")
        return

    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        await message.reply_text("Payload-Datei konnte nicht gelesen werden.")
        return

    current_image_id = payload.get("image_id")
    if not current_image_id:
        await message.reply_text("Kein aktuelles Bild erkannt.")
        return

    next_images = services.database.get_next_images(current_image_id, 5)
    total = services.database.count_displayed_images()
    current_pos = services.database.get_displayed_image_position(current_image_id)

    def _image_label(record: ImageRecord) -> str:
        parts = []
        if record.caption:
            parts.append(f'"{record.caption}"')
        if record.location:
            parts.append(record.location)
        if record.taken_at:
            parts.append(record.taken_at)
        return " • ".join(parts) if parts else "(kein Text)"

    lines = [f"Bilderliste ({total} gesamt)", ""]

    current_record = services.database.get_image_by_id(current_image_id)
    current_label = _image_label(current_record) if current_record else "(unbekannt)"
    lines.append(f"{current_label}")

    if services.config.uses_remote_display_transport():
        lines.append("  Zeitplan auf dem Server Pi nicht verfügbar (Remote-Display via Dropbox).")
    else:
        interval = await asyncio.to_thread(services.display.get_slideshow_interval)
        displayed_at = services.database.get_setting("current_image_displayed_at")

        # Time remaining for current image
        from datetime import datetime, timezone as tz
        from app.slideshow import _is_in_sleep_window, _seconds_until_wake_up
        now = datetime.now(tz.utc)
        elapsed = 0
        if displayed_at:
            try:
                since = datetime.fromisoformat(displayed_at)
                if since.tzinfo is None:
                    since = since.replace(tzinfo=tz.utc)
                elapsed = max(0, int((now - since).total_seconds()))
            except (ValueError, TypeError):
                elapsed = 0
        remaining = max(0, interval - elapsed)

        sleep_schedule = await asyncio.to_thread(services.display.get_sleep_schedule)
        in_sleep = bool(sleep_schedule and _is_in_sleep_window(sleep_schedule))
        if in_sleep:
            remaining = _seconds_until_wake_up(sleep_schedule)

        remaining_str = _format_interval(remaining) if remaining > 0 else "weniger als 1 Minute"
        lines.append(f"  Wechsel in ca. {remaining_str}")

    if next_images:
        lines.append("")
        lines.append("Nächste Bilder:")
        for i, record in enumerate(next_images, 1):
            pos = ((current_pos or 0) + i - 1) % total + 1
            lines.append(f"{i}. [{pos}/{total}] {_image_label(record)}")
            if not services.config.uses_remote_display_transport():
                offset = remaining + (i - 1) * interval
                eta_str = _format_interval(offset) if offset > 0 else "weniger als 1 Minute"
                lines.append(f"   In ca. {eta_str}")

    await message.reply_text("\n".join(lines))


async def _display_target(services: AppServices, target: ImageRecord) -> DisplayResult:
    """Render, display, and upload a target image. Caller must hold display_lock."""
    rendered_path = Path(target.local_rendered_path) if target.local_rendered_path else None
    original_path = Path(target.local_original_path)

    if rendered_path is None or not rendered_path.exists():
        if not original_path.exists():
            if target.dropbox_original_path and services.dropbox.enabled:
                downloaded = await asyncio.to_thread(
                    services.dropbox.download_file,
                    target.dropbox_original_path,
                    original_path,
                )
                if not downloaded:
                    return DisplayResult(False, f"Download von {target.image_id} fehlgeschlagen.")
            else:
                return DisplayResult(False, f"Bilddatei für {target.image_id} nicht mehr vorhanden.")
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
    fit_mode = services.database.get_setting("image_fit_mode") or "fill"
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
        fit_mode=fit_mode,
    )

    result = await asyncio.to_thread(services.display.display, display_request)
    if not result.success:
        return result

    payload_ok, payload_message = await sync_display_payload_to_dropbox(services)
    if not payload_ok:
        return DisplayResult(False, payload_message or "Dropbox-Synchronisierung fehlgeschlagen.")
    if payload_message:
        logger.warning(payload_message)

    return result


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

    result = await _display_target(services, target)

    total = services.database.count_displayed_images()
    position = services.database.get_displayed_image_position(target.image_id)
    if result.success:
        services.database.set_setting("current_image_displayed_at", utcnow_iso())
        await message.reply_text(f"Bild {position} von {total}: {target.image_id}")
        from app.slideshow import reschedule_slideshow_job
        reschedule_slideshow_job(context.application)
    else:
        await message.reply_text(_friendly_display_error(result.message))


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

        # Delete from Dropbox
        if record and services.dropbox.enabled:
            for remote_path in (record.dropbox_original_path, record.dropbox_rendered_path):
                if remote_path:
                    await asyncio.to_thread(services.dropbox.delete_file, remote_path)

        result = await _display_target(services, replacement)

        total = services.database.count_displayed_images()
        if result.success:
            services.database.set_setting("current_image_displayed_at", utcnow_iso())
            await query.edit_message_caption(
                caption=f"Bild {image_id} gelöscht. Zeige jetzt {replacement.image_id} ({total} Bilder verbleibend)."
            )
            from app.slideshow import reschedule_slideshow_job
            reschedule_slideshow_job(context.application)
        else:
            await query.edit_message_caption(
                caption=f"Bild {image_id} gelöscht. {_friendly_display_error(result.message)}"
            )


async def delete_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    await query.edit_message_caption(caption="Löschen abgebrochen.")


@require_admin
async def restore_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    services = get_services(context)
    if not services.dropbox.enabled:
        await message.reply_text("Dropbox ist nicht aktiviert. Wiederherstellung nicht möglich.")
        return
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Ja, wiederherstellen", callback_data="restore_confirm"),
            InlineKeyboardButton("Abbrechen", callback_data="restore_cancel"),
        ],
    ])
    await message.reply_text(
        "Sollen alle fehlenden Bilder von Dropbox wiederhergestellt werden?\n\n"
        "Dies kann je nach Anzahl der Bilder einige Minuten dauern.",
        reply_markup=keyboard,
    )


async def restore_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    await query.edit_message_text("Wiederherstellung läuft…")

    services = get_services(context)
    db_path = services.config.database.path

    # If the database has no images, try to restore the DB backup first
    total_db = services.database.count_displayed_images()
    if total_db == 0:
        restored_db = await asyncio.to_thread(services.dropbox.restore_database, db_path)
        if restored_db:
            await query.edit_message_text(
                "Datenbank wurde von Dropbox wiederhergestellt.\n"
                "Bitte starte den Bot neu, damit die Wiederherstellung wirksam wird."
            )
            return
        else:
            await query.edit_message_text(
                "Keine Datenbank-Sicherung in Dropbox gefunden. "
                "Es gibt keine Bilder zum Wiederherstellen."
            )
            return

    records = services.database.get_all_images_ordered()
    missing = [
        r for r in records
        if r.dropbox_original_path and not Path(r.local_original_path).exists()
    ]

    if not missing:
        await query.edit_message_text("Alle Bilder sind bereits lokal vorhanden. Nichts zu tun.")
        return

    restored = 0
    failed = 0
    for record in missing:
        local_path = Path(record.local_original_path)
        success = await asyncio.to_thread(
            services.dropbox.download_file,
            record.dropbox_original_path,
            local_path,
        )
        if success:
            restored += 1
        else:
            failed += 1

    parts = [f"{restored} von {len(missing)} Bildern wiederhergestellt."]
    if failed:
        parts.append(f"{failed} Download(s) fehlgeschlagen.")
    await query.edit_message_text(" ".join(parts))


async def restore_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    await query.edit_message_text("Wiederherstellung abgebrochen.")


@require_admin
async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    services = get_services(context)
    users = services.database.get_whitelisted_users()
    if not users:
        await message.reply_text("Keine freigegebenen Nutzer.")
        return
    lines = [f"Freigegebene Nutzer ({len(users)}):"]
    for u in users:
        user_id = u["telegram_user_id"]
        name = u.get("display_name") or (f"@{u['username']}" if u.get("username") else str(user_id))
        admin_marker = " (Admin)" if u.get("is_admin") else ""
        lines.append(f"- {user_id} {name}{admin_marker}")
    await message.reply_text("\n".join(lines))


@require_admin
async def unwhitelist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    if not context.args:
        await message.reply_text("Verwendung: /unwhitelist <telegram_user_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await message.reply_text("Die Nutzer-ID muss numerisch sein, z.B.: /unwhitelist 123456789")
        return
    if target_id == user.id:
        await message.reply_text("Du kannst dich nicht selbst entfernen.")
        return
    services = get_services(context)
    removed = services.database.remove_whitelist(target_id)
    if removed:
        logger.info("User %d removed from whitelist by admin %d", target_id, user.id)
        await message.reply_text(f"Nutzer {target_id} wurde entfernt.")
    else:
        await message.reply_text(f"Nutzer {target_id} nicht gefunden.")


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
