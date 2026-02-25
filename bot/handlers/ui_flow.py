"""Strict keyboard flow: internal screens remove Reply keyboard and show Inline only."""
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove


async def show_internal_screen(
    origin: Message | CallbackQuery,
    text: str,
    inline_keyboard,
) -> None:
    """Remove Reply keyboard and show message with Inline keyboard only. Never attach main Reply keyboard."""
    remove_markup = ReplyKeyboardRemove(remove_keyboard=True)
    if isinstance(origin, Message):
        await origin.answer(".", reply_markup=remove_markup)
        await origin.answer(text, reply_markup=inline_keyboard)
    else:
        await origin.answer()
        await origin.message.edit_text(text, reply_markup=inline_keyboard)
        await origin.message.answer(".", reply_markup=remove_markup)
