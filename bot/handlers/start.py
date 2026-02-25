from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext

from bot.keyboards import main_menu_keyboard, kb_back_to_menu
from bot.handlers.ui_flow import show_internal_screen
from bot.handlers.guide import GUIDE
from bot.handlers.stats import _build_stats
from bot.database.db import get_valid_trades_for_stats, get_open_trades

router = Router()

WELCOME = """👋 Welcome to BehaveBot

The market doesn't make you lose money.
Your decisions do.

BehaveBot records how you trade, why you trade, and what patterns lead you to profit or loss.

Focus on your behavior, not the market.

To start: send any token contract address (CA)
Example: 0x1234...abcd"""

COMMAND_LIST_TEXT = """🧭 Command List

/start – Open main menu
/guide – How to use bot
/mystats – Show trading statistics
/positions – Show current open positions
/premium – Premium features
/feedback – Send feedback
/command_list – Show command list
/cancel – Reset current flow"""

PREMIUM_TEXT = """💎 Premium

Premium features are coming soon.
Focus on your behavior first."""


async def show_main_menu(origin: Message | CallbackQuery, state: FSMContext) -> None:
    """Clear FSM and pending token; send welcome with Reply keyboard only. Never use edit for /start."""
    from bot.services import clear_pending_token
    user_id = origin.from_user.id
    await state.clear()
    clear_pending_token(user_id)
    if isinstance(origin, Message):
        await origin.answer(WELCOME, reply_markup=main_menu_keyboard(user_id))
    else:
        await origin.answer()
        await origin.message.answer(WELCOME, reply_markup=main_menu_keyboard(user_id))


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    from bot.services import clear_pending_token
    clear_pending_token(message.from_user.id)
    await message.answer(WELCOME, reply_markup=main_menu_keyboard(message.from_user.id))


@router.callback_query(F.data == "back_home")
async def back_home(callback: CallbackQuery, state: FSMContext) -> None:
    await show_main_menu(callback, state)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await show_main_menu(message, state)


@router.message(F.text == "🛠 Admin Panel")
async def menu_admin_panel(message: Message) -> None:
    from config import ADMIN_IDS
    from bot.keyboards import kb_admin_panel
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Access denied.")
        return
    await show_internal_screen(message, "🛠 Admin Panel\n\nChoose an action:", kb_admin_panel())


# ---- Shared handlers: one place for business + UI; slash and button both call these ----

async def handle_guide(origin: Message | CallbackQuery) -> None:
    await show_internal_screen(origin, GUIDE, kb_back_to_menu())


async def handle_stats(origin: Message | CallbackQuery) -> None:
    from bot.keyboards import kb_stats_tokens
    user_id = origin.from_user.id
    trades = await get_valid_trades_for_stats(user_id)
    text, token_list = _build_stats(user_id, trades)
    kb = kb_stats_tokens(token_list) if token_list else kb_back_to_menu()
    await show_internal_screen(origin, text, kb)


async def handle_positions(origin: Message | CallbackQuery) -> None:
    from bot.keyboards import kb_open_trades_list
    user_id = origin.from_user.id
    open_trades = await get_open_trades(user_id)
    if not open_trades:
        await show_internal_screen(origin, "You have no open positions.", kb_back_to_menu())
        return
    lines = []
    for t in open_trades:
        ot = t.open_time if isinstance(t.open_time, datetime) else datetime.fromisoformat(str(t.open_time))
        mins = int((datetime.utcnow() - ot).total_seconds() / 60)
        mcap_str = f"${t.mcap_open:,.0f}" if t.mcap_open else "N/A"
        lines.append(f"• {t.token_symbol} | 🏦 Mcap at open: {mcap_str} | {mins} min")
    msg = "📈 My Positions\n\n" + "\n".join(lines) + "\n\nTap a position:"
    pairs = [(t.trade_id, t.token_symbol) for t in open_trades]
    await show_internal_screen(origin, msg, kb_open_trades_list(pairs))


async def handle_premium(origin: Message | CallbackQuery) -> None:
    await show_internal_screen(origin, PREMIUM_TEXT, kb_back_to_menu())


async def handle_command_list(origin: Message | CallbackQuery) -> None:
    await show_internal_screen(origin, COMMAND_LIST_TEXT, kb_back_to_menu())


# ---- Menu buttons (Reply keyboard) ----

@router.message(F.text == "📖 Guide")
async def menu_guide(message: Message) -> None:
    await handle_guide(message)


@router.message(F.text == "📊 My Stats")
async def menu_stats(message: Message) -> None:
    await handle_stats(message)


@router.message(F.text == "📈 My Positions")
async def menu_positions(message: Message) -> None:
    await handle_positions(message)


@router.message(F.text == "🧭 Command List")
async def menu_command_list(message: Message) -> None:
    await handle_command_list(message)


@router.message(F.text == "💎 Premium")
async def menu_premium(message: Message) -> None:
    await handle_premium(message)


@router.message(F.text == "📨 Feedback")
async def menu_feedback(message: Message, state: FSMContext) -> None:
    from bot.states import FeedbackStates
    from bot.handlers.feedback import FEEDBACK_PROMPT
    await state.set_state(FeedbackStates.text)
    await show_internal_screen(message, FEEDBACK_PROMPT, kb_back_to_menu())


# ---- Slash commands (same logic as buttons) ----

@router.message(Command("guide"))
async def cmd_guide(message: Message) -> None:
    await handle_guide(message)


@router.message(Command("mystats"))
async def cmd_mystats(message: Message) -> None:
    await handle_stats(message)


@router.message(Command("positions"))
async def cmd_positions(message: Message) -> None:
    await handle_positions(message)


@router.message(Command("premium"))
async def cmd_premium(message: Message) -> None:
    await handle_premium(message)


@router.message(Command("command_list"))
async def cmd_command_list(message: Message) -> None:
    await handle_command_list(message)


@router.message(Command("feedback"))
async def cmd_feedback(message: Message, state: FSMContext) -> None:
    from bot.states import FeedbackStates
    from bot.handlers.feedback import FEEDBACK_PROMPT
    await state.set_state(FeedbackStates.text)
    await show_internal_screen(message, FEEDBACK_PROMPT, kb_back_to_menu())
