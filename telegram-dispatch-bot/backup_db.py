"""Make a safe copy of the database (works while the bot is running).

    python backup_db.py                -> backups/dispatch-YYYYMMDD-HHMMSS.sqlite3
Keeps the 30 most recent backups.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from dispatch_bot.config import ConfigError, load_config
from dispatch_bot.db import Database

KEEP = 30


def main() -> int:
    try:
        cfg = load_config(require_token=False)
    except ConfigError as exc:
        print(f"Configuration problem: {exc}")
        return 1
    if not Path(cfg.db_path).exists():
        print(f"No database found at {cfg.db_path}. Has the bot been started yet?")
        return 1
    folder = Path("backups")
    folder.mkdir(exist_ok=True)
    dest = folder / f"dispatch-{datetime.now():%Y%m%d-%H%M%S}.sqlite3"
    db = Database(cfg.db_path)
    try:
        db.backup_to(str(dest))
    finally:
        db.close()
    print(f"Backup saved: {dest}")
    for old in sorted(folder.glob("dispatch-*.sqlite3"))[:-KEEP]:
        old.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
