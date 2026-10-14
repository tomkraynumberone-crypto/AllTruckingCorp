"""Rule-based understanding of driver messages (no AI service, no network).

`parse(text, now)` turns a message into a `Parsed` result: an intent, plus an
optional ZIP code and an optional expected-availability time.

`now` must be a timezone-aware datetime in the dispatch timezone. It is only
used to resolve vague times ("at 5", "in 3 hours").
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from . import phrases as P


class Intent(str, Enum):
    AVAILABLE_NOW = "available_now"      # empty and ready now
    AVAILABLE_LATER = "available_later"  # will be empty later (time may be unknown)
    NOT_YET = "not_yet"                  # not empty yet, no time given -> ask for it
    UNAVAILABLE = "unavailable"          # loaded / no longer available
    ZIP_ONLY = "zip_only"                # a ZIP code and nothing else relevant
    TIME_ONLY = "time_only"              # a time and nothing else relevant
    READY_WEAK = "ready_weak"            # just "ready" - could mean many things
    AMBIGUOUS = "ambiguous"              # unsure / hedging -> clarify
    YES = "yes"
    NO = "no"
    NONE = "none"                        # not about availability


@dataclass(frozen=True)
class TimeInfo:
    text: str                            # how it is shown in the list, e.g. "2pm"
    dt: datetime | None = None           # exact moment when it can be worked out
    spans: tuple = ()                    # matched character ranges (internal)


@dataclass(frozen=True)
class Parsed:
    intent: Intent
    zip_code: str | None = None
    time: TimeInfo | None = None
    word_count: int = 0
    is_question: bool = False
    pure_time: bool = False              # message is essentially only a time


# --------------------------------------------------------------------------
# Helpers to build regexes from word lists
# --------------------------------------------------------------------------
def _norm_apostrophes(s: str) -> str:
    return (s.replace("\u2019", "'").replace("\u2018", "'").replace("\u02bc", "'")
             .replace("\u02bb", "'").replace("`", "'").replace("\u00b4", "'"))


def _alt(words) -> str:
    items = sorted((_norm_apostrophes(w) for w in words), key=len, reverse=True)
    return "(?:%s)" % "|".join(re.escape(w) for w in items)


def _words_re(words) -> re.Pattern:
    return re.compile(r"(?<!\w)%s(?!\w)" % _alt(words))


AVAIL_RE = _words_re(P.AVAILABLE_WORDS)
LOADED_RE = _words_re(P.LOADED_WORDS)
NOT_NOW_RE = _words_re(P.NOT_NOW_PHRASES)
HEDGE_RE = _words_re(P.HEDGE_WORDS)
YES_RE = re.compile(r"(?:%s)\W*" % _alt(P.YES_WORDS))
NO_RE = re.compile(r"(?:%s)\W*" % _alt(P.NO_WORDS))

LOADED_PHRASE_RE = re.compile(
    r"(?<!\w)(?:got|have|took|booked|picked up|accepted|i'm on|im on|on)\s+"
    r"(?:a|the|my|another|new)?\s*load(?!\w)")
NO_LONGER_RE = re.compile(r"(?<!\w)(?:no longer|not anymore|not any more)(?!\w)")
NOT_LOADED_RE = re.compile(
    r"(?<!\w)(?:not|isn't|am not|i'm not|im not)\s+loaded(?!\w)")
UNLOADED_RE = re.compile(r"(?<!\w)(?:just\s+|finished\s+|done\s+)?unloaded(?!\w)")
READY_STRONG_RE = re.compile(
    r"(?<!\w)ready\s+(?:for|to)\s+(?:a\s+|another\s+|the\s+|new\s+)?"
    r"(?:load|loads|go|roll|work|pick|dispatch|haul|move)(?!\w)")
READY_WEAK_RE = re.compile(r"(?<!\w)ready(?!\w)")
WILL_RE = re.compile(r"(?<!\w)(?:will be|i'll be|ill be|gonna be|going to be|should be)(?!\w)")
LATER_RE = re.compile(
    r"(?<!\w)(?:later|soon|shortly|in a bit|in a while|next week|"
    r"in the (?:morning|afternoon|evening)|after lunch)(?!\w)")
NOW_RE = re.compile(
    r"(?<!\w)(?:now|right now|asap|today|this morning|immediately|currently|rn)(?!\w)")
UNTIL_RE = re.compile(r"(?<!\w)(?:until|till|after|not before)(?!\w)")
ZIP_CTX_RE = re.compile(
    r"(?<!\w)(?:zip|zipcode|zip code|postal|location|located|currently|"
    r"now in|now at|i'm in|im in|i am in|i'm at|im at|i am at)(?!\w)")

NOISE_RES = [
    re.compile(r"(?<!\w)loads?\s+(?:is\s+|are\s+)?(?:available|avail)(?!\w)"),
    re.compile(r"(?<!\w)(?:available|avail)\s+loads?(?!\w)"),
    re.compile(r"(?<!\w)empty\s+(?:miles?|trailers?|containers?|chassis|box|pallets?|reefer|space|return)(?!\w)"),
]

ZIP_RE = re.compile(r"(?<![\d$.,#])(\d{5})(?:-\d{4})?(?!\d|[.,]\d)")
ZIP_ALONE_RE = re.compile(r"(?:zip(?:\s*code)?\s*[:#-]?\s*)?\d{5}(?:-\d{4})?")

# A time next to these words is about a delivery/appointment, not about being empty.
OTHER_TIME_RE = re.compile(
    r"(?<!\w)(?:eta|deliver\w*|appointment|appt|pick ?up|drop ?off|arriv\w*|"
    r"unload(?:ing)? at|scheduled|check ?in)(?!\w)")

MAX_WORDS = 30


# --------------------------------------------------------------------------
# ZIP
# --------------------------------------------------------------------------
def extract_zip(t: str) -> str | None:
    for m in ZIP_RE.finditer(t):
        if m.group(1) != "00000":
            return m.group(1)
    return None


# --------------------------------------------------------------------------
# Time
# --------------------------------------------------------------------------
_NUM_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
              "six": 6, "seven": 7, "eight": 8, "half a": 0.5, "half an": 0.5}
_UNIT = r"(hours?|hrs?|hr|minutes?|mins?|min)"
DURATION_RE = re.compile(
    r"(?<!\w)(?:in|after|within)\s+(?:about\s+|around\s+|like\s+)?"
    r"(\d+(?:\.\d+)?|half an?|an?|one|two|three|four|five|six|seven|eight)\s*" + _UNIT + r"(?!\w)")
MERIDIEM_RE = re.compile(r"(?<![\d:.])(\d{1,2})(?::([0-5]\d))?\s*([ap])\.?\s?m(?!\w)\.?")
COLON_RE = re.compile(r"(?<![\d:.])([01]?\d|2[0-3]):([0-5]\d)(?![\d:])")
CONTEXT_HOUR_RE = re.compile(
    r"(?:(?<!\w)(?:at|after|until|till|by|around|about|before)|@)\s*(\d{1,2})(?::([0-5]\d))?"
    r"(?![\d:])(?!\s*(?:miles?|mi(?!\w)|loads?|lbs?|k(?!\w)|%|hours?|hrs?|minutes?|mins?|[ap]\.?\s?m(?!\w)))")
TOMORROW_RE = re.compile(r"(?<!\w)(?:tomorrow|tmrw|tmr)(?!\w)")
WEEKDAY_RE = re.compile(
    r"(?<!\w)(?:on\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?!\w)")
PART_RE = re.compile(r"(?<!\w)(morning|afternoon|evening|night)(?!\w)")
SPECIAL_RES = [
    (re.compile(r"(?<!\w)this afternoon(?!\w)"), "this afternoon"),
    (re.compile(r"(?<!\w)this evening(?!\w)"), "this evening"),
    (re.compile(r"(?<!\w)tonight(?!\w)"), "tonight"),
    (re.compile(r"(?<!\w)later today(?!\w)"), "later today"),
    (re.compile(r"(?<!\w)(?:end of day|eod)(?!\w)"), "end of day"),
]
NOON_RE = re.compile(r"(?<!\w)noon(?!\w)")
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _fmt_clock(h24: int, minute: int) -> str:
    h12 = h24 % 12 or 12
    suffix = "am" if h24 < 12 else "pm"
    return f"{h12}{':%02d' % minute if minute else ''}{suffix}"


def _resolve_clock(hour: int, minute: int, meridiem: str | None, now: datetime,
                   day_given: bool) -> tuple[int, bool]:
    """Return (hour24, rolled_to_tomorrow). Guesses am/pm when the driver did not say.

    Rules for a bare hour such as "at 5":
      * with a day word ("tomorrow at 8"): 5-11 -> am, 12-4 -> pm
      * otherwise: the next time that hour happens (am or pm) from now.
    """
    if meridiem == "am":
        return (0 if hour == 12 else hour), False
    if meridiem == "pm":
        return (12 if hour == 12 else hour + 12), False
    if hour == 0 or hour > 12:                      # already 24-hour time
        return hour, False
    if hour == 12:
        return 12, False
    if day_given:
        return (hour if 5 <= hour <= 11 else hour + 12), False
    for h24 in (hour, hour + 12):
        if now.replace(hour=h24, minute=minute, second=0, microsecond=0) > now:
            return h24, False
    return hour, True


def _next_weekday(now: datetime, name: str) -> datetime:
    target = _WEEKDAYS.index(name)
    delta = (target - now.weekday()) % 7
    return now + timedelta(days=delta or 7)


def _round5(dt: datetime) -> datetime:
    dt = dt.replace(second=0, microsecond=0)
    return dt - timedelta(minutes=dt.minute % 5) + (
        timedelta(minutes=5) if dt.minute % 5 >= 3 else timedelta())


def extract_time(t: str, now: datetime) -> TimeInfo | None:
    # 1) "in 3 hours", "in 30 minutes", "in an hour"
    m = DURATION_RE.search(t)
    if m:
        qty = m.group(1)
        n = float(qty) if qty[0].isdigit() else _NUM_WORDS[qty]
        unit = m.group(2)
        delta = timedelta(hours=n) if unit.startswith("h") else timedelta(minutes=n)
        target = _round5(now + delta)
        label = _fmt_clock(target.hour, target.minute)
        if target.date() != now.date():
            label = "tomorrow " + label
        return TimeInfo(label, target, ((m.start(), m.end()),))

    day = None
    spans = []
    m_t = TOMORROW_RE.search(t)
    if m_t:
        day = "tomorrow"
        spans.append(m_t.span())
    else:
        m_w = WEEKDAY_RE.search(t)
        if m_w:
            day = m_w.group(1)
            spans.append(m_w.span())

    # 2) a clock time: "2pm", "2:30 pm", "14:00", "at 5"
    hour = minute = None
    meridiem = None
    clock_span = None
    for rx in (MERIDIEM_RE, COLON_RE, CONTEXT_HOUR_RE):
        cm = rx.search(t)
        if not cm:
            continue
        h = int(cm.group(1))
        mi = int(cm.group(2)) if cm.group(2) else 0
        if rx is MERIDIEM_RE:
            if not 1 <= h <= 12:
                continue
            meridiem = "am" if cm.group(3) == "a" else "pm"
        elif h > 23:
            continue
        hour, minute, clock_span = h, mi, cm.span()
        break
    if hour is None and (nm := NOON_RE.search(t)):
        hour, minute, meridiem, clock_span = 12, 0, "pm", nm.span()

    pm = PART_RE.search(t)
    if hour is not None:
        h24, rolled = _resolve_clock(hour, minute, meridiem, now, day is not None)
        label = _fmt_clock(h24, minute)
        spans.append(clock_span)
        if day:
            label = f"{day} {label}"
        elif rolled:
            label = f"tomorrow {label}"
        base = now
        if day == "tomorrow" or rolled:
            base = now + timedelta(days=1)
        elif day:
            base = _next_weekday(now, day)
        target = base.replace(hour=h24, minute=minute, second=0, microsecond=0)
        return TimeInfo(label, target, tuple(spans))

    # 3) words only: "tomorrow morning", "monday", "tonight", "this afternoon"
    if day:
        label = day
        if pm:
            label += " " + pm.group(1)
            spans.append(pm.span())
        return TimeInfo(label, None, tuple(spans))
    for rx, label in SPECIAL_RES:
        sm = rx.search(t)
        if sm:
            return TimeInfo(label, None, (sm.span(),))
    return None


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------
def _clean(text: str) -> str:
    t = _norm_apostrophes(text).lower()
    t = re.sub(r"@\w+", " ", t)                      # drop @mentions
    t = NOT_LOADED_RE.sub(" empty ", t)               # "not loaded" == empty
    for rx in NOISE_RES:                              # "any loads available" etc.
        t = rx.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def _only_time(t: str, tinfo: TimeInfo) -> bool:
    """True when nothing but the time (plus filler words) is in the message."""
    chars = list(t)
    for s, e in tinfo.spans:
        for i in range(s, e):
            chars[i] = " "
    rest = "".join(chars)
    rest = re.sub(r"(?<!\w)(?:at|by|around|about|after|until|till|before|i'll|ill|i|will|be|"
                  r"then|probably|approx|approximately|like|in|the|a|an|on|ready|around)(?!\w)",
                  " ", rest)
    return re.sub(r"[\W_]+", "", rest) == ""


def parse(text: str, now: datetime) -> Parsed:
    t = _clean(text)
    words = len(t.split())
    zip_code = extract_zip(t)
    tinfo = extract_time(t, now)
    question = "?" in t
    avail = bool(AVAIL_RE.search(t) or READY_STRONG_RE.search(t))
    if tinfo and not avail and OTHER_TIME_RE.search(t):
        tinfo = None                                  # "delivering at 3pm" is not availability

    def make(intent: Intent) -> Parsed:
        pure = bool(tinfo) and _only_time(t, tinfo)
        return Parsed(intent, zip_code, tinfo, words, question, pure)

    loaded = bool(LOADED_RE.search(t) or LOADED_PHRASE_RE.search(t))
    not_now = bool(NOT_NOW_RE.search(t))
    no_longer = bool(NO_LONGER_RE.search(t))
    hedge = bool(HEDGE_RE.search(t))
    ready_weak = bool(READY_WEAK_RE.search(t))
    unloaded = bool(UNLOADED_RE.search(t))
    until = bool(UNTIL_RE.search(t))
    will = bool(WILL_RE.search(t))
    later = bool(LATER_RE.search(t))
    now_marker = bool(NOW_RE.search(t))

    if hedge and (avail or not_now or loaded or ready_weak or unloaded):
        return make(Intent.AMBIGUOUS)

    if no_longer:
        return make(Intent.AVAILABLE_LATER if tinfo else Intent.UNAVAILABLE)

    if not_now:
        return make(Intent.AVAILABLE_LATER if tinfo else Intent.NOT_YET)

    if loaded:
        if avail and (tinfo or until):
            return make(Intent.AVAILABLE_LATER)
        if tinfo and until:
            return make(Intent.AVAILABLE_LATER)
        if avail and (later or will):
            return make(Intent.AVAILABLE_LATER)
        return make(Intent.UNAVAILABLE)

    if avail:
        if tinfo:
            return make(Intent.AVAILABLE_LATER)
        if later or (will and not now_marker):
            return make(Intent.AVAILABLE_LATER)
        return make(Intent.AVAILABLE_NOW)

    if ready_weak:
        return make(Intent.READY_WEAK)

    if unloaded:
        return make(Intent.AMBIGUOUS)

    if zip_code and (ZIP_ALONE_RE.fullmatch(t) or ZIP_CTX_RE.search(t)):
        return make(Intent.ZIP_ONLY)

    if tinfo:
        return make(Intent.TIME_ONLY)

    if YES_RE.fullmatch(t):
        return make(Intent.YES)
    if NO_RE.fullmatch(t):
        return make(Intent.NO)

    return make(Intent.NONE)
