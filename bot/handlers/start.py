import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext

from bot.keyboards import kb_back_to_menu
from bot.handlers.ui_flow import show_internal_screen
from bot.handlers.guide import GUIDE_MAIN_MENU, kb_guide_main
from bot.handlers.stats import _build_stats
from bot.database.db import get_valid_trades_for_stats, get_open_trades, get_exit_totals_for_trades
from bot.commands import get_command_list_text

router = Router()
_log = logging.getLogger(__name__)

WELCOME = """👋 Welcome to BehaveBot

The market doesn't make you lose money.
Your decisions do.

BehaveBot records how you trade, why you trade, and what patterns lead you to profit or loss.

Focus on your behavior, not the market.

To start: 
send any token contract address (CA)
Example: 0x1234...abcd"""

async def show_main_menu(origin: Message | CallbackQuery, state: FSMContext) -> None:
    """Clear FSM and pending token; send welcome with inline main menu under the message."""
    from bot.services import clear_pending_token
    from bot.keyboards import main_menu_keyboard_inline
    user_id = origin.from_user.id
    await state.clear()
    clear_pending_token(user_id)
    kb = main_menu_keyboard_inline(user_id)
    if isinstance(origin, Message):
        await origin.answer(WELCOME, reply_markup=kb)
    else:
        await origin.message.answer(WELCOME, reply_markup=kb)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    from bot.services import clear_pending_token
    clear_pending_token(message.from_user.id)
    if message.text and " " in message.text:
        payload = message.text.split(maxsplit=1)[1].strip()
        referrer_id = None
        if payload.upper().startswith("BBT-"):
            try:
                referrer_id = int(payload[4:].strip())
            except (ValueError, IndexError):
                pass
        elif payload.lower().startswith("ref_"):
            try:
                referrer_id = int(payload[4:].strip())
            except (ValueError, IndexError):
                pass
        if referrer_id is not None:
            from bot.database.db import record_referral
            await record_referral(referrer_id, message.from_user.id)
    _log.info("cmd_start: user_id=%s chat_id=%s", message.from_user.id, message.chat.id)
    from bot.keyboards import main_menu_keyboard_inline
    await message.answer(WELCOME, reply_markup=main_menu_keyboard_inline(message.from_user.id))


@router.callback_query(F.data == "back_home")
async def back_home(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await show_main_menu(callback, state)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await show_main_menu(message, state)


@router.message(F.text == "🛠 Admin Panel")
async def menu_admin_panel(message: Message) -> None:
    from config import ADMIN_IDS
    from bot.keyboards import kb_admin_panel, ADMIN_PANEL_TEXT
    from bot.database.db import get_user_premium_status_fresh

    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Access denied.")
        return
    st = await get_user_premium_status_fresh(message.from_user.id)
    await show_internal_screen(message, ADMIN_PANEL_TEXT, kb_admin_panel(bool(st.get("is_premium"))))


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    await menu_admin_panel(message)


@router.message(Command("admin_mystats"))
async def cmd_admin_mystats(message: Message) -> None:
    from config import ADMIN_IDS
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Access denied.")
        return
    await handle_stats(message)


# ---- Inline main menu callbacks (UI-only navigation wrappers) ----

@router.callback_query(F.data == "menu_guide")
async def cb_menu_guide(callback: CallbackQuery) -> None:
    await callback.answer()
    await handle_guide(callback)


@router.callback_query(F.data == "menu_stats")
async def cb_menu_stats(callback: CallbackQuery) -> None:
    await callback.answer()
    await handle_stats(callback)


@router.callback_query(F.data == "menu_positions")
async def cb_menu_positions(callback: CallbackQuery) -> None:
    await callback.answer()
    await handle_positions(callback)


@router.callback_query(F.data == "menu_premium")
async def cb_menu_premium(callback: CallbackQuery) -> None:
    await callback.answer()
    await handle_premium(callback)


@router.callback_query(F.data == "menu_command_list")
async def cb_menu_command_list(callback: CallbackQuery) -> None:
    await callback.answer()
    await handle_command_list(callback)


@router.callback_query(F.data == "menu_feedback")
async def cb_menu_feedback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    # Reuse existing feedback flow (same as /feedback)
    await cmd_feedback(callback.message, state)


@router.callback_query(F.data == "menu_settings")
async def cb_menu_settings(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await cmd_settings(callback.message, state)


@router.callback_query(F.data == "menu_journal")
async def cb_menu_journal(callback: CallbackQuery) -> None:
    await callback.answer()
    from bot.handlers.journal import JOURNAL_MENU_TEXT, kb_journal_menu
    await show_internal_screen(callback, JOURNAL_MENU_TEXT, kb_journal_menu())


@router.callback_query(F.data == "menu_referral")
async def cb_menu_referral(callback: CallbackQuery) -> None:
    await callback.answer()
    from bot.handlers.referral import show_referral_system_screen
    await show_referral_system_screen(callback)


@router.callback_query(F.data == "menu_admin_panel")
async def cb_menu_admin_panel(callback: CallbackQuery) -> None:
    await callback.answer()
    from config import ADMIN_IDS
    from bot.keyboards import kb_admin_panel, ADMIN_PANEL_TEXT
    from bot.database.db import get_user_premium_status_fresh

    if callback.from_user.id not in ADMIN_IDS:
        return
    st = await get_user_premium_status_fresh(callback.from_user.id)
    await show_internal_screen(callback, ADMIN_PANEL_TEXT, kb_admin_panel(bool(st.get("is_premium"))))


@router.callback_query(F.data == "admin_mystats")
async def cb_admin_mystats(callback: CallbackQuery) -> None:
    await callback.answer()
    from config import ADMIN_IDS
    if callback.from_user.id not in ADMIN_IDS:
        return
    await handle_stats(callback)


# ---- Shared handlers: one place for business + UI; slash and button both call these ----

async def handle_guide(origin: Message | CallbackQuery) -> None:
    await show_internal_screen(origin, GUIDE_MAIN_MENU, kb_guide_main())


async def handle_stats(origin: Message | CallbackQuery) -> None:
    # Delegate to stats module so MyStats stays chain-first.
    from bot.handlers.stats import _render_stats_screen
    await _render_stats_screen(origin)  # type: ignore[arg-type]


async def handle_positions(origin: Message | CallbackQuery) -> None:
    from bot.keyboards import kb_open_trades_list
    from bot.utils.formatters import format_compact_number
    user_id = origin.from_user.id
    open_trades = await get_open_trades(user_id)
    if not open_trades:
        await show_internal_screen(origin, "You have no open positions.", kb_back_to_menu())
        return
    lines = []
    for t in open_trades:
        ot = t.open_time if isinstance(t.open_time, datetime) else datetime.fromisoformat(str(t.open_time))
        mins = int((datetime.utcnow() - ot).total_seconds() / 60)
        mcap_str = f"${format_compact_number(t.mcap_open)}" if t.mcap_open is not None else "—"
        mode_tag = " 🤖" if t.trade_mode == "auto" else ""
        net_tag = f" ({t.network})" if t.network else ""
        lines.append(f"• {t.token_symbol}{net_tag}{mode_tag} | 🏦 {mcap_str} | {mins} min")
    msg = "📈 My Positions\n\n" + "\n".join(lines) + "\n\nTap a position:"
    pairs = [(t.trade_id, t.token_symbol) for t in open_trades]
    await show_internal_screen(origin, msg, kb_open_trades_list(pairs))


async def handle_premium(origin: Message | CallbackQuery) -> None:
    """If user has active premium: show Premium Active screen. Else show landing (Preview / Get Free Access / Unlock)."""
    from bot.database.db import get_user_premium_status_fresh
    from bot.keyboards import kb_premium_active_hub, kb_premium_landing
    from bot.handlers.premium import build_premium_active_message
    from bot.handlers.premium import _build_premium_message
    from datetime import datetime
    user_id = origin.from_user.id
    status = await get_user_premium_status_fresh(user_id)
    is_premium = status.get("is_premium", False)
    if is_premium:
        text = await build_premium_active_message(user_id)
        await show_internal_screen(origin, text, kb_premium_active_hub())
    else:
        # Premium expired notification (paid or referral) with direct upgrade CTA.
        now = datetime.utcnow()
        had_paid = False
        had_ref = False
        try:
            if status.get("premium_expires_at"):
                expiry = datetime.fromisoformat(str(status["premium_expires_at"]).replace("Z", ""))
                had_paid = expiry <= now
            if status.get("referral_premium_expires_at"):
                expiry = datetime.fromisoformat(str(status["referral_premium_expires_at"]).replace("Z", ""))
                had_ref = expiry <= now
        except Exception:
            pass
        if had_paid or had_ref:
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            from aiogram.types import InlineKeyboardButton
            b = InlineKeyboardBuilder()
            b.row(InlineKeyboardButton(text="🚀 Unlock Full Premium", callback_data="premium_landing_unlock"))
            b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data="back_home"))
            text = (
                "⏰ Premium Expired\n\n"
                "Your premium access has ended.\n\n"
                "Unlock full insights again anytime 🚀"
            )
            await show_internal_screen(origin, text, b.as_markup())
            return
        await show_internal_screen(origin, await _build_premium_message(user_id), kb_premium_landing())


async def handle_command_list(origin: Message | CallbackQuery) -> None:
    await show_internal_screen(origin, get_command_list_text(), kb_back_to_menu())


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


@router.message(Command("settings"))
async def cmd_settings(message: Message, state: FSMContext) -> None:
    """Show Settings screen (same as ⚙️ Settings button)."""
    await state.clear()
    from bot.handlers.settings import SETTINGS_TITLE
    from bot.keyboards import kb_settings_menu
    await show_internal_screen(message, SETTINGS_TITLE, kb_settings_menu())


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
