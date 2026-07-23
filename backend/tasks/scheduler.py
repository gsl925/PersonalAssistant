"""APScheduler setup — replaces Celery Beat for periodic tasks.

No Redis or external broker required.
The scheduler is started/stopped inside the FastAPI lifespan context.
"""
from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
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


async def start_scheduler() -> AsyncIOScheduler:
    """Configure and start the scheduler. Returns the running scheduler."""
    scheduler = get_scheduler()
    setup_jobs(scheduler)
    scheduler.start()
    logger.info("APScheduler started ({} jobs).", len(scheduler.get_jobs()))
    return scheduler


async def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped.")
