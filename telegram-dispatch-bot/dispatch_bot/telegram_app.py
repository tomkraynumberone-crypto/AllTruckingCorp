"""The only file that talks to Telegram (aiogram 3.x, long polling)."""

from __future__ import annotations

import asyncio
import logging

from .config import Config
from .core import Core, Outgoing
from .db import Database
from .scheduler import run_scheduler
from .telegram_convert import to_incoming

log = logging.getLogger("dispatch_bot.telegram")


async def run_bot(cfg: Config) -> None:
    # Imported here so the rest of the project (and its tests) work without aiogram installed.
    from aiogram import BaseMiddleware, Bot, Dispatcher, F
    from aiogram.exceptions import TelegramForbiddenError
    from aiogram.types import Message, ReplyParameters

    db = Database(cfg.db_path)
    bot = Bot(token=cfg.bot_token)
    try:
        me = await bot.get_me()          # proves the token works before we start polling
        log.info("Connected to Telegram as @%s (id %s).", me.username, me.id)

        core = Core(db, cfg, bot_username=me.username)
        core.startup()
        if core.group_chat_id() is None:
            log.warning("No dispatch group set yet. Add the bot to your group and send /setgroup there.")
        log.info("Timezone %s, morning message at %s.", core.tz().key, core.greeting_time().strftime("%H:%M"))

        async def send_raw(out: Outgoing) -> None:
            kwargs = dict(chat_id=out.chat_id, text=out.text, parse_mode=out.parse_mode)
            if out.reply_to_message_id:
                kwargs["reply_parameters"] = ReplyParameters(
                    message_id=out.reply_to_message_id, allow_sending_without_reply=True)
            await bot.send_message(**kwargs)

        async def safe_send(out: Outgoing) -> None:
            try:
                await send_raw(out)
            except TelegramForbiddenError:
                log.warning("Cannot message chat %s. If this is a dispatcher, open a private chat "
                            "with the bot and press Start.", out.chat_id)
            except Exception:
                log.exception("Failed to send a message to chat %s", out.chat_id)

        class UpdateIdMiddleware(BaseMiddleware):
            async def __call__(self, handler, event, data):
                data["update_id"] = event.update_id
                return await handler(event, data)

        dp = Dispatcher()
        dp.update.outer_middleware(UpdateIdMiddleware())

        @dp.message(F.text)
        async def on_message(message: Message, update_id: int | None = None) -> None:
            try:
                incoming = to_incoming(message, update_id, me.id, me.username)
                if incoming is None:
                    return
                for out in core.handle_message(incoming):
                    await safe_send(out)
            except Exception:
                log.exception("Error while handling a message")

        stop = asyncio.Event()
        scheduler_task = asyncio.create_task(run_scheduler(core, send_raw, stop))
        try:
            await bot.delete_webhook(drop_pending_updates=False)   # long polling needs no webhook
            log.info("Polling for updates. Press Ctrl+C to stop.")
            await dp.start_polling(bot, allowed_updates=["message"])
        finally:
            stop.set()
            await scheduler_task
    finally:
        await bot.session.close()
        db.close()
        log.info("Bot stopped.")
