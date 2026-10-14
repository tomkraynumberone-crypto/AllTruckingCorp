import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from dispatch_bot.parser import Intent, parse

TZ = ZoneInfo("America/Chicago")
MORNING = datetime(2026, 10, 13, 8, 0, tzinfo=TZ)


def p(text, now=MORNING):
    return parse(text, now)


class IntentTests(unittest.TestCase):
    def check(self, texts, intent):
        for t in texts:
            with self.subTest(text=t):
                self.assertEqual(p(t).intent, intent)

    def test_available_phrases_from_the_spec(self):
        self.check(["Available", "I'm empty", "Empty and ready", "Ready for a load",
                    "I am available this morning", "Available now", "Boşum",
                    "I'm empty in Chicago", "avail", "I’m empty", "свободен", "bo'shman"],
                   Intent.AVAILABLE_NOW)

    def test_zip_only(self):
        self.check(["19237", "zip 19237", "My ZIP is now 60007", "ZIP code: 60007-1234"], Intent.ZIP_ONLY)

    def test_not_yet_without_time(self):
        self.check(["Not yet", "Still loaded", "not available", "Still delivering"], Intent.NOT_YET)

    def test_unavailable(self):
        self.check(["I'm loaded now", "I got a load", "No longer available", "just got booked",
                    "I'm loaded", "have a load"], Intent.UNAVAILABLE)

    def test_future_availability(self):
        self.check(["I'll be empty at 2 PM", "Available after 5", "Not available until 10 AM",
                    "I will be empty in 3 hours", "available tomorrow", "available later",
                    "available monday", "loaded, will be empty at 2pm"], Intent.AVAILABLE_LATER)

    def test_unrelated_chat_is_none(self):
        self.check(["Good morning everyone", "Delivering at 3pm", "load from 60007 to 30301",
                    "Any loads available?", "I need an empty trailer", "delivered POD sent",
                    "what's the rate", "thanks boss"], Intent.NONE)

    def test_ambiguous(self):
        self.check(["maybe available", "I think I'm empty", "unloaded", "just unloaded"], Intent.AMBIGUOUS)

    def test_bare_ready_is_weak(self):
        self.check(["ready", "I'm ready"], Intent.READY_WEAK)

    def test_not_loaded_means_empty(self):
        self.check(["I'm not loaded"], Intent.AVAILABLE_NOW)


class ZipTests(unittest.TestCase):
    def test_zip_extraction(self):
        self.assertEqual(p("I'm empty in 19237").zip_code, "19237")
        self.assertEqual(p("Available, ZIP 19237").zip_code, "19237")
        self.assertEqual(p("19237").zip_code, "19237")
        self.assertEqual(p("zip 60007-1234").zip_code, "60007")

    def test_not_a_zip(self):
        self.assertIsNone(p("rate is $12000").zip_code)
        self.assertIsNone(p("call 312-555-1234").zip_code)
        self.assertIsNone(p("available 1234").zip_code)
        self.assertIsNone(p("available 123456").zip_code)


class TimeTests(unittest.TestCase):
    def t(self, text, now=MORNING):
        info = p(text, now).time
        return info.text if info else None

    def test_explicit_times(self):
        self.assertEqual(self.t("available at 2 PM"), "2pm")
        self.assertEqual(self.t("available 2pm"), "2pm")
        self.assertEqual(self.t("empty at 2:30 pm"), "2:30pm")
        self.assertEqual(self.t("not available until 10 AM"), "10am")
        self.assertEqual(self.t("available 14:00"), "2pm")
        self.assertEqual(self.t("empty at noon"), "12pm")

    def test_bare_hour_uses_next_occurrence(self):
        self.assertEqual(self.t("available after 5"), "5pm")                 # 8am now -> 5pm
        self.assertEqual(self.t("available at 9"), "9am")                    # 8am now -> 9am
        self.assertEqual(self.t("available at 7"), "7pm")                    # 7am already passed
        afternoon = datetime(2026, 10, 13, 15, 0, tzinfo=TZ)
        self.assertEqual(self.t("available at 4", afternoon), "4pm")
        self.assertEqual(self.t("available at 8", afternoon), "8pm")

    def test_durations_become_clock_times(self):
        self.assertEqual(self.t("I will be empty in 3 hours"), "11am")
        self.assertEqual(self.t("empty in an hour"), "9am")
        self.assertEqual(self.t("empty in 30 minutes"), "8:30am")
        late = datetime(2026, 10, 13, 22, 0, tzinfo=TZ)
        self.assertEqual(self.t("empty in 3 hours", late), "tomorrow 1am")

    def test_day_words(self):
        self.assertEqual(self.t("tomorrow morning"), "tomorrow morning")
        self.assertEqual(self.t("available tomorrow"), "tomorrow")
        self.assertEqual(self.t("available tomorrow at 8"), "tomorrow 8am")
        self.assertEqual(self.t("available tomorrow 3pm"), "tomorrow 3pm")
        self.assertEqual(self.t("available monday"), "monday")
        self.assertEqual(self.t("empty tonight"), "tonight")

    def test_distances_and_loads_are_not_times(self):
        self.assertIsNone(self.t("available at 19237"))
        self.assertIsNone(self.t("I have 2 loads"))
        self.assertIsNone(self.t("empty after 300 miles"))

    def test_pure_time_flag(self):
        self.assertTrue(p("2 PM").pure_time)
        self.assertTrue(p("around 2pm").pure_time)
        self.assertTrue(p("Tomorrow morning").pure_time)
        self.assertFalse(p("I'm empty at 2pm").pure_time)


if __name__ == "__main__":
    unittest.main()
