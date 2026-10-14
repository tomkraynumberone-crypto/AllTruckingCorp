import os
import tempfile
import unittest

from dispatch_bot import messages as M
from dispatch_bot.core import Core
from dispatch_bot.db import Database
from tests.helpers import ADMIN, GROUP, BotTestCase, make_cfg

MO, JM, CL = (1, "Mohammad Ibrahim"), (2, "Juan Miguel"), (3, "Chris Lee")


class AvailabilityWithoutZip(BotTestCase):
    def test_available_asks_for_zip_and_is_not_confirmed(self):
        out = self.say(*MO, "Available")
        self.assertEqual(self.texts(out), [M.ASK_ZIP])
        self.assertEqual(out[0].chat_id, GROUP)
        d = self.db.get_driver(1)
        self.assertEqual((d.status, d.zip_code, d.awaiting), ("available", None, "zip"))
        self.assertEqual(self.available_text(), "No drivers on the available list right now.")
        self.assertIn("waiting for ZIP: 1 (Mohammad Ibrahim)", self.admin("/status")[0].text)

    def test_no_admin_notification_until_zip_is_known(self):
        self.assertEqual(self.dms(self.say(*MO, "I'm empty")), [])


class ZipProvided(BotTestCase):
    def test_zip_after_available_confirms_and_notifies_dispatcher(self):
        self.say(*MO, "Available")
        out = self.say(*MO, "19237")
        self.assertEqual(self.texts(self.group_replies(out)), [M.ZIP_ACK])
        dm = self.dms(out)
        self.assertEqual([(o.chat_id, o.text) for o in dm],
                         [(ADMIN, "✅ Driver available: Mohammad Ibrahim, 19237")])
        d = self.db.get_driver(1)
        self.assertEqual((d.name, d.zip_code, d.status, d.awaiting), ("Mohammad Ibrahim", "19237", "available", None))
        self.assertTrue(d.updated_at and d.zip_updated_at)
        self.assertEqual(self.available_text(), "Mohammad Ibrahim, 19237")

    def test_zip_inside_sentence(self):
        for text in ("I'm empty in 19237", "Available, ZIP 19237"):
            with self.subTest(text=text):
                out = self.say(*MO, text)
                self.assertEqual(self.texts(self.group_replies(out)), [M.ZIP_ACK])
        self.assertEqual(self.available_text(), "Mohammad Ibrahim, 19237")

    def test_same_zip_not_notified_twice(self):
        self.say(*MO, "Available 19237")
        out = self.say(*MO, "Available 19237")
        self.assertEqual(self.dms(out), [])

    def test_bot_never_claims_loads_found(self):
        for t in (M.ZIP_ACK, M.ASK_ZIP):
            self.assertNotIn("found", t.lower())


class FutureAvailability(BotTestCase):
    def test_future_time_is_not_available_now(self):
        out = self.say(*JM, "I'll be empty at 2 PM")
        self.assertEqual(self.texts(out), ["Thanks! I'll update your availability for 2pm."])
        self.assertEqual(self.db.get_driver(2).status, "later")
        self.assertEqual(self.available_text(), "Juan Miguel, will be available 2pm")
        self.assertIn("Available now (ZIP confirmed): 0", self.admin("/status")[0].text)
        self.assertIn("later: 1", self.admin("/status")[0].text)

    def test_not_yet_then_time(self):
        self.core.scheduled_greeting()                        # opens the check-in window
        self.assertEqual(self.texts(self.say(*JM, "Not yet")), [M.ASK_TIME])
        self.assertEqual(self.db.get_driver(2).status, "unavailable")
        self.assertEqual(self.texts(self.say(*JM, "2 PM")), ["Thanks! I'll update your availability for 2pm."])
        self.assertEqual(self.available_text(), "Juan Miguel, will be available 2pm")

    def test_time_without_context_is_ignored(self):
        self.assertEqual(self.say(*JM, "Delivering at 3pm"), [])
        self.assertIsNone(self.db.get_driver(2))

    def test_available_later_without_time_asks(self):
        self.assertEqual(self.texts(self.say(*JM, "available later")), [M.ASK_TIME])
        self.assertEqual(self.available_text(), "No drivers on the available list right now.")

    def test_tomorrow_morning_reply_to_bot(self):
        self.say(*JM, "Not yet")
        out = self.say(*JM, "Tomorrow morning", reply_to_bot=True)
        self.assertEqual(self.texts(out), ["Thanks! I'll update your availability for tomorrow morning."])


class ChangesAndDuplicates(BotTestCase):
    def test_zip_change_updates_same_record(self):
        self.say(*MO, "Available 19237")
        out = self.say(*MO, "My ZIP is now 60007")
        self.assertEqual(self.texts(self.group_replies(out)), [M.ZIP_ACK])
        self.assertEqual(self.dms(out)[0].text, "✅ Driver available: Mohammad Ibrahim, 60007")
        self.assertEqual(self.available_text(), "Mohammad Ibrahim, 60007")
        self.assertEqual(len(self.db.list_drivers()), 1)

    def test_loaded_removes_from_list_but_keeps_record(self):
        self.say(*MO, "Available 19237")
        out = self.say(*MO, "I'm loaded now")
        self.assertEqual(self.texts(out), [M.UNAVAILABLE_ACK])
        self.assertEqual(self.available_text(), "No drivers on the available list right now.")
        d = self.db.get_driver(1)
        self.assertEqual((d.status, d.active), ("unavailable", 1))
        self.say(*MO, "Available 19237")                        # next day: back again
        self.assertEqual(self.available_text(), "Mohammad Ibrahim, 19237")

    def test_other_unavailable_phrases(self):
        for phrase in ("I got a load", "No longer available"):
            with self.subTest(phrase=phrase):
                self.say(*MO, "Available 19237")
                self.say(*MO, phrase)
                self.assertEqual(self.db.get_driver(1).status, "unavailable")

    def test_available_to_later_and_back_without_duplicates(self):
        self.say(*MO, "Available 19237")
        self.say(*MO, "Actually available after 5")
        self.assertEqual(self.available_text(), "Mohammad Ibrahim, will be available 5pm")
        self.say(*MO, "Available now in 60007")
        self.assertEqual(self.available_text(), "Mohammad Ibrahim, 60007")
        self.assertEqual(len(self.db.list_drivers()), 1)

    def test_identity_is_telegram_id_not_name(self):
        self.say(10, "John Smith", "Available 11111")
        self.say(11, "John Smith", "Available 22222")
        self.assertEqual(len(self.db.list_drivers()), 2)
        self.assertEqual(self.available_text(), "John Smith, 11111; John Smith, 22222")
        self.say(10, "Johnny S.", "Available 33333")               # same ID, new display name
        self.assertEqual(len(self.db.list_drivers()), 2)
        self.assertEqual(self.db.get_driver(10).name, "Johnny S.")

    def test_repeating_available_does_not_reask(self):
        self.say(*MO, "Available 19237")
        self.assertEqual(self.texts(self.say(*MO, "Available")), [M.ALREADY_LISTED.format(zip="19237")])

    def test_old_zip_is_not_reused_after_hours(self):
        self.say(*MO, "Available 19237")
        self.say(*MO, "I'm loaded")
        self.clock.advance(hours=5)
        self.assertEqual(self.texts(self.say(*MO, "Available")), [M.ASK_ZIP])
        self.assertEqual(self.db.get_driver(1).zip_code, None)

    def test_duplicate_update_id_gets_one_reply(self):
        first = self.say(*MO, "Available", update_id=555, message_id=7)
        again = self.say(*MO, "Available", update_id=555, message_id=7)
        self.assertEqual(len(first), 1)
        self.assertEqual(again, [])

    def test_same_message_with_new_update_id_gets_one_reply(self):
        self.say(*MO, "Available 19237", update_id=1, message_id=9)
        again = self.say(*MO, "Available 19237", update_id=2, message_id=9)
        self.assertEqual(again, [])
        self.assertEqual(len(self.db.list_drivers()), 1)

    def test_duplicates_do_not_double_notify(self):
        self.say(*MO, "Available 19237", update_id=5, message_id=5)
        out = self.say(*MO, "Available 19237", update_id=5, message_id=5)
        self.assertEqual(out, [])


class AvailableListFormat(BotTestCase):
    def test_exact_format_with_mixed_entries(self):
        self.say(*MO, "Available 19237")
        self.say(*JM, "I'll be empty at 2 PM")
        self.say(*CL, "Available 60007")
        self.say(4, "Loaded Larry", "Available 99999")
        self.say(4, "Loaded Larry", "I'm loaded")
        self.assertEqual(self.available_text(),
                         "Mohammad Ibrahim, 19237; Chris Lee, 60007; Juan Miguel, will be available 2pm")

    def test_commas_and_semicolons_in_names_cannot_break_the_format(self):
        self.say(5, "Smith, John; Jr", "Available 11111")
        self.assertEqual(self.available_text(), "Smith John Jr, 11111")

    def test_empty_list_message(self):
        self.assertEqual(self.available_text(), "No drivers on the available list right now.")

    def test_stale_records_hidden_after_18_hours(self):
        self.say(*MO, "Available 19237")
        self.clock.advance(hours=19)
        self.assertEqual(self.available_text(), "No drivers on the available list right now.")
        self.assertIn("Hidden as outdated", self.admin("/status")[0].text)


class Persistence(unittest.TestCase):
    def test_data_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bot.sqlite3")
            t = BotTestCase()
            t.setUp()
            t.db.close()
            db1 = Database(path)
            core1 = Core(db1, make_cfg(), now_fn=t.clock, bot_username="DispatchBot")
            t.db, t.core = db1, core1
            t.say(*MO, "Available 19237")
            t.say(*JM, "available at 2pm")
            core1.db.set_setting("paused", "1")
            db1.close()

            db2 = Database(path)                                  # "restart"
            core2 = Core(db2, make_cfg(), now_fn=t.clock, bot_username="DispatchBot")
            self.assertEqual(core2.available_entries(),
                             ["Mohammad Ibrahim, 19237", "Juan Miguel, will be available 2pm"])
            self.assertTrue(core2.paused())
            db2.close()
            t.db = Database(":memory:")
            t.tearDown()


class AccessControl(BotTestCase):
    def test_non_admins_cannot_use_admin_commands(self):
        self.say(*JM, "Available 11111")
        for cmd in ("/available", "/status", "/refresh", "/remove 2", "/remove Juan", "/pause",
                    "/resume", "/setgroup", "/settime 08:00", "/settimezone America/New_York", "/schedule"):
            with self.subTest(cmd=cmd):
                out = self.say(*MO, cmd)
                self.assertEqual(self.texts(out), [M.NOT_AUTHORIZED])
        self.assertFalse(self.core.paused())
        self.assertEqual(self.core.group_chat_id(), GROUP)
        self.assertEqual(self.core.greeting_time().strftime("%H:%M"), "07:00")
        self.assertEqual(self.db.get_driver(2).active, 1)
        self.assertEqual(self.available_text(), "Juan Miguel, 11111")

    def test_drivers_can_use_public_commands(self):
        for cmd in ("/start", "/help", "/myid"):
            self.assertEqual(len(self.say(*MO, cmd)), 1)
        self.assertNotIn("/remove", self.say(*MO, "/help")[0].text)
        self.assertIn("/remove", self.admin("/help")[0].text)

    def test_driver_cannot_change_someone_elses_record(self):
        self.say(*JM, "Available 11111")
        self.say(*MO, "Available 19237")
        self.assertEqual(self.db.get_driver(2).zip_code, "11111")

    def test_command_for_other_bot_is_ignored(self):
        self.assertEqual(self.admin("/available@SomeOtherBot"), [])
        self.assertEqual(len(self.admin("/available@DispatchBot")), 1)


class IgnoringChatter(BotTestCase):
    def test_unrelated_messages_get_no_reply_and_no_record(self):
        chatter = ["Good morning everyone", "Where is the load for 12345?", "Any loads available?",
                   "Delivered, POD sent", "what's the rate for Atlanta", "I'm loaded, heading to Dallas",
                   "Still loaded, ETA 5pm", "load from 60007 to 30301",
                   "ok", "thanks boss", "Is anyone available to cover?",
                   "word " * 40 + "available"]
        for text in chatter:
            with self.subTest(text=text[:40]):
                self.assertEqual(self.say(*MO, text), [])
        self.assertEqual(self.db.list_drivers(), [])

    def test_other_chats_and_unset_group_are_ignored(self):
        self.assertEqual(self.say(*MO, "Available 19237", chat_id=-999), [])
        self.db.set_setting("group_chat_id", None)
        self.assertEqual(self.say(*MO, "Available 19237"), [])

    def test_private_chat_gets_hint_only(self):
        out = self.say(*MO, "Available 19237", chat_id=MO[0], chat_type="private")
        self.assertEqual(self.texts(out), [M.PRIVATE_HINT])
        self.assertEqual(self.db.list_drivers(), [])

    def test_dispatcher_messages_not_tracked_by_default(self):
        self.assertEqual(self.admin("Available 19237"), [])
        self.assertEqual(self.db.list_drivers(), [])

    def test_bots_are_ignored(self):
        from dispatch_bot.core import IncomingMessage
        m = IncomingMessage(GROUP, "supergroup", 1, 77, "Other Bot", "Available", is_bot=True)
        self.assertEqual(self.core.handle_message(m), [])


class AdminTracking(BotTestCase):
    cfg_overrides = {"treat_admins_as_drivers": True}

    def test_admin_can_test_as_driver_when_enabled(self):
        out = self.admin("Available 19237")
        self.assertEqual(self.texts(self.group_replies(out)), [M.ZIP_ACK])


class Ambiguity(BotTestCase):
    def test_hedging_triggers_clarification_without_guessing(self):
        out = self.say(*MO, "maybe available")
        self.assertEqual(self.texts(out), [M.CLARIFY])
        self.assertEqual(self.available_text(), "No drivers on the available list right now.")

    def test_yes_after_clarification_means_available(self):
        self.say(*MO, "maybe available")
        self.assertEqual(self.texts(self.say(*MO, "yes")), [M.ASK_ZIP])
        self.assertEqual(self.db.get_driver(1).status, "available")

    def test_no_after_clarification_asks_time(self):
        self.say(*MO, "maybe available")
        self.assertEqual(self.texts(self.say(*MO, "no")), [M.ASK_TIME])

    def test_yes_without_question_is_ignored(self):
        self.assertEqual(self.say(*MO, "yes"), [])

    def test_unloaded_and_bare_ready(self):
        self.assertEqual(self.texts(self.say(*MO, "just unloaded")), [M.CLARIFY])
        self.assertEqual(self.say(*JM, "ready"), [])               # no check-in open -> ignore
        self.core.scheduled_greeting()
        self.assertEqual(self.texts(self.say(*JM, "ready")), [M.CLARIFY])

    def test_bare_zip_without_context_is_ignored_but_in_checkin_window_is_noted(self):
        self.assertEqual(self.say(*MO, "19237"), [])
        self.core.scheduled_greeting()
        out = self.say(*MO, "19237")
        self.assertEqual(self.texts(out), [M.ZIP_NOTED_ASK_STATUS.format(zip="19237")])
        self.assertEqual(self.available_text(), "No drivers on the available list right now.")


class AdminCommands(BotTestCase):
    def test_remove_by_name_id_and_reply(self):
        self.say(*MO, "Available 19237")
        self.say(*JM, "Available 11111")
        self.say(*CL, "Available 22222")
        self.assertIn("Removed Mohammad Ibrahim", self.admin("/remove mohammad")[0].text)
        self.assertIn("Removed Juan Miguel", self.admin("/remove 2")[0].text)
        self.assertIn("Removed Chris Lee", self.admin("/remove", reply_to_user_id=3)[0].text)
        self.assertEqual(self.available_text(), "No drivers on the available list right now.")
        self.assertEqual(len(self.db.list_drivers(active_only=False)), 3)   # records retained
        self.say(*MO, "Available 19237")                                    # driver can come back
        self.assertEqual(self.available_text(), "Mohammad Ibrahim, 19237")

    def test_remove_ambiguous_name_and_missing(self):
        self.say(10, "John Smith", "Available 11111")
        self.say(11, "John Stone", "Available 22222")
        self.assertIn("Several drivers match", self.admin("/remove john")[0].text)
        self.assertIn("couldn't find", self.admin("/remove nobody")[0].text)
        self.assertIn("Usage", self.admin("/remove")[0].text)

    def test_pause_silences_replies_but_still_records(self):
        self.admin("/pause")
        self.assertEqual(self.group_replies(self.say(*MO, "Available 19237")), [])
        self.assertEqual(self.available_text(), "Mohammad Ibrahim, 19237")
        self.assertIn("PAUSED", self.admin("/status")[0].text)
        self.admin("/resume")
        self.assertEqual(self.texts(self.say(*JM, "Available")), [M.ASK_ZIP])

    def test_refresh_with_cooldown_and_zip_request(self):
        self.say(*MO, "Available")                                           # waiting for ZIP
        out = self.admin("/refresh")
        self.assertEqual(out[0].chat_id, GROUP)
        self.assertEqual(out[0].parse_mode, "HTML")
        self.assertIn("ZIP code", out[0].text)
        self.assertIn('tg://user?id=1">Mohammad Ibrahim</a>', out[0].text)
        again = self.admin("/refresh")
        self.assertIn("wait", again[0].text)
        self.clock.advance(minutes=31)
        self.assertEqual(self.admin("/refresh")[0].chat_id, GROUP)

    def test_refresh_from_private_chat_posts_to_group(self):
        out = self.admin("/refresh", chat_id=ADMIN, chat_type="private")
        self.assertEqual([o.chat_id for o in out], [GROUP, ADMIN])

    def test_setgroup_settime_settimezone_schedule(self):
        self.assertIn("now the dispatch group", self.admin("/setgroup", chat_id=-42)[0].text)
        self.assertEqual(self.core.group_chat_id(), -42)
        self.assertIn("08:30", self.admin("/settime 8:30", chat_id=-42)[0].text)
        self.assertIn("valid time", self.admin("/settime 25:00", chat_id=-42)[0].text)
        self.assertIn("valid timezone", self.admin("/settimezone Mars/Base", chat_id=-42)[0].text)
        self.assertIn("America/New_York", self.admin("/settimezone America/New_York", chat_id=-42)[0].text)
        text = self.admin("/schedule", chat_id=-42)[0].text
        self.assertIn("08:30 America/New_York", text)

    def test_setgroup_in_private_chat_refused(self):
        out = self.admin("/setgroup", chat_id=ADMIN, chat_type="private")
        self.assertIn("inside your dispatch group", out[0].text)
        self.assertEqual(self.core.group_chat_id(), GROUP)

    def test_long_list_is_split_into_several_messages(self):
        for i in range(400):
            self.say(1000 + i, f"Driver Number {i:03d}", f"Available {10000 + i}", minutes=0)
        out = self.admin("/available")
        self.assertGreater(len(out), 1)
        self.assertTrue(all(len(o.text) <= 4000 for o in out))
        self.assertEqual(sum(o.text.count("; ") + 1 for o in out), 400)


if __name__ == "__main__":
    unittest.main()
