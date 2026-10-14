"""Settings come from environment variables (normally from the .env file)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_MORNING_MESSAGE = (
    "Good morning, boss! Are you empty and available today? "
    "If you're ready for a load, reply AVAILABLE. "
    "If you're not available yet, tell us what time you'll be ready."
)

_DAY_NAMES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


class ConfigError(Exception):
    """Raised with a plain-English message when .env is wrong."""


@dataclass(frozen=True)
class Config:
    bot_token: str = ""
    admin_ids: frozenset = frozenset()
    group_chat_id: int | None = None
    db_path: str = "data/dispatch.sqlite3"
    timezone: str = "America/Chicago"
    greeting_time: str = "07:00"
    greeting_days: frozenset = frozenset(range(7))
    morning_message: str = DEFAULT_MORNING_MESSAGE
    greeting_catchup_minutes: int = 120
    checkin_window_hours: int = 12
    refresh_cooldown_minutes: int = 30
    stale_hours: int = 18
    zip_fresh_hours: int = 3
    treat_admins_as_drivers: bool = False
    notify_admins: bool = True
    log_level: str = "INFO"
    log_dir: str = "logs"


def validate_time(value: str) -> str:
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", value or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ConfigError(f"'{value}' is not a valid time. Use 24-hour HH:MM, for example 07:30.")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ConfigError(
            f"'{value}' is not a valid timezone. Examples: America/Chicago, "
            "America/New_York, America/Los_Angeles."
        ) from None
    return value


def _int(env, key, default, minimum=0):
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{key} must be a whole number (you wrote '{raw}').") from None
    if value < minimum:
        raise ConfigError(f"{key} must be {minimum} or more.")
    return value


def _bool(env, key, default):
    raw = env.get(key, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


def _days(raw: str) -> frozenset:
    if not raw.strip():
        return frozenset(range(7))
    out = set()
    for part in re.split(r"[,\s]+", raw.strip().lower()):
        if not part:
            continue
        key = part[:3]
        if key not in _DAY_NAMES:
            raise ConfigError(f"GREETING_DAYS has an unknown day '{part}'. Use Mon,Tue,Wed,Thu,Fri,Sat,Sun.")
        out.add(_DAY_NAMES[key])
    return frozenset(out)


def load_config(env=None, require_token: bool = True) -> Config:
    """Build a Config from environment variables (loads .env first when run for real)."""
    if env is None:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:  # python-dotenv missing: fall back to real environment only
            pass
        env = os.environ

    token = env.get("BOT_TOKEN", "").strip()
    if require_token and (not token or token.lower().startswith("paste")):
        raise ConfigError("BOT_TOKEN is missing. Open the .env file and paste the token from @BotFather.")

    admin_ids = set()
    for part in re.split(r"[,\s;]+", env.get("ADMIN_IDS", "").strip()):
        if not part:
            continue
        if not re.fullmatch(r"\d+", part):
            raise ConfigError(f"ADMIN_IDS must contain only numbers separated by commas (found '{part}').")
        admin_ids.add(int(part))
    if require_token and not admin_ids:
        raise ConfigError("ADMIN_IDS is empty. Add at least one dispatcher's Telegram user ID "
                          "(send /myid to the bot to find it).")

    group_raw = env.get("GROUP_CHAT_ID", "").strip()
    try:
        group_chat_id = int(group_raw) if group_raw else None
    except ValueError:
        raise ConfigError("GROUP_CHAT_ID must be a number like -1001234567890 (or leave it empty "
                          "and use /setgroup inside the group).") from None

    return Config(
        bot_token=token,
        admin_ids=frozenset(admin_ids),
        group_chat_id=group_chat_id,
        db_path=env.get("DB_PATH", "").strip() or "data/dispatch.sqlite3",
        timezone=validate_timezone(env.get("TIMEZONE", "").strip() or "America/Chicago"),
        greeting_time=validate_time(env.get("GREETING_TIME", "").strip() or "07:00"),
        greeting_days=_days(env.get("GREETING_DAYS", "")),
        morning_message=env.get("MORNING_MESSAGE", "").strip().replace("\\n", "\n") or DEFAULT_MORNING_MESSAGE,
        greeting_catchup_minutes=_int(env, "GREETING_CATCHUP_MINUTES", 120),
        checkin_window_hours=_int(env, "CHECKIN_WINDOW_HOURS", 12, 1),
        refresh_cooldown_minutes=_int(env, "REFRESH_COOLDOWN_MINUTES", 30),
        stale_hours=_int(env, "STALE_HOURS", 18),
        zip_fresh_hours=_int(env, "ZIP_FRESH_HOURS", 3),
        treat_admins_as_drivers=_bool(env, "TREAT_ADMINS_AS_DRIVERS", False),
        notify_admins=_bool(env, "NOTIFY_ADMINS", True),
        log_level=(env.get("LOG_LEVEL", "").strip() or "INFO").upper(),
        log_dir=env.get("LOG_DIR", "").strip() or "logs",
    )
