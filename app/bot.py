from __future__ import annotations

from telegram.ext import Application, ApplicationBuilder, CommandHandler, MessageHandler, filters

from app.commands import (
    cancel_command,
    delete_command,
    help_command,
    myid_command,
    next_command,
    prev_command,
    refresh_command,
    status_command,
    stray_text_handler,
    whitelist_command,
)
from app.conversations import build_photo_conversation
from app.settings_conversation import build_settings_conversation
from app.models import AppServices, ProcessingReservation


def build_application(services: AppServices) -> Application:
    application = ApplicationBuilder().token(services.config.telegram.bot_token).build()
    application.bot_data["services"] = services
    application.bot_data["processing_reservation"] = ProcessingReservation()

    application.add_handler(build_photo_conversation())
    application.add_handler(build_settings_conversation())
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("myid", myid_command))
    application.add_handler(CommandHandler("whitelist", whitelist_command))
    application.add_handler(CommandHandler("next", next_command))
    application.add_handler(CommandHandler("prev", prev_command))
    application.add_handler(CommandHandler("delete", delete_command))
    application.add_handler(CommandHandler("refresh", refresh_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, stray_text_handler))
    return application

