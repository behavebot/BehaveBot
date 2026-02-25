from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.keyboards import kb_back_to_menu
from bot.handlers.ui_flow import show_internal_screen

router = Router()

GUIDE = """📘 BehaveBot Guide

1. Send a token contract address (CA)
2. Click Open Position
3. Answer short questions
4. Trade as usual
5. Click Close Position
6. View your behavior report

BehaveBot does not trade for you.
It helps you understand yourself."""


@router.callback_query(F.data == "guide")
async def show_guide(callback: CallbackQuery) -> None:
    await show_internal_screen(callback, GUIDE, kb_back_to_menu())
