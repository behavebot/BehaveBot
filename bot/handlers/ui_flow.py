"""Internal screens: one clean message with inline keyboard (no placeholder / dot messages)."""
from aiogram.types import Message, CallbackQuery


async def show_internal_screen(
    origin: Message | CallbackQuery,
    text: str,
    inline_keyboard,
) -> None:
    """Show one message with inline keyboard. No extra placeholder messages."""
    if isinstance(origin, Message):
        await origin.answer(text, reply_markup=inline_keyboard)
    else:
        await origin.answer()
        await origin.message.edit_text(text, reply_markup=inline_keyboard)
