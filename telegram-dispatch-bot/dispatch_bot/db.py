"""SQLite storage: drivers, settings, and bookkeeping that prevents duplicates."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS drivers (
    telegram_user_id  INTEGER PRIMARY KEY,
    name              TEXT NOT NULL,
    username          TEXT,
    status            TEXT NOT NULL DEFAULT 'unknown',   -- available | later | unavailable | unknown
    zip_code          TEXT,
    zip_updated_at    TEXT,
    available_at_text TEXT,
    available_at_ts   TEXT,
    awaiting          TEXT,                               -- NULL | zip | time | confirm
    active            INTEGER NOT NULL DEFAULT 1,
    updated_at        TEXT NOT NULL,
    notified_key      TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS processed_updates (
    update_id INTEGER PRIMARY KEY,
    seen_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS processed_messages (
    chat_id    INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    seen_at    TEXT NOT NULL,
    PRIMARY KEY (chat_id, message_id)
);
CREATE TABLE IF NOT EXISTS scheduled_runs (
    kind     TEXT NOT NULL,
    run_date TEXT NOT NULL,
    sent_at  TEXT NOT NULL,
    PRIMARY KEY (kind, run_date)
);
"""

_DRIVER_FIELDS = {
    "name", "username", "status", "zip_code", "zip_updated_at", "available_at_text",
    "available_at_ts", "awaiting", "active", "updated_at", "notified_key",
}


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@dataclass
class Driver:
    telegram_user_id: int
    name: str
    username: str | None
    status: str
    zip_code: str | None
    zip_updated_at: str | None
    available_at_text: str | None
    available_at_ts: str | None
    awaiting: str | None
    active: int
    updated_at: str
    notified_key: str | None


class Database:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None -> we control transactions explicitly.
        self.conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._in_tx = False
        self.init()

    # -- setup / lifecycle -------------------------------------------------
    def init(self) -> None:
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self):
        """All-or-nothing block. Nested use simply joins the outer transaction."""
        if self._in_tx:
            yield
            return
        self.conn.execute("BEGIN IMMEDIATE")
        self._in_tx = True
        try:
            yield
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        finally:
            self._in_tx = False

    def backup_to(self, dest: str) -> None:
        """Consistent copy of the database (safe while the bot is running)."""
        target = sqlite3.connect(dest)
        try:
            self.conn.backup(target)
        finally:
            target.close()

    # -- settings ------------------------------------------------------------
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row and row["value"] is not None else default

    def set_setting(self, key: str, value: str | None) -> None:
        self.conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    # -- duplicate protection -------------------------------------------------
    def claim_update(self, update_id: int, now: datetime) -> bool:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO processed_updates(update_id, seen_at) VALUES(?,?)",
            (update_id, iso(now)))
        return cur.rowcount == 1

    def claim_message(self, chat_id: int, message_id: int, now: datetime) -> bool:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO processed_messages(chat_id, message_id, seen_at) VALUES(?,?,?)",
            (chat_id, message_id, iso(now)))
        return cur.rowcount == 1

    def claim_run(self, kind: str, run_date: str, now: datetime) -> bool:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO scheduled_runs(kind, run_date, sent_at) VALUES(?,?,?)",
            (kind, run_date, iso(now)))
        return cur.rowcount == 1

    def release_run(self, kind: str, run_date: str) -> None:
        self.conn.execute("DELETE FROM scheduled_runs WHERE kind=? AND run_date=?", (kind, run_date))

    def prune(self, now: datetime, days: int = 7) -> None:
        cutoff = iso(now - timedelta(days=days))
        self.conn.execute("DELETE FROM processed_updates WHERE seen_at < ?", (cutoff,))
        self.conn.execute("DELETE FROM processed_messages WHERE seen_at < ?", (cutoff,))

    # -- drivers ---------------------------------------------------------------
    @staticmethod
    def _driver(row) -> Driver | None:
        return Driver(**dict(row)) if row else None

    def get_driver(self, user_id: int) -> Driver | None:
        return self._driver(self.conn.execute(
            "SELECT * FROM drivers WHERE telegram_user_id=?", (user_id,)).fetchone())

    def ensure_driver(self, user_id: int, name: str, username: str | None, now: datetime) -> Driver:
        """Create the record if new; always refresh display name and re-activate."""
        self.conn.execute(
            "INSERT INTO drivers(telegram_user_id, name, username, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(telegram_user_id) DO UPDATE SET name=excluded.name, "
            "username=excluded.username, active=1",
            (user_id, name, username, iso(now)))
        return self.get_driver(user_id)

    def update_driver(self, user_id: int, **fields) -> None:
        bad = set(fields) - _DRIVER_FIELDS
        if bad:
            raise ValueError(f"Unknown driver fields: {bad}")
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE drivers SET {sets} WHERE telegram_user_id=?",
                          (*fields.values(), user_id))

    def list_drivers(self, active_only: bool = True) -> list[Driver]:
        sql = "SELECT * FROM drivers" + (" WHERE active=1" if active_only else "")
        rows = self.conn.execute(sql + " ORDER BY updated_at ASC, telegram_user_id ASC").fetchall()
        return [self._driver(r) for r in rows]

    def find_by_name(self, fragment: str) -> list[Driver]:
        like = f"%{fragment.lower()}%"
        rows = self.conn.execute(
            "SELECT * FROM drivers WHERE active=1 AND (lower(name) LIKE ? OR lower(COALESCE(username,'')) LIKE ?)",
            (like, like)).fetchall()
        return [self._driver(r) for r in rows]
