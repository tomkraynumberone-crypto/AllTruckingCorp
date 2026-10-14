"""Morning greeting scheduling.

`is_greeting_due` is a plain function (easy to test). `run_scheduler` is the
small loop the real bot runs; it never talks to Telegram directly, it is given a
`send` coroutine function.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta

log = logging.getLogger("dispatch_bot.scheduler")


def is_greeting_due(local_now: datetime, greeting_time: time, days: frozenset,
                    catchup_minutes: int) -> bool:
    """True when `local_now` is on an allowed weekday and between the greeting time and
    greeting time + catch-up window.

    The catch-up window means: if the computer was off at 07:00 and you start the bot at
    07:40, the greeting still goes out. If you start it at 15:00 it does not (too late to
    be a "good morning" message). Set GREETING_CATCHUP_MINUTES=0 to disable catch-up.
    """
    if local_now.weekday() not in days:
        return False
    start = local_now.replace(hour=greeting_time.hour, minute=greeting_time.minute,
                              second=0, microsecond=0)
    return start <= local_now <= start + timedelta(minutes=max(catchup_minutes, 1))


async def run_scheduler(core, send, stop_event: asyncio.Event, interval_seconds: float = 20.0):
    """Check every few seconds whether the morning greeting must go out."""
    log.info("Scheduler started (checks every %ss).", interval_seconds)
    while not stop_event.is_set():
        try:
            job = core.scheduled_greeting()
            if job is not None:
                try:
                    await send(job.outgoing)
                    log.info("Morning greeting sent for %s.", job.run_date)
                except Exception:
                    # Allow a retry on the next tick instead of silently losing the greeting.
                    core.release_greeting(job.run_date)
                    log.exception("Could not send the morning greeting; will retry.")
        except Exception:
            log.exception("Scheduler error")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass
    log.info("Scheduler stopped.")
