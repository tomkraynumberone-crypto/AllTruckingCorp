import asyncio
import os
import tempfile
import unittest
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from dispatch_bot.core import Core
from dispatch_bot.db import Database
from dispatch_bot.scheduler import is_greeting_due, run_scheduler
from tests.helpers import GROUP, START, BotTestCase, make_cfg

CHI = ZoneInfo("America/Chicago")


class DuePure(unittest.TestCase):
    def test_window(self):
        t = time(7, 0)
        days = frozenset(range(7))
        d = lambda h, m: datetime(2026, 10, 13, h, m, tzinfo=CHI)
        self.assertFalse(is_greeting_due(d(6, 59), t, days, 120))
        self.assertTrue(is_greeting_due(d(7, 0), t, days, 120))
        self.assertTrue(is_greeting_due(d(8, 59), t, days, 120))
        self.assertFalse(is_greeting_due(d(9, 30), t, days, 120))

    def test_weekdays(self):
        weekdays = frozenset(range(5))
        saturday = datetime(2026, 10, 17, 7, 0, tzinfo=CHI)
        self.assertFalse(is_greeting_due(saturday, time(7, 0), weekdays, 120))


class GreetingScheduling(BotTestCase):
    def test_not_before_time_then_once_per_day(self):
        self.clock.dt = START - timedelta(minutes=1)              # 06:59 Chicago
        self.assertIsNone(self.core.scheduled_greeting())
        self.clock.dt = START                                     # 07:00
        job = self.core.scheduled_greeting()
        self.assertIsNotNone(job)
        self.assertEqual(job.outgoing.chat_id, GROUP)
        self.assertIn("Are you empty and available today?", job.outgoing.text)
        for _ in range(5):                                        # many ticks, no duplicates
            self.clock.advance(minutes=1)
            self.assertIsNone(self.core.scheduled_greeting())
        self.clock.dt = START + timedelta(days=1)                 # next morning works again
        self.assertIsNotNone(self.core.scheduled_greeting())

    def test_no_duplicate_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "b.sqlite3")
            db1 = Database(path)
            self.assertIsNotNone(Core(db1, make_cfg(), now_fn=self.clock).scheduled_greeting())
            db1.close()
            self.clock.advance(minutes=10)
            db2 = Database(path)
            self.assertIsNone(Core(db2, make_cfg(), now_fn=self.clock).scheduled_greeting())
            db2.close()

    def test_late_start_catches_up_but_not_all_day(self):
        self.clock.dt = START + timedelta(minutes=40)
        self.assertIsNotNone(self.core.scheduled_greeting())
        self.db.release_run("greeting", "2026-10-13")
        self.clock.dt = START + timedelta(hours=8)
        self.assertIsNone(self.core.scheduled_greeting())

    def test_paused_and_no_group(self):
        self.admin("/pause")
        self.assertIsNone(self.core.scheduled_greeting())
        self.admin("/resume")
        self.db.set_setting("group_chat_id", None)
        self.assertIsNone(self.core.scheduled_greeting())

    def test_weekday_setting(self):
        core = Core(self.db, make_cfg(greeting_days=frozenset(range(5))), now_fn=self.clock)
        self.clock.dt = START + timedelta(days=4)                 # Saturday
        self.assertIsNone(core.scheduled_greeting())

    def test_time_and_timezone_are_configurable_not_hardcoded(self):
        self.admin("/settimezone America/New_York")
        self.admin("/settime 07:00")
        self.clock.dt = datetime(2026, 10, 13, 10, 59, tzinfo=timezone.utc)   # 06:59 EDT
        self.assertIsNone(self.core.scheduled_greeting())
        self.clock.dt = datetime(2026, 10, 13, 11, 0, tzinfo=timezone.utc)    # 07:00 EDT
        self.assertIsNotNone(self.core.scheduled_greeting())

    def test_custom_message_from_config(self):
        core = Core(self.db, make_cfg(morning_message="Hi team!"), now_fn=self.clock)
        self.assertEqual(core.scheduled_greeting().outgoing.text, "Hi team!")

    def test_greeting_opens_checkin_window(self):
        self.assertEqual(self.say(1, "A", "ready"), [])
        self.core.scheduled_greeting()
        self.assertEqual(len(self.say(1, "A", "ready")), 1)

    def test_failed_send_can_be_retried(self):
        job = self.core.scheduled_greeting()
        self.core.release_greeting(job.run_date)
        self.assertIsNotNone(self.core.scheduled_greeting())


class SchedulerLoop(BotTestCase):
    def test_loop_sends_exactly_once(self):
        sent = []

        async def send(out):
            sent.append(out)

        async def go():
            stop = asyncio.Event()
            task = asyncio.create_task(run_scheduler(self.core, send, stop, interval_seconds=0.01))
            await asyncio.sleep(0.15)
            stop.set()
            await task

        asyncio.run(go())
        self.assertEqual(len(sent), 1)

    def test_loop_retries_after_send_failure(self):
        attempts = []

        async def flaky(out):
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("network down")

        async def go():
            stop = asyncio.Event()
            task = asyncio.create_task(run_scheduler(self.core, flaky, stop, interval_seconds=0.01))
            await asyncio.sleep(0.15)
            stop.set()
            await task

        asyncio.run(go())
        self.assertEqual(len(attempts), 2)          # failed once, succeeded once, then stopped


if __name__ == "__main__":
    unittest.main()
