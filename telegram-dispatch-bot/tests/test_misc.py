import importlib.util
import io
import logging
import unittest
from types import SimpleNamespace as NS

from dispatch_bot.config import ConfigError, load_config
from dispatch_bot.logging_setup import RedactSecrets
from dispatch_bot.telegram_convert import to_incoming

BOT_ID, BOT_NAME = 999, "DispatchBot"


def fake_message(text="Available", reply_from=None, entities=None, from_user="default"):
    user = NS(id=1, full_name="Juan Miguel", first_name="Juan", last_name="Miguel",
              username="juanm", is_bot=False) if from_user == "default" else from_user
    reply = NS(from_user=reply_from) if reply_from else None
    return NS(chat=NS(id=-100, type="supergroup"), message_id=5, from_user=user, text=text,
              reply_to_message=reply, entities=entities)


class ConvertTests(unittest.TestCase):
    def test_basic_fields(self):
        m = to_incoming(fake_message(), 42, BOT_ID, BOT_NAME)
        self.assertEqual((m.chat_id, m.user_id, m.user_name, m.update_id, m.message_id),
                         (-100, 1, "Juan Miguel", 42, 5))
        self.assertFalse(m.reply_to_bot)
        self.assertFalse(m.mentions_bot)

    def test_reply_to_bot_and_to_human(self):
        bot = NS(id=BOT_ID, is_bot=True)
        human = NS(id=7, is_bot=False)
        m = to_incoming(fake_message(reply_from=bot), 1, BOT_ID, BOT_NAME)
        self.assertTrue(m.reply_to_bot)
        self.assertIsNone(m.reply_to_user_id)
        m = to_incoming(fake_message(reply_from=human), 1, BOT_ID, BOT_NAME)
        self.assertFalse(m.reply_to_bot)
        self.assertEqual(m.reply_to_user_id, 7)

    def test_mentions(self):
        self.assertTrue(to_incoming(fake_message("@dispatchbot available"), 1, BOT_ID, BOT_NAME).mentions_bot)
        ent = [NS(type="text_mention", user=NS(id=BOT_ID))]
        self.assertTrue(to_incoming(fake_message("hey", entities=ent), 1, BOT_ID, BOT_NAME).mentions_bot)
        self.assertFalse(to_incoming(fake_message("@dispatchbotx hi"), 1, BOT_ID, BOT_NAME).mentions_bot)

    def test_no_text_or_no_sender(self):
        self.assertIsNone(to_incoming(fake_message(text=None), 1, BOT_ID, BOT_NAME))
        self.assertIsNone(to_incoming(fake_message(from_user=None), 1, BOT_ID, BOT_NAME))

    @unittest.skipUnless(importlib.util.find_spec("aiogram"), "aiogram not installed")
    def test_with_real_aiogram_message_object(self):
        import datetime
        from aiogram.types import Chat, Message, User
        msg = Message(message_id=5, date=datetime.datetime.now(), chat=Chat(id=-100, type="supergroup", title="x"),
                      from_user=User(id=1, is_bot=False, first_name="Juan", last_name="Miguel"), text="Available")
        m = to_incoming(msg, 1, BOT_ID, BOT_NAME)
        self.assertEqual((m.user_id, m.user_name, m.chat_id), (1, "Juan Miguel", -100))


class ConfigTests(unittest.TestCase):
    good = {"BOT_TOKEN": "123456:ABC", "ADMIN_IDS": "11, 22"}

    def test_defaults(self):
        c = load_config(dict(self.good))
        self.assertEqual(c.timezone, "America/Chicago")
        self.assertEqual(c.admin_ids, frozenset({11, 22}))
        self.assertEqual(c.greeting_time, "07:00")
        self.assertEqual(c.greeting_days, frozenset(range(7)))

    def test_overrides(self):
        c = load_config({**self.good, "TIMEZONE": "America/New_York", "GREETING_TIME": "6:30",
                         "GREETING_DAYS": "Mon,Tue,Fri", "GROUP_CHAT_ID": "-100123"})
        self.assertEqual((c.timezone, c.greeting_time, c.group_chat_id), ("America/New_York", "06:30", -100123))
        self.assertEqual(c.greeting_days, frozenset({0, 1, 4}))

    def test_helpful_errors(self):
        for bad in ({}, {"BOT_TOKEN": "x"}, {**self.good, "TIMEZONE": "Nowhere/Land"},
                    {**self.good, "GREETING_TIME": "25:99"}, {**self.good, "ADMIN_IDS": "bob"},
                    {**self.good, "GREETING_DAYS": "Funday"}, {**self.good, "GROUP_CHAT_ID": "abc"},
                    {"BOT_TOKEN": "PASTE_YOUR_TOKEN", "ADMIN_IDS": "1"}):
            with self.subTest(env=bad):
                with self.assertRaises(ConfigError):
                    load_config(bad)


class LoggingTests(unittest.TestCase):
    def test_token_is_masked(self):
        token = "123456789:AAH-secretsecretsecretsecretsecret12345"
        stream = io.StringIO()
        h = logging.StreamHandler(stream)
        h.addFilter(RedactSecrets([token]))
        lg = logging.getLogger("redact-test")
        lg.propagate = False
        lg.addHandler(h)
        lg.warning("url https://api.telegram.org/bot%s/getMe failed", token)
        try:
            raise RuntimeError(f"boom {token}")
        except RuntimeError:
            lg.exception("oops")
        self.assertNotIn("secretsecret", stream.getvalue())
        self.assertIn("***", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
