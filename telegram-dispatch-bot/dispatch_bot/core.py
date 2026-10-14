"""The brain of the bot. It has NO dependency on Telegram or aiogram:

    incoming message  ->  Core.handle_message()  ->  list of Outgoing messages

That keeps it simple to test (with mock messages) and keeps the Telegram part tiny.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from . import formatting as fmt
from . import messages as M
from .config import Config, ConfigError, validate_time, validate_timezone
from .db import Database, Driver, iso, parse_iso
from .parser import MAX_WORDS, Intent, TimeInfo, parse
from .scheduler import is_greeting_due

log = logging.getLogger("dispatch_bot.core")

ADMIN_COMMANDS = {"available", "status", "refresh", "remove", "pause", "resume",
                  "setgroup", "settime", "settimezone", "schedule"}


@dataclass
class IncomingMessage:
    """A Telegram message reduced to the facts the bot needs."""
    chat_id: int
    chat_type: str                       # "private", "group", "supergroup"
    message_id: int
    user_id: int | None
    user_name: str
    text: str | None
    update_id: int | None = None
    username: str | None = None
    is_bot: bool = False
    reply_to_bot: bool = False           # this message replies to one of the bot's messages
    reply_to_user_id: int | None = None  # author of the replied-to message (if a human)
    mentions_bot: bool = False


@dataclass
class Outgoing:
    chat_id: int
    text: str
    reply_to_message_id: int | None = None
    parse_mode: str | None = None


@dataclass
class GreetingJob:
    run_date: str
    outgoing: Outgoing


class Core:
    def __init__(self, db: Database, cfg: Config, now_fn=None, bot_username: str | None = None):
        self.db = db
        self.cfg = cfg
        self.bot_username = (bot_username or "").lstrip("@").lower()
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        # The .env GROUP_CHAT_ID only seeds the setting; /setgroup can change it later.
        if cfg.group_chat_id is not None and db.get_setting("group_chat_id") is None:
            db.set_setting("group_chat_id", str(cfg.group_chat_id))

    # ------------------------------------------------------------------ settings
    def now(self) -> datetime:
        return self._now_fn()

    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.db.get_setting("timezone", self.cfg.timezone))

    def greeting_time(self) -> time:
        h, m = self.db.get_setting("greeting_time", self.cfg.greeting_time).split(":")
        return time(int(h), int(m))

    def paused(self) -> bool:
        return self.db.get_setting("paused", "0") == "1"

    def group_chat_id(self) -> int | None:
        value = self.db.get_setting("group_chat_id")
        return int(value) if value else None

    def is_admin(self, user_id: int | None) -> bool:
        return user_id in self.cfg.admin_ids

    def startup(self) -> None:
        """Housekeeping when the bot starts."""
        self.db.prune(self.now())

    # ------------------------------------------------------------------ entry point
    def handle_message(self, msg: IncomingMessage) -> list[Outgoing]:
        """Process one incoming Telegram message and return what to send (possibly nothing)."""
        if msg.is_bot or msg.user_id is None or not msg.text:
            return []
        now = self.now()
        with self.db.transaction():
            # Never process the same Telegram update / message twice.
            if msg.update_id is not None and not self.db.claim_update(msg.update_id, now):
                log.info("Duplicate update %s ignored.", msg.update_id)
                return []
            if not self.db.claim_message(msg.chat_id, msg.message_id, now):
                log.info("Duplicate message %s/%s ignored.", msg.chat_id, msg.message_id)
                return []
            return self._dispatch(msg, msg.text.strip(), now)

    def _dispatch(self, msg: IncomingMessage, text: str, now: datetime) -> list[Outgoing]:
        if text.startswith("/"):
            return self._command(msg, text, now)
        if msg.chat_type == "private":
            return [self._reply(msg, M.PRIVATE_HINT)]
        group = self.group_chat_id()
        if group is None or msg.chat_id != group:
            return []                                    # not our dispatch group
        if self.is_admin(msg.user_id) and not self.cfg.treat_admins_as_drivers:
            return []                                    # dispatchers' chatter is not tracked
        result = self._availability(msg, text, now)
        if result is None:
            return []
        reply, note = result
        out: list[Outgoing] = []
        if reply and not self.paused():                  # paused = no automatic group messages
            out.append(self._reply(msg, reply))
        if note:
            out.extend(self._admin_notifications(note))
        return out

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _reply(msg: IncomingMessage, text: str) -> Outgoing:
        return Outgoing(msg.chat_id, text, msg.message_id)

    def _admin_notifications(self, line: str) -> list[Outgoing]:
        if not self.cfg.notify_admins:
            return []
        return [Outgoing(admin, f"✅ Driver available: {line}") for admin in sorted(self.cfg.admin_ids)]

    def _fresh(self, iso_value: str | None, now: datetime) -> bool:
        ts = parse_iso(iso_value)
        return bool(ts and now - ts <= timedelta(hours=self.cfg.zip_fresh_hours))

    def _stale(self, d: Driver, now: datetime) -> bool:
        if self.cfg.stale_hours <= 0:
            return False
        return now - parse_iso(d.updated_at) > timedelta(hours=self.cfg.stale_hours)

    def _awaiting(self, d: Driver | None, now: datetime) -> str | None:
        """What the bot is waiting for from this driver. Expires after the check-in window."""
        if not d or not d.active or not d.awaiting:
            return None
        if now - parse_iso(d.updated_at) > timedelta(hours=self.cfg.checkin_window_hours):
            return None
        return d.awaiting

    def _window_open(self, now: datetime) -> bool:
        """True for a while after a morning greeting or /refresh (drivers are answering it)."""
        ts = parse_iso(self.db.get_setting("checkin_at"))
        return bool(ts and now - ts <= timedelta(hours=self.cfg.checkin_window_hours))

    def _views(self, now: datetime) -> dict[str, list[Driver]]:
        v = {"available": [], "waiting_zip": [], "later": [], "other": [], "stale": []}
        for d in self.db.list_drivers(active_only=True):
            if d.status in ("available", "later") and self._stale(d, now):
                v["stale"].append(d)
            elif d.status == "available":
                v["available" if d.zip_code else "waiting_zip"].append(d)
            elif d.status == "later" and d.available_at_text:
                v["later"].append(d)
            else:
                v["other"].append(d)
        return v

    def available_entries(self, now: datetime | None = None) -> list[str]:
        v = self._views(now or self.now())
        return ([fmt.entry_now(d.name, d.zip_code) for d in v["available"]] +
                [fmt.entry_later(d.name, d.available_at_text) for d in v["later"]])

    # ------------------------------------------------------------------ availability logic
    def _availability(self, msg: IncomingMessage, text: str, now: datetime):
        """Return (reply_text | None, admin_note | None), or None when the message is irrelevant."""
        addressed = msg.reply_to_bot or msg.mentions_bot
        driver = self.db.get_driver(msg.user_id)
        awaiting = self._awaiting(driver, now)
        window = self._window_open(now)
        parsed = parse(text, now.astimezone(self.tz()))

        if parsed.word_count > MAX_WORDS and not addressed:
            return None                                  # long chat messages are not status updates
        if parsed.is_question and not (addressed or awaiting):
            return None                                  # "any loads available?" etc.

        known = bool(driver and driver.active and driver.status in ("available", "later"))
        engaged = bool(awaiting or addressed or known)
        intent = parsed.intent

        if intent is Intent.AVAILABLE_NOW:
            return self._set_available(msg, parsed.zip_code, now)
        if intent is Intent.AVAILABLE_LATER:
            if parsed.time:
                return self._set_later(msg, parsed.zip_code, parsed.time, now)
            return self._ask_time(msg, parsed.zip_code, now)
        if intent is Intent.NOT_YET and (engaged or window):
            return self._ask_time(msg, parsed.zip_code, now)
        if intent is Intent.UNAVAILABLE and engaged:
            return self._set_unavailable(msg, now)
        if intent is Intent.ZIP_ONLY and (engaged or window):
            return self._set_zip(msg, parsed.zip_code, now)
        if intent is Intent.TIME_ONLY and (
                awaiting == "time" or addressed or (window and parsed.pure_time)):
            return self._set_later(msg, parsed.zip_code, parsed.time, now)
        if intent is Intent.YES and awaiting == "confirm":
            return self._set_available(msg, None, now)
        if intent is Intent.NO and awaiting == "confirm":
            return self._ask_time(msg, None, now)
        if intent is Intent.READY_WEAK and (engaged or window):
            return self._clarify(msg, now)
        if intent is Intent.AMBIGUOUS:
            return self._clarify(msg, now)
        return None

    def _driver_for(self, msg: IncomingMessage, now: datetime) -> Driver:
        name = re.sub(r"\s+", " ", msg.user_name or "").strip() or f"Driver {msg.user_id}"
        return self.db.ensure_driver(msg.user_id, name, msg.username, now)

    def _set_available(self, msg, zip_in_msg, now):
        d = self._driver_for(msg, now)
        zip_code, was_listed = zip_in_msg, d.status == "available"
        if not zip_code and d.zip_code and (was_listed or self._fresh(d.zip_updated_at, now)):
            zip_code = d.zip_code                        # reuse a recent ZIP
        fields = dict(status="available", available_at_text=None, available_at_ts=None,
                      awaiting=None if zip_code else "zip", updated_at=iso(now))
        if zip_in_msg:
            fields.update(zip_code=zip_in_msg, zip_updated_at=iso(now))
        elif not zip_code:
            fields.update(zip_code=None, zip_updated_at=None)   # old ZIP is outdated: ask again
        note = None
        if zip_code:
            if d.notified_key != zip_code:
                note = fmt.entry_now(d.name, zip_code)
            fields["notified_key"] = zip_code
        else:
            fields["notified_key"] = None
        self.db.update_driver(d.telegram_user_id, **fields)
        log.info("Driver %s -> available (ZIP %s)", d.telegram_user_id, zip_code or "pending")
        if zip_in_msg:
            return M.ZIP_ACK, note
        if zip_code:
            return (M.ALREADY_LISTED.format(zip=zip_code) if was_listed and not note else M.ZIP_ACK), note
        return M.ASK_ZIP, None

    def _set_zip(self, msg, zip_code, now):
        d = self._driver_for(msg, now)
        awaiting = self._awaiting(d, now)
        fields = dict(zip_code=zip_code, zip_updated_at=iso(now), updated_at=iso(now))
        note = None
        if d.status == "available":
            fields["awaiting"] = None
            if d.notified_key != zip_code:
                note = fmt.entry_now(d.name, zip_code)
            fields["notified_key"] = zip_code
            reply = M.ZIP_ACK
        elif d.status == "later":
            reply = M.ZIP_UPDATED.format(zip=zip_code)
        elif awaiting == "time":
            reply = M.ZIP_NOTED_ASK_TIME.format(zip=zip_code)
        else:
            fields["awaiting"] = "confirm"
            reply = M.ZIP_NOTED_ASK_STATUS.format(zip=zip_code)
        self.db.update_driver(d.telegram_user_id, **fields)
        log.info("Driver %s ZIP updated to %s", d.telegram_user_id, zip_code)
        return reply, note

    def _set_later(self, msg, zip_in_msg, tinfo: TimeInfo, now):
        d = self._driver_for(msg, now)
        fields = dict(status="later", available_at_text=tinfo.text,
                      available_at_ts=iso(tinfo.dt) if tinfo.dt else None,
                      awaiting=None, notified_key=None, updated_at=iso(now))
        if zip_in_msg:
            fields.update(zip_code=zip_in_msg, zip_updated_at=iso(now))
        self.db.update_driver(d.telegram_user_id, **fields)
        log.info("Driver %s -> available later (%s)", d.telegram_user_id, tinfo.text)
        return M.TIME_ACK.format(time=tinfo.text), None

    def _ask_time(self, msg, zip_in_msg, now):
        d = self._driver_for(msg, now)
        fields = dict(status="unavailable", available_at_text=None, available_at_ts=None,
                      awaiting="time", notified_key=None, updated_at=iso(now))
        if zip_in_msg:
            fields.update(zip_code=zip_in_msg, zip_updated_at=iso(now))
        self.db.update_driver(d.telegram_user_id, **fields)
        log.info("Driver %s -> not available yet, asked for time", d.telegram_user_id)
        return M.ASK_TIME, None

    def _set_unavailable(self, msg, now):
        d = self._driver_for(msg, now)
        self.db.update_driver(d.telegram_user_id, status="unavailable", available_at_text=None,
                              available_at_ts=None, awaiting=None, notified_key=None,
                              updated_at=iso(now))
        log.info("Driver %s -> unavailable", d.telegram_user_id)
        return M.UNAVAILABLE_ACK, None

    def _clarify(self, msg, now):
        d = self._driver_for(msg, now)
        self.db.update_driver(d.telegram_user_id, awaiting="confirm", updated_at=iso(now))
        return M.CLARIFY, None

    # ------------------------------------------------------------------ commands
    def _command(self, msg: IncomingMessage, text: str, now: datetime) -> list[Outgoing]:
        parts = text.split(None, 1)
        head, args = parts[0], (parts[1].strip() if len(parts) > 1 else "")
        cmd, _, target = head[1:].partition("@")
        if target and self.bot_username and target.lower() != self.bot_username:
            return []                                    # addressed to a different bot
        cmd = cmd.lower()
        handlers = {
            "start": self._cmd_start, "help": self._cmd_help, "myid": self._cmd_myid,
            "available": self._cmd_available, "status": self._cmd_status,
            "refresh": self._cmd_refresh, "remove": self._cmd_remove,
            "pause": self._cmd_pause, "resume": self._cmd_resume,
            "setgroup": self._cmd_setgroup, "settime": self._cmd_settime,
            "settimezone": self._cmd_settimezone, "schedule": self._cmd_schedule,
        }
        handler = handlers.get(cmd)
        if handler is None:
            return []
        if cmd in ADMIN_COMMANDS and not self.is_admin(msg.user_id):
            log.warning("Unauthorized /%s from user %s", cmd, msg.user_id)
            return [self._reply(msg, M.NOT_AUTHORIZED)]
        return handler(msg, args, now)

    def _cmd_start(self, msg, args, now):
        text = M.START_TEXT
        if self.is_admin(msg.user_id) and self.group_chat_id() is None:
            text += ("\n\nSetup step: add me to your dispatch group and send /setgroup there "
                     "so I know which group to work in.")
        return [self._reply(msg, text)]

    def _cmd_help(self, msg, args, now):
        text = M.HELP_DRIVERS + (M.HELP_ADMIN if self.is_admin(msg.user_id) else "")
        return [self._reply(msg, text)]

    def _cmd_myid(self, msg, args, now):
        return [self._reply(msg, f"Your Telegram user ID: {msg.user_id}\nThis chat's ID: {msg.chat_id}")]

    def _cmd_available(self, msg, args, now):
        entries = self.available_entries(now)
        if not entries:
            return [self._reply(msg, "No drivers on the available list right now.")]
        return [self._reply(msg, chunk) for chunk in fmt.chunk_entries(entries)]

    def _cmd_status(self, msg, args, now):
        v = self._views(now)
        lines = [f"Available now (ZIP confirmed): {len(v['available'])}"]
        if v["waiting_zip"]:
            names = ", ".join(fmt.clean_name(d.name) for d in v["waiting_zip"])
            lines.append(f"Available, waiting for ZIP: {len(v['waiting_zip'])} ({names})")
        lines.append(f"Expected to be available later: {len(v['later'])}")
        lines.append(f"Not available / no update: {len(v['other'])}")
        if v["stale"]:
            lines.append(f"Hidden as outdated (no update in {self.cfg.stale_hours}h): {len(v['stale'])}. "
                         "Use /refresh to ask them again.")
        if self.paused():
            lines.append("⏸ Automatic messages are PAUSED.")
        return [self._reply(msg, "\n".join(lines))]

    def _cmd_refresh(self, msg, args, now):
        group = self.group_chat_id()
        if group is None:
            return [self._reply(msg, "I don't know the dispatch group yet. Send /setgroup inside the group first.")]
        if self.paused():
            return [self._reply(msg, "Automatic messages are paused. Send /resume first.")]
        last = parse_iso(self.db.get_setting("last_refresh_at"))
        cooldown = timedelta(minutes=self.cfg.refresh_cooldown_minutes)
        if last and now - last < cooldown:
            wait = max(1, int((cooldown - (now - last)).total_seconds() // 60) + 1)
            return [self._reply(msg, f"A refresh was just sent. Please wait about {wait} more minute(s).")]
        self.db.set_setting("last_refresh_at", iso(now))
        self.db.set_setting("checkin_at", iso(now))
        text = html.escape(M.REFRESH, quote=False)
        waiting = self._views(now)["waiting_zip"]
        if waiting:
            names = ", ".join(
                f'<a href="tg://user?id={d.telegram_user_id}">{html.escape(fmt.clean_name(d.name), quote=False)}</a>'
                for d in waiting)
            text += "\n\n" + html.escape(M.REFRESH_NEED_ZIP, quote=False).replace("{names}", names)
        out = [Outgoing(group, text, parse_mode="HTML")]
        if msg.chat_id != group:
            out.append(self._reply(msg, "Refresh message sent to the dispatch group."))
        return out

    def _cmd_remove(self, msg, args, now):
        target: Driver | None = None
        if args:
            if args.lstrip("-").isdigit():
                target = self.db.get_driver(int(args))
            else:
                matches = self.db.find_by_name(args)
                if len(matches) > 1:
                    listing = "; ".join(f"{fmt.clean_name(d.name)} (ID {d.telegram_user_id})" for d in matches)
                    return [self._reply(msg, f"Several drivers match: {listing}. Use /remove <ID>.")]
                target = matches[0] if matches else None
        elif msg.reply_to_user_id:
            target = self.db.get_driver(msg.reply_to_user_id)
        else:
            return [self._reply(msg, "Usage: /remove <name or ID> (or reply to the driver's message with /remove).")]
        if not target or not target.active:
            return [self._reply(msg, "I couldn't find an active driver record for that.")]
        self.db.update_driver(target.telegram_user_id, active=0, status="unavailable", awaiting=None,
                              available_at_text=None, available_at_ts=None, notified_key=None)
        log.info("Driver %s deactivated by %s", target.telegram_user_id, msg.user_id)
        return [self._reply(msg, f"Removed {fmt.clean_name(target.name)} from the list. "
                                 "They'll be added back if they send a new availability update.")]

    def _cmd_pause(self, msg, args, now):
        self.db.set_setting("paused", "1")
        return [self._reply(msg, "⏸ Paused. I won't send the morning message or reply to drivers in the group. "
                                 "I'll still record updates quietly. Send /resume to restart.")]

    def _cmd_resume(self, msg, args, now):
        self.db.set_setting("paused", "0")
        return [self._reply(msg, "▶️ Resumed. Automatic messages are back on.")]

    def _cmd_setgroup(self, msg, args, now):
        if msg.chat_type == "private":
            return [self._reply(msg, "Send /setgroup inside your dispatch group, not in a private chat.")]
        self.db.set_setting("group_chat_id", str(msg.chat_id))
        log.info("Dispatch group set to %s by %s", msg.chat_id, msg.user_id)
        return [self._reply(msg, "✅ This group is now the dispatch group.")]

    def _cmd_settime(self, msg, args, now):
        try:
            value = validate_time(args)
        except ConfigError as exc:
            return [self._reply(msg, f"{exc}")]
        self.db.set_setting("greeting_time", value)
        return [self._reply(msg, f"Morning message time set to {value} ({self.tz().key}).")]

    def _cmd_settimezone(self, msg, args, now):
        try:
            value = validate_timezone(args.strip())
        except ConfigError as exc:
            return [self._reply(msg, f"{exc}")]
        self.db.set_setting("timezone", value)
        return [self._reply(msg, f"Timezone set to {value}. Morning message time: {self.greeting_time():%H:%M}.")]

    def _cmd_schedule(self, msg, args, now):
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        days = ",".join(names[i] for i in sorted(self.cfg.greeting_days))
        group = self.group_chat_id()
        lines = [
            f"Morning message: {self.greeting_time():%H:%M} {self.tz().key} ({days})",
            f"Status: {'PAUSED' if self.paused() else 'running'}",
            f"Dispatch group: {'set (' + str(group) + ')' if group else 'NOT set. Send /setgroup in the group'}",
            f"Local time now: {now.astimezone(self.tz()):%Y-%m-%d %H:%M}",
        ]
        return [self._reply(msg, "\n".join(lines))]

    # ------------------------------------------------------------------ scheduled greeting
    def scheduled_greeting(self, now: datetime | None = None) -> GreetingJob | None:
        """Return the morning greeting if it is due and has not been sent today, else None.

        The 'claim' row in the database guarantees one greeting per day even if this is
        called repeatedly or the bot restarts.
        """
        now = now or self.now()
        group = self.group_chat_id()
        if group is None or self.paused():
            return None
        local = now.astimezone(self.tz())
        if not is_greeting_due(local, self.greeting_time(), self.cfg.greeting_days,
                               self.cfg.greeting_catchup_minutes):
            return None
        run_date = local.date().isoformat()
        with self.db.transaction():
            if not self.db.claim_run("greeting", run_date, now):
                return None
            self.db.set_setting("checkin_at", iso(now))
        return GreetingJob(run_date, Outgoing(group, self.cfg.morning_message))

    def release_greeting(self, run_date: str) -> None:
        self.db.release_run("greeting", run_date)
