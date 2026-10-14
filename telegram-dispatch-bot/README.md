# Telegram Driver Availability & Dispatch Assistant

A small Telegram bot for your dispatch group. Every morning it asks drivers if they are empty,
collects ZIP codes and expected-ready times, keeps one up-to-date record per driver, and gives
dispatchers a copy-ready list with `/available`.

* No paid AI service: it understands messages with simple phrase rules (English, plus a few Turkish/Uzbek/Russian words).
* Data is stored in a local SQLite file, so it survives restarts.
* It does **not** search for loads and never claims to. (The reply "Checking loads for you" is just the
  wording you asked for; edit it in `dispatch_bot/messages.py` if you prefer.)

Example `/available` output:

```
Mohammad Ibrahim, 19237; Chris Lee, 60007; Juan Miguel, will be available 2pm
```

---

## 1. Install (Windows)

1. Install **Python 3.11 or newer** from <https://www.python.org/downloads/>. On the first installer screen, tick **"Add python.exe to PATH"**.
2. Unzip this project folder somewhere permanent, e.g. `C:\dispatch-bot`.
3. Double-click **`setup.bat`**. It creates a private Python environment, installs the packages, and opens the `.env` settings file in Notepad.

## 2. Create the bot (Telegram's official @BotFather)

1. In Telegram, open **@BotFather** and send `/newbot`.
2. Choose a display name and a username ending in `bot`.
3. BotFather replies with a **token** (`123456789:AAH...`). Paste it into `.env` after `BOT_TOKEN=`. Treat it like a password.
4. **Privacy mode.** By default a bot in a group only sees commands, replies to itself, and @mentions, so it would miss a plain "Available". Choose one:
   * **Recommended:** in @BotFather send `/setprivacy`, pick your bot, choose **Disable**. The bot can then read group messages (it only acts on availability-related ones; it never stores message text).
   * **Minimum access:** leave privacy **enabled**. The bot then only hears drivers who *reply to the bot's messages* (the morning message, ZIP question, etc.) or @mention it. Free-standing messages like "I got loaded" will be missed.
   * Do **not** make the bot a group admin; it does not need it.
   * Changing privacy only takes effect after you **remove the bot from the group and add it again**.

## 3. Add the bot to your dispatch group

1. Open your existing group, **Add member**, search for the bot's username, add it.
2. (Optional but recommended) in @BotFather: `/setjoingroups` is fine as is. If you don't want others adding it elsewhere, set it to **Disable** after adding.

## 4. Set the administrators (dispatchers)

1. Everyone can send **`/myid`** to the bot (in the group or a private chat); it replies with their numeric Telegram ID.
2. Put the dispatchers' IDs in `.env`: `ADMIN_IDS=111111111,222222222`
3. **Each dispatcher should open a private chat with the bot and press Start.** The bot sends them a private
   notification when a driver becomes available with a ZIP, and Telegram only allows that after they pressed Start.
   The bot **never** sends private messages to drivers.

## 5. Start the bot

1. Double-click **`run.bat`**. Leave the window open. You should see `Connected to Telegram as @yourbot`.
2. In the group, an administrator sends **`/setgroup`**. This tells the bot which group is the dispatch group (it ignores all other chats). You only do this once.
3. Check with **`/schedule`**.

## 6. Test it

*Without Telegram:* run `.venv\Scripts\python simulate.py --demo` (or without `--demo` to type your own messages as different drivers).

*In Telegram:* messages from dispatchers are not treated as driver updates, so test with a second account, or set `TREAT_ADMINS_AS_DRIVERS=true` in `.env` while testing alone (and set it back afterwards). Try:

| You send | Bot replies | List shows |
|---|---|---|
| `Available` | asks for your ZIP | nothing yet |
| `19237` | "Got it! Checking loads for you. 👍" (+ private note to dispatchers) | `Name, 19237` |
| `I'll be empty at 2 PM` | "Thanks! I'll update your availability for 2pm." | `Name, will be available 2pm` |
| `My ZIP is now 60007` | "Got it! ..." | `Name, 60007` |
| `I'm loaded now` | "...taken you off the available list." | (removed) |
| `Any loads available?` | nothing | |

## 7. Morning message time and timezone

Defaults: **07:00, America/Chicago**, every day. Change either way:

* In chat (dispatchers): `/settime 06:30` and `/settimezone America/New_York` (these are saved in the database and win over `.env`).
* Or in `.env`: `GREETING_TIME`, `TIMEZONE`, `GREETING_DAYS`, `MORNING_MESSAGE` (then restart the bot).

The message goes out once per day, even if the bot restarts. If your PC was off at the scheduled time, the bot still sends it when it starts within `GREETING_CATCHUP_MINUTES` (default 120). It does not send a "good morning" at 3 pm.

## Commands

| Command | Who | What |
|---|---|---|
| `/start`, `/help`, `/myid` | everyone | explanation, instructions, show my Telegram ID |
| `/available` | dispatchers | current list in the exact required format |
| `/status` | dispatchers | counts: available now, waiting for ZIP, later, not available |
| `/refresh` | dispatchers | asks everyone to update and send their ZIP; at most once per 30 min (`REFRESH_COOLDOWN_MINUTES`). Works from a private chat too. |
| `/remove <name or ID>` | dispatchers | deactivate a record (or reply to the driver's message with `/remove`). They are re-added if they send a new update. |
| `/pause`, `/resume` | dispatchers | pause / resume automatic messages |
| `/setgroup`, `/settime`, `/settimezone`, `/schedule` | dispatchers | setup and settings |

To use `/available` privately (copy into Saved Messages): open a private chat with the bot as a dispatcher and send `/available`.
Telegram bots cannot write into anyone's Saved Messages, so copy the reply and paste it there.

## How the bot decides (so there are no surprises)

* **Identity** is the Telegram user ID, never the display name. Two drivers named "John Smith" stay separate; a name change just updates the record.
* **Available** + no ZIP -> asks for the ZIP; the driver is *not* listed until a ZIP is given. A ZIP from a previous update is reused only if it is under 3 hours old (`ZIP_FRESH_HOURS`).
* **Later** ("at 2 PM", "after 5", "in 3 hours", "tomorrow morning") is saved as a future time, never as available now. "In 3 hours" is converted to a clock time. A bare hour like "after 5" is read as the next time that hour comes round (at 7 am, "5" = 5pm).
* **Loaded / "got a load" / "no longer available"** -> removed from the list, record kept. "Still loaded" or "Not yet" -> the bot asks for an expected time.
* **Unsure** ("maybe", "just unloaded", a bare "ready") -> one short clarifying question; the bot does not guess.
* **Silence on chatter.** It answers only availability-related messages, direct replies to the bot, or @mentions. Questions ("any loads available?"), long messages, delivery times ("delivering at 3pm") and ZIPs in load talk are ignored. Loaded/"not yet" style messages from drivers who aren't on the list are ignored unless they answer the bot.
* **One reply per message.** Telegram update IDs and message IDs are remembered, so a re-delivered update never produces a second reply or a second private notification.
* **Outdated records:** a driver who has not updated for `STALE_HOURS` (18) is hidden from `/available` (shown in `/status`) so yesterday's "available" is not mistaken for today's. Set `STALE_HOURS=0` to turn this off.
* **Pause** stops the morning message and all group replies, but updates are still recorded quietly and commands still answer.
* Dispatchers' own group messages are not tracked as driver updates (unless `TREAT_ADMINS_AS_DRIVERS=true`).

If drivers use words the bot misses, add them to `dispatch_bot/phrases.py` (plain lists of words). All bot sentences are in `dispatch_bot/messages.py`.

## Stop, restart, back up

* **Stop:** press `Ctrl+C` in the bot window or close it. **Restart:** double-click `run.bat`. Data and settings are kept.
* Only run **one copy** of the bot at a time (Telegram rejects a second one with a "Conflict" error).
* **Back up:** double-click `backup.bat` (safe while the bot runs). Copies go to `backups\`, the newest 30 are kept. Or copy `data\dispatch.sqlite3` while the bot is stopped.
* **Restore:** stop the bot, copy a backup over `data\dispatch.sqlite3`, start again.
* **Start automatically with Windows (optional):** Task Scheduler -> Create Basic Task -> "When I log on" -> Start a program -> `run.bat`, with "Start in" set to the project folder. The PC must be on and online for the bot to work.
* Logs are in `logs\bot.log`. They never contain the token or message text.

## Troubleshooting

| Problem | Fix |
|---|---|
| "BOT_TOKEN is missing" | Edit `.env` (token from @BotFather). |
| Bot ignores everything in the group | Run `/setgroup` in the group; check privacy mode (step 2.4) and re-add the bot after changing it. |
| "Not authorized" replies | Your ID is not in `ADMIN_IDS`; send `/myid`, add it, restart. |
| No private notifications | Each dispatcher must press **Start** in a private chat with the bot. |
| "Conflict: terminated by other getUpdates request" | Another copy of the bot is running somewhere. Stop it. |
| Morning message at the wrong hour | `/schedule` shows the timezone in use; fix with `/settimezone`. |

## Automated tests

Double-click `test.bat`, or run `.venv\Scripts\python -m unittest discover -s tests -t . -v`. The tests use mock Telegram messages, a fake clock and an in-memory database: no real token or internet needed. They cover the scheduling, ZIP and time handling, status changes, duplicates, list format, persistence across restarts, admin-only commands, chatter filtering and clarifications.

## Project layout

```
dispatch_bot/core.py            the bot's decisions (no Telegram code)
dispatch_bot/parser.py          phrase / ZIP / time understanding
dispatch_bot/phrases.py         word lists you can edit
dispatch_bot/messages.py        every bot sentence
dispatch_bot/db.py              SQLite storage
dispatch_bot/scheduler.py       morning message timing
dispatch_bot/telegram_app.py    aiogram 3 long polling (the only Telegram-specific file)
simulate.py   backup_db.py   setup.bat   run.bat   backup.bat   test.bat
sample_data/                    sample list + a demo conversation
```
