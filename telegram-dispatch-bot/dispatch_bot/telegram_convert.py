"""Turn an aiogram Message into the library-independent IncomingMessage.

Only plain attribute access is used, so tests can pass simple mock objects
(types.SimpleNamespace) instead of real Telegram updates.
"""

from __future__ import annotations

import re

from .core import IncomingMessage


def _full_name(user) -> str:
    name = getattr(user, "full_name", None)
    if not name:
        name = " ".join(p for p in (getattr(user, "first_name", None), getattr(user, "last_name", None)) if p)
    return name or ""


def to_incoming(message, update_id: int | None, bot_id: int | None,
                bot_username: str | None) -> IncomingMessage | None:
    user = getattr(message, "from_user", None)
    text = getattr(message, "text", None)
    if user is None or not text:
        return None

    reply = getattr(message, "reply_to_message", None)
    reply_user = getattr(reply, "from_user", None) if reply is not None else None
    reply_to_bot = bool(reply_user is not None and bot_id is not None and reply_user.id == bot_id)
    reply_to_user_id = reply_user.id if (reply_user is not None and not getattr(reply_user, "is_bot", False)) else None

    mentions_bot = False
    if bot_username and re.search(rf"@{re.escape(bot_username.lstrip('@'))}(?!\w)", text, re.IGNORECASE):
        mentions_bot = True
    for ent in getattr(message, "entities", None) or []:
        ent_user = getattr(ent, "user", None)
        if getattr(ent, "type", None) == "text_mention" and ent_user is not None and ent_user.id == bot_id:
            mentions_bot = True

    chat = message.chat
    return IncomingMessage(
        chat_id=chat.id,
        chat_type=chat.type,
        message_id=message.message_id,
        user_id=user.id,
        user_name=_full_name(user),
        text=text,
        update_id=update_id,
        username=getattr(user, "username", None),
        is_bot=bool(getattr(user, "is_bot", False)),
        reply_to_bot=reply_to_bot,
        reply_to_user_id=reply_to_user_id,
        mentions_bot=mentions_bot,
    )
