from __future__ import annotations

import json
import logging
from datetime import datetime, time as dt_time

from telegram.ext import Application

from app.commands import _display_target
from app.database import utcnow_iso

logger = logging.getLogger(__name__)

JOB_NAME = "slideshow_advance"


def schedule_slideshow_job(application: Application) -> None:
    """Schedule the slideshow auto-advance job. Called once on startup."""
    services = application.bot_data["services"]
    interval = services.display.get_slideshow_interval()
    application.job_queue.run_repeating(
        _advance_slideshow,
        interval=interval,
        first=interval,
        name=JOB_NAME,
    )
    logger.info("Slideshow job scheduled with interval %ds", interval)


def reschedule_slideshow_job(application: Application, interval_seconds: int | None = None) -> None:
    """Remove and re-schedule the slideshow job. Resets the timer."""
    jobs = application.job_queue.get_jobs_by_name(JOB_NAME)
    for job in jobs:
        job.schedule_removal()

    if interval_seconds is None:
        services = application.bot_data["services"]
        interval_seconds = services.display.get_slideshow_interval()

    application.job_queue.run_repeating(
        _advance_slideshow,
        interval=interval_seconds,
        first=interval_seconds,
        name=JOB_NAME,
    )
    logger.info("Slideshow job rescheduled with interval %ds", interval_seconds)


def _is_in_sleep_window(schedule: tuple[str, str]) -> bool:
    """Check if current local time falls inside the sleep window."""
    sleep_start_str, wake_up_str = schedule
    try:
        sh, sm = sleep_start_str.split(":")
        wh, wm = wake_up_str.split(":")
        sleep_start = dt_time(int(sh), int(sm))
        wake_up = dt_time(int(wh), int(wm))
    except (ValueError, AttributeError):
        return False

    now = datetime.now().time()

    if sleep_start > wake_up:
        # Overnight window, e.g. 22:00-08:00
        return now >= sleep_start or now < wake_up
    else:
        # Same-day window, e.g. 13:00-15:00
        return sleep_start <= now < wake_up


async def _advance_slideshow(context) -> None:
    """Auto-advance to the next image. Called by JobQueue."""
    services = context.application.bot_data["services"]
    lock = context.application.bot_data["display_lock"]

    # Check sleep schedule
    schedule = services.display.get_sleep_schedule()
    if schedule and _is_in_sleep_window(schedule):
        logger.info("Skipping auto-advance — sleep schedule active")
        return

    # Skip if display is busy (non-blocking check)
    if lock.locked():
        logger.info("Skipping auto-advance — display is busy")
        return

    async with lock:
        payload_path = services.config.storage.current_payload_path
        if not payload_path.exists():
            return

        try:
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Auto-advance: could not read payload")
            return

        current_image_id = payload.get("image_id")
        if not current_image_id:
            return

        target = services.database.get_adjacent_image(current_image_id, "next")
        if target is None:
            logger.debug("Auto-advance: no next image (only 1 in rotation?)")
            return

        result = await _display_target(services, target)

        if result.success:
            services.database.set_setting("current_image_displayed_at", utcnow_iso())
            logger.info("Auto-advanced to image %s", target.image_id)
        else:
            logger.warning("Auto-advance failed: %s", result.message)
