"""Try the bot's logic WITHOUT Telegram. Nothing is sent anywhere; no token needed.

    python simulate.py            interactive: type   Name: message
    python simulate.py --demo     run a short built-in conversation

In interactive mode, the dispatcher is called "boss". Examples:
    Mohammad Ibrahim: Available
    Mohammad Ibrahim: 19237
    Juan Miguel: I'll be empty at 2 PM
    boss: /available
Type  quit  to leave. Data is kept in memory only (nothing is saved).
"""

from __future__ import annotations

import itertools
import sys
from datetime import datetime, timezone

from dispatch_bot.config import Config
from dispatch_bot.core import Core, IncomingMessage
from dispatch_bot.db import Database

GROUP, ADMIN = -1001, 1

DEMO = [
    ("Mohammad Ibrahim", "Good morning boss, available"),
    ("Mohammad Ibrahim", "19237"),
    ("Juan Miguel", "I'll be empty at 2 PM"),
    ("Chris Lee", "Any loads available?"),
    ("Chris Lee", "I'm empty in 60007"),
    ("Sam Carter", "Not yet"),
    ("Sam Carter", "Tomorrow morning"),
    ("Chris Lee", "I got a load"),
    ("boss", "/available"),
    ("boss", "/status"),
]


class Sim:
    def __init__(self):
        cfg = Config(admin_ids=frozenset({ADMIN}), group_chat_id=GROUP)
        self.core = Core(Database(":memory:"), cfg, bot_username="DispatchBot")
        self.ids, self.counter = {"boss": ADMIN}, itertools.count(1)
        # Pretend the morning message went out so bare replies ("19237") are understood.
        self.core.db.set_setting("checkin_at", self.core.now().isoformat())

    def say(self, name: str, text: str) -> None:
        uid = self.ids.setdefault(name, 100 + len(self.ids))
        n = next(self.counter)
        print(f"  {name}: {text}")
        for out in self.core.handle_message(IncomingMessage(
                GROUP, "supergroup", n, uid, name, text, update_id=n)):
            who = "BOT" if out.chat_id == GROUP else "BOT -> private message to dispatcher"
            print(f"    [{who}] {out.text}")


def main() -> None:
    sim = Sim()
    if "--demo" in sys.argv:
        for name, text in DEMO:
            sim.say(name, text)
        return
    print(__doc__)
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if line.lower() in {"quit", "exit"}:
            break
        if ":" not in line:
            print("  Format:  Name: message")
            continue
        name, text = line.split(":", 1)
        sim.say(name.strip(), text.strip())


if __name__ == "__main__":
    main()
