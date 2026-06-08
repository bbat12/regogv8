"""
Scan Scheduler — runs recurring scans using APScheduler.
Prints new HOT leads to terminal on launch.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# APScheduler is optional for V1
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False
    BackgroundScheduler = None  # type: ignore


def create_scheduler() -> Optional["BackgroundScheduler"]:
    """
    Create and return a background scheduler.
    Returns None if APScheduler is not installed.

    Usage:
        scheduler = create_scheduler()
        if scheduler:
            scheduler.add_job(my_scan, 'interval', hours=24, id='daily_scan')
            scheduler.start()
    """
    if not HAS_APSCHEDULER:
        logger.warning("APScheduler not installed — scheduler unavailable")
        return None
    return BackgroundScheduler()


def schedule_scan(
    scheduler,
    scan_func,
    location: str,
    scan_type: str = "residential",
    interval_hours: int = 24,
    job_id: Optional[str] = None,
):
    """
    Schedule a recurring scan job.

    Args:
        scheduler: BackgroundScheduler instance.
        scan_func: Callable that runs the scan.
        location: Location string for the scan.
        scan_type: 'residential', 'land', or 'commercial'.
        interval_hours: Hours between scans.
        job_id: Optional unique job ID.
    """
    if not scheduler:
        logger.warning("No scheduler available")
        return

    job_id = job_id or f"{location}_{scan_type}_{interval_hours}h"

    scheduler.add_job(
        scan_func,
        "interval",
        hours=interval_hours,
        kwargs={
            "location": location,
            "scan_type": scan_type,
        },
        id=job_id,
        replace_existing=True,
    )
    logger.info(
        f"Scheduled '{job_id}': {scan_type} scan of '{location}' every {interval_hours}h"
    )
