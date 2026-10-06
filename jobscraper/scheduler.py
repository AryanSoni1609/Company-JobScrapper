"""Run everything on a schedule, with no manual steps.

Jobs (all times in TIMEZONE, default Asia/Kolkata):
    scan            every SCAN_INTERVAL_HOURS (first run 2 minutes after start)
    company sync    daily at 02:00 while LeetCode companies are still being
                    detected, then every COMPANY_SYNC_INTERVAL_DAYS
    nightly digest  daily at DIGEST_TIME (21:00): fresh scan + Gmail digest

Jobs run one at a time (single worker) so they never fight over the sheet.
If the machine was asleep/off at 21:00, the digest runs as soon as the
scheduler starts again that day (catch-up), or within the misfire grace.

Only one scheduler may run per machine: a localhost port is used as a lock,
so starting the MCP server with --with-scheduler next to `daemon` is safe.
"""

from __future__ import annotations

import logging
import socket
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import load_settings
from .state import State, now_iso

log = logging.getLogger("jobscraper.scheduler")

LOCK_PORT = 47653
_lock_socket: socket.socket | None = None


def acquire_single_instance_lock() -> bool:
    global _lock_socket
    if _lock_socket is not None:
        return True
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
    except OSError:
        s.close()
        return False
    _lock_socket = s
    return True


def _safe(name: str, fn):
    def run():
        log.info("Scheduled job '%s' starting", name)
        try:
            result = fn()
            log.info("Scheduled job '%s' finished: %s", name, _short(result))
        except Exception:  # noqa: BLE001 — keep the scheduler alive
            log.exception("Scheduled job '%s' failed", name)
        finally:
            State().set_meta(f"job_{name}_last_run", now_iso())
    run.__name__ = f"job_{name}"
    return run


def _short(result) -> str:
    if isinstance(result, dict):
        return ", ".join(f"{k}={v}" for k, v in result.items() if not isinstance(v, (list, dict)))[:300]
    return str(result)[:300]


def job_scan():
    from .pipeline import scan_jobs
    return scan_jobs()


def job_company_sync():
    from .pipeline import sync_companies

    settings = load_settings()
    state = State()
    remaining = state.get_meta("company_sync_remaining", "")
    last = state.get_meta("last_company_sync")
    if remaining == "0" and last:
        age = datetime.now(ZoneInfo("UTC")) - datetime.fromisoformat(last)
        if age < timedelta(days=settings.company_sync_interval_days):
            return {"skipped": f"all companies detected; next refresh after {settings.company_sync_interval_days} days"}
    return sync_companies()


def job_nightly():
    from .pipeline import run_nightly
    return run_nightly()


def _digest_hour_minute(settings) -> tuple[int, int]:
    try:
        h, m = settings.digest_time.split(":")
        return int(h), int(m)
    except ValueError:
        log.warning("Invalid DIGEST_TIME %r, using 21:00", settings.digest_time)
        return 21, 0


def digest_missed_today() -> bool:
    """True if today's digest time has passed and no digest went out since then."""
    settings = load_settings()
    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz)
    h, m = _digest_hour_minute(settings)
    due = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if now < due:
        return False
    last = State().get_meta("last_digest")
    # No catch-up on the very first start: wait for the first regular digest.
    return bool(last) and datetime.fromisoformat(last).astimezone(tz) < due


def build_scheduler(background: bool):
    from apscheduler.executors.pool import ThreadPoolExecutor
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    settings = load_settings()
    tz = ZoneInfo(settings.timezone)
    cls = BackgroundScheduler if background else BlockingScheduler
    sched = cls(timezone=tz, executors={"default": ThreadPoolExecutor(1)},
                job_defaults={"coalesce": True, "max_instances": 1})
    h, m = _digest_hour_minute(settings)
    now = datetime.now(tz)

    sched.add_job(_safe("nightly", job_nightly), CronTrigger(hour=h, minute=m, timezone=tz),
                  id="nightly_digest", name=f"Scan + Gmail digest at {h:02d}:{m:02d}",
                  misfire_grace_time=6 * 3600)
    sched.add_job(_safe("scan", job_scan), IntervalTrigger(hours=settings.scan_interval_hours, timezone=tz),
                  id="scan", name=f"Scan every {settings.scan_interval_hours}h",
                  next_run_time=now + timedelta(minutes=2), misfire_grace_time=3600)
    sched.add_job(_safe("company_sync", job_company_sync), CronTrigger(hour=2, minute=0, timezone=tz),
                  id="company_sync", name="LeetCode company sync at 02:00",
                  misfire_grace_time=12 * 3600)
    if digest_missed_today():
        log.info("Today's digest was missed (machine off/asleep at %02d:%02d); running it now", h, m)
        sched.add_job(_safe("nightly", job_nightly), id="nightly_catchup",
                      name="Catch-up digest (missed while offline)", next_run_time=now + timedelta(seconds=30))
    if not State().get_meta("last_company_sync"):
        sched.add_job(_safe("company_sync", job_company_sync), id="company_sync_first", name="First LeetCode company sync",
                      next_run_time=now + timedelta(minutes=1))
    return sched


def describe(sched) -> list[str]:
    return [f"{j.name}: next run {j.next_run_time:%Y-%m-%d %H:%M %Z}" for j in sched.get_jobs() if j.next_run_time]


def start_background():
    """Start the scheduler inside another process (e.g. the MCP server). Returns it, or None if
    another scheduler already runs on this machine."""
    if not acquire_single_instance_lock():
        log.warning("Another jobscraper scheduler is already running on this machine; not starting a second one")
        return None
    sched = build_scheduler(background=True)
    sched.start()
    for line in describe(sched):
        log.info(line)
    return sched


def run_forever():
    """Blocking daemon: `python -m jobscraper daemon`."""
    if not acquire_single_instance_lock():
        raise SystemExit("Another jobscraper scheduler is already running on this machine.")
    sched = build_scheduler(background=False)
    log.info("Scheduler started (timezone %s). Press Ctrl+C to stop.", load_settings().timezone)
    try:
        # BlockingScheduler only knows next_run_time after start(); log the plan from a listener
        from apscheduler.events import EVENT_SCHEDULER_STARTED

        sched.add_listener(lambda _e: [log.info(line) for line in describe(sched)], EVENT_SCHEDULER_STARTED)
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped")
