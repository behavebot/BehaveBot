"""Admin-only Track Behaviour analytics. Visible only to ADMIN_IDS."""
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_IDS
from bot.keyboards.inline import BACK_TO_MENU_DATA
from bot.database.db import (
    get_analytics_user_activity,
    get_analytics_trade_stats,
    get_analytics_psychology_stats,
)

router = Router()

ADMIN_ACCESS_DENIED = "Access denied."
TRACK_BEHAVIOUR_TITLE = "📊 BehaveBot Internal Analytics"
BACK_TO_ADMIN_DATA = "admin_back_to_admin"


def kb_track_behaviour_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="👥 User Activity", callback_data="admin_user_activity"))
    b.row(InlineKeyboardButton(text="📈 Trade Stats", callback_data="admin_trade_stats"))
    b.row(InlineKeyboardButton(text="🧠 Psychology Stats", callback_data="admin_psychology_stats"))
    b.row(InlineKeyboardButton(text="📊 Engagement Stats", callback_data="admin_engagement_stats"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


async def _deny_or_continue(callback: CallbackQuery) -> bool:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(ADMIN_ACCESS_DENIED, show_alert=True)
        return False
    return True


@router.callback_query(F.data == "admin_track_behaviour")
async def show_track_behaviour_menu(callback: CallbackQuery) -> None:
    if not await _deny_or_continue(callback):
        return
    await callback.answer()
    text = f"{TRACK_BEHAVIOUR_TITLE}\n\nSelect a report:"
    await callback.message.edit_text(text, reply_markup=kb_track_behaviour_menu())


@router.callback_query(F.data == "admin_user_activity")
async def show_user_activity(callback: CallbackQuery) -> None:
    if not await _deny_or_continue(callback):
        return
    await callback.answer()
    data = await get_analytics_user_activity()
    text = (
        "👥 User Activity\n\n"
        f"Total Users: {data['total_users']}\n"
        f"Active 1D: {data['active_1d']}\n"
        f"Active 7D: {data['active_7d']}\n"
        f"Active 30D: {data['active_30d']}"
    )
    await callback.message.edit_text(text, reply_markup=kb_track_behaviour_menu())


@router.callback_query(F.data == "admin_trade_stats")
async def show_trade_stats(callback: CallbackQuery) -> None:
    if not await _deny_or_continue(callback):
        return
    await callback.answer()
    data = await get_analytics_trade_stats()
    text = (
        "📈 Trade Stats\n\n"
        f"Total Trades (valid): {data['total_valid']}\n"
        f"Closed Trades: {data['closed']}\n"
        f"Open Trades: {data['open']}\n"
        f"Invalid %: {data['invalid_pct']:.1f}%\n"
        f"Avg Duration: {data['avg_duration_min']} min"
    )
    await callback.message.edit_text(text, reply_markup=kb_track_behaviour_menu())


@router.callback_query(F.data == "admin_psychology_stats")
async def show_psychology_stats(callback: CallbackQuery) -> None:
    if not await _deny_or_continue(callback):
        return
    await callback.answer()
    data = await get_analytics_psychology_stats()
    text = (
        "🧠 Psychology Stats\n\n"
        f"Emotion Open fill rate: {data['emotion_open_rate']}%\n"
        f"Emotion Close fill rate: {data['emotion_close_rate']}%\n"
        f"Most Used Emotion: {data['most_used_emotion']}\n"
        f"Worst Emotion (lowest avg PnL): {data['worst_emotion']} ({data['worst_avg_pnl']}%)"
    )
    await callback.message.edit_text(text, reply_markup=kb_track_behaviour_menu())


@router.callback_query(F.data == "admin_engagement_stats")
async def show_engagement_stats(callback: CallbackQuery) -> None:
    if not await _deny_or_continue(callback):
        return
    await callback.answer()
    text = (
        "📊 Engagement Stats\n\n"
        "No event logging table. Stats view / engagement metrics are not available."
    )
    await callback.message.edit_text(text, reply_markup=kb_track_behaviour_menu())


@router.callback_query(F.data == BACK_TO_ADMIN_DATA)
async def admin_analytics_back(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer()
        return
    from bot.keyboards import kb_admin_panel
    from bot.database.db import get_user_premium_status_fresh
    await callback.answer()
    st = await get_user_premium_status_fresh(callback.from_user.id)
    await callback.message.edit_text(
        "🛠 Admin Panel\n\nChoose an action:",
        reply_markup=kb_admin_panel(bool(st.get("is_premium"))),
    )
