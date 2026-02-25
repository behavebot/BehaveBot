"""Global maintenance mode: block non-admin users when maintenance is on."""
from aiogram import BaseMiddleware
from aiogram.types import Update, TelegramObject

from config import ADMIN_IDS
from bot.database.db import is_maintenance_mode

MAINTENANCE_MSG = (
    "🚧 BehaveBot is under maintenance. Please contact administrator and try again later."
)


class MaintenanceMiddleware(BaseMiddleware):
    """If maintenance is ON and user is not admin, reply and stop propagation."""

    async def __call__(
        self,
        handler,
        event: Update,
        data: dict,
    ) -> any:
        if not await is_maintenance_mode():
            return await handler(event, data)
        user_id = None
        chat_id = None
        if event.message:
            user_id = event.message.from_user.id if event.message.from_user else None
            chat_id = event.message.chat.id if event.message.chat else None
        elif event.callback_query:
            user_id = event.callback_query.from_user.id if event.callback_query.from_user else None
            chat_id = (
                event.callback_query.message.chat.id
                if event.callback_query.message and event.callback_query.message.chat
                else None
            )
        if user_id is None or chat_id is None:
            return await handler(event, data)
        if user_id in ADMIN_IDS:
            return await handler(event, data)
        bot = data.get("bot")
        if bot:
            if event.callback_query:
                await event.callback_query.answer()
                await bot.send_message(chat_id=chat_id, text=MAINTENANCE_MSG)
            else:
                await bot.send_message(chat_id=chat_id, text=MAINTENANCE_MSG)
        return
