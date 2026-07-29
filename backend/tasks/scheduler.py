"""APScheduler setup — replaces Celery Beat for periodic tasks.

No Redis or external broker required.
The scheduler is started/stopped inside the FastAPI lifespan context.
"""
from __future__ import annotations

from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from loguru import logger

# Module-level singleton created on first call to get_scheduler()
_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler  # noqa: PLW0603
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="Asia/Taipei")
    return _scheduler


def setup_jobs(scheduler: AsyncIOScheduler) -> None:
    """Register all periodic jobs on the scheduler.

    Called once during FastAPI lifespan startup, before scheduler.start().
    """
    from backend.tasks.processing import send_daily_digest

    # Daily digest at 08:00 Asia/Taipei
    scheduler.add_job(
        send_daily_digest,
        trigger=CronTrigger(hour=8, minute=0, timezone="Asia/Taipei"),
        id="daily_digest",
        name="Daily knowledge digest",
        replace_existing=True,
        misfire_grace_time=3600,  # run if missed within 1 hour
    )
    logger.info("Scheduled: daily digest at 08:00 Asia/Taipei")


def schedule_todo_reminder(scheduler: AsyncIOScheduler, reminder_id: str, remind_at: datetime) -> None:
    """Add (or replace) a one-off job for a single TodoReminder row.

    A todo can now have several reminders (start/midpoint/due), each with its
    own row and its own job — the job id keys off *reminder_id*, not the
    parent todo, so scheduling one doesn't clobber another. If *remind_at*
    has already passed (e.g. the app was down when it was due), it fires
    ASAP instead of never — a reminder late is better than one silently
    dropped. ``replace_existing=True`` means re-scheduling the same reminder
    (e.g. after a restart) never double-fires.
    """
    from backend.tasks.processing import send_todo_reminder

    now = datetime.now(timezone.utc)
    run_date = remind_at if remind_at > now else now
    scheduler.add_job(
        send_todo_reminder,
        trigger=DateTrigger(run_date=run_date),
        id=f"todo_reminder_{reminder_id}",
        args=[reminder_id],
        replace_existing=True,
        misfire_grace_time=3600,
    )


async def _reschedule_pending_todo_reminders(scheduler: AsyncIOScheduler) -> None:
    """Re-register reminder jobs lost on restart (MemoryJobStore doesn't persist)."""
    from backend.knowledge import crud
    from backend.knowledge.db import async_session_maker

    async with async_session_maker() as db:
        reminders = await crud.list_pending_todo_reminders(db)

    for reminder in reminders:
        schedule_todo_reminder(scheduler, str(reminder.id), reminder.remind_at)
    if reminders:
        logger.info("Rescheduled {} pending todo reminder(s) after restart.", len(reminders))


async def start_scheduler() -> AsyncIOScheduler:
    """Configure and start the scheduler. Returns the running scheduler."""
    from backend.tasks.processing import send_daily_digest

    scheduler = get_scheduler()
    setup_jobs(scheduler)
    await _reschedule_pending_todo_reminders(scheduler)
    scheduler.start()
    logger.info("APScheduler started ({} jobs).", len(scheduler.get_jobs()))

    # Catch up on the daily digest if this machine wasn't running at 08:00 —
    # the cron trigger above only fires at that exact wall-clock moment.
    # send_daily_digest() itself guards on "already sent today" so this is
    # a safe no-op on days the cron already handled it.
    await send_daily_digest()
    return scheduler


async def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped.")
