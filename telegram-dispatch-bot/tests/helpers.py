"""Shared test tools: a fake clock, an in-memory bot, and a way to 'type' as a driver."""

from __future__ import annotations

import itertools
import unittest
from datetime import datetime, timedelta, timezone

from dispatch_bot.config import Config
from dispatch_bot.core import Core, IncomingMessage
from dispatch_bot.db import Database

GROUP = -1001234567890
ADMIN = 100
# Tuesday 2026-10-13 12:00 UTC  ==  07:00 in Chicago (CDT, UTC-5)
START = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, start=START):
        self.dt = start

    def __call__(self):
        return self.dt

    def advance(self, **kw):
        self.dt += timedelta(**kw)


def make_cfg(**overrides) -> Config:
    base = dict(admin_ids=frozenset({ADMIN}), group_chat_id=GROUP, bot_token="123456:TESTTOKEN")
    base.update(overrides)
    return Config(**base)


class BotTestCase(unittest.TestCase):
    """Each test gets a fresh in-memory database and a controllable clock."""

    cfg_overrides: dict = {}

    def setUp(self):
        self.clock = Clock()
        self.db = Database(":memory:")
        self.core = Core(self.db, make_cfg(**self.cfg_overrides), now_fn=self.clock, bot_username="DispatchBot")
        self._msg_ids = itertools.count(1)
        self._upd_ids = itertools.count(1000)

    def tearDown(self):
        self.db.close()

    # -- typing as someone ----------------------------------------------------
    def say(self, user_id, name, text, *, chat_id=GROUP, chat_type="supergroup", update_id=None,
            message_id=None, reply_to_bot=False, mentions_bot=False, reply_to_user_id=None,
            minutes=1):
        """Send a message as a user and return what the bot would send. Time moves on a bit."""
        self.clock.advance(minutes=minutes)
        msg = IncomingMessage(
            chat_id=chat_id, chat_type=chat_type,
            message_id=message_id if message_id is not None else next(self._msg_ids),
            user_id=user_id, user_name=name, text=text,
            update_id=update_id if update_id is not None else next(self._upd_ids),
            reply_to_bot=reply_to_bot, mentions_bot=mentions_bot, reply_to_user_id=reply_to_user_id)
        return self.core.handle_message(msg)

    def admin(self, text, **kw):
        return self.say(ADMIN, "Dispatcher Dan", text, **kw)

    # -- convenience -------------------------------------------------------------
    @staticmethod
    def texts(outgoing):
        return [o.text for o in outgoing]

    @staticmethod
    def group_replies(outgoing):
        return [o for o in outgoing if o.chat_id == GROUP]

    @staticmethod
    def dms(outgoing):
        return [o for o in outgoing if o.chat_id != GROUP]

    def available_text(self):
        out = self.admin("/available")
        self.assertEqual(len(out), 1)
        return out[0].text
