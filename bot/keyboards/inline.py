from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

BACK_TO_MENU_DATA = "back_home"

# Must match exactly what token handler uses to ignore button text.
MAIN_MENU_BUTTON_TEXTS = (
    "📖 Guide",
    "📊 My Stats",
    "📈 My Positions",
    "💎 Premium",
    "🧭 Command List",
    "📨 Feedback",
    "🛠 Admin Panel",
)


def main_menu_keyboard(user_id: int | None = None) -> ReplyKeyboardMarkup:
    """Main menu: Reply only. 2–3 buttons per row. If user_id in ADMIN_IDS, add Admin Panel."""
    from config import ADMIN_IDS
    rows = [
        [KeyboardButton(text="📖 Guide"), KeyboardButton(text="📊 My Stats")],
        [KeyboardButton(text="📈 My Positions"), KeyboardButton(text="💎 Premium")],
        [KeyboardButton(text="🧭 Command List"), KeyboardButton(text="📨 Feedback")],
    ]
    if user_id is not None and user_id in ADMIN_IDS:
        rows.append([KeyboardButton(text="🛠 Admin Panel")])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
    )


def kb_main_menu_reply(user_id: int | None = None) -> ReplyKeyboardMarkup:
    """Alias for main_menu_keyboard (backward compatibility)."""
    return main_menu_keyboard(user_id)


def kb_admin_panel() -> InlineKeyboardMarkup:
    """Admin Panel: Maintenance, Track Behaviour, Admin Feedback, Back to Menu."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🛠 Maintenance", callback_data="admin_maintenance_menu"))
    b.row(InlineKeyboardButton(text="📊 Track Behaviour", callback_data="admin_track_behaviour"))
    b.row(InlineKeyboardButton(text="📨 Admin Feedback", callback_data="admin_feedback_viewer"))
    b.row(InlineKeyboardButton(text="🔙 Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_admin_maintenance() -> InlineKeyboardMarkup:
    """Maintenance sub-menu: Turn Bot ON, Turn Maintenance ON, Back to Admin."""
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="🟢 Turn Bot ON", callback_data="admin_maintenance_off"),
        InlineKeyboardButton(text="🔴 Turn Maintenance ON", callback_data="admin_maintenance_on"),
    )
    b.row(InlineKeyboardButton(text="🔙 Back to Admin", callback_data="admin_back_to_admin"))
    return b.as_markup()


def kb_back_to_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_stats_tokens(token_list: list[tuple[str, float]]) -> InlineKeyboardMarkup:
    """One button per token: label 'SYMBOL → +10%', callback_data stat_token:SYMBOL. Then Back to Menu."""
    b = InlineKeyboardBuilder()
    for symbol, pnl in token_list:
        label = f"{symbol} → {pnl:+.0f}%"
        cb = f"stat_token:{symbol}"[:64]
        b.row(InlineKeyboardButton(text=label, callback_data=cb))
    b.row(InlineKeyboardButton(text="⬅ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_stats_back() -> InlineKeyboardMarkup:
    """Back to Stats (show stats again) and Back to Menu."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅ Back to Stats", callback_data="stats"))
    b.row(InlineKeyboardButton(text="⬅ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_main() -> InlineKeyboardMarkup:
    return kb_back_to_menu()


def kb_guide_feedback() -> InlineKeyboardMarkup:
    return kb_back_to_menu()


def kb_token_preview() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="🔄 Refresh", callback_data="token_refresh"),
        InlineKeyboardButton(text="✅ Open Position", callback_data="open_position"),
        InlineKeyboardButton(text="❌ Cancel", callback_data="token_cancel"),
    )
    return b.as_markup()


def kb_token_open_cancel() -> InlineKeyboardMarkup:
    return kb_token_preview()


def kb_open_or_view_cancel() -> InlineKeyboardMarkup:
    return kb_token_preview()


def kb_open_new_or_past_cancel() -> InlineKeyboardMarkup:
    return kb_token_preview()


def kb_emotion_open() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="FOMO", callback_data="emotion_open:FOMO"),
        InlineKeyboardButton(text="Calm", callback_data="emotion_open:Calm"),
        InlineKeyboardButton(text="Fear", callback_data="emotion_open:Fear"),
    )
    b.row(
        InlineKeyboardButton(text="Confident", callback_data="emotion_open:Confident"),
        InlineKeyboardButton(text="Greedy", callback_data="emotion_open:Greedy"),
        InlineKeyboardButton(text="Revenge", callback_data="emotion_open:Revenge"),
    )
    b.row(InlineKeyboardButton(text="Other ✍️", callback_data="emotion_open:Other"))
    return b.as_markup()


def kb_reason_open() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="Following Twitter", callback_data="reason_open:Following Twitter"),
        InlineKeyboardButton(text="Chart setup", callback_data="reason_open:Chart setup"),
    )
    b.row(
        InlineKeyboardButton(text="Friend signal", callback_data="reason_open:Friend signal"),
        InlineKeyboardButton(text="Pump chase", callback_data="reason_open:Pump chase"),
    )
    b.row(
        InlineKeyboardButton(text="Plan", callback_data="reason_open:Plan"),
        InlineKeyboardButton(text="Other ✍️", callback_data="reason_open:Other"),
    )
    return b.as_markup()


def kb_category() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="Meme", callback_data="category:Meme"),
        InlineKeyboardButton(text="AI", callback_data="category:AI"),
        InlineKeyboardButton(text="DeFi", callback_data="category:DeFi"),
    )
    b.row(
        InlineKeyboardButton(text="Gaming", callback_data="category:Gaming"),
        InlineKeyboardButton(text="NFT", callback_data="category:NFT"),
        InlineKeyboardButton(text="Other ✍️", callback_data="category:Other"),
    )
    return b.as_markup()


def kb_risk() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="Low Risk", callback_data="risk:Low Risk"),
        InlineKeyboardButton(text="Medium Risk", callback_data="risk:Medium Risk"),
    )
    b.row(
        InlineKeyboardButton(text="High Risk", callback_data="risk:High Risk"),
        InlineKeyboardButton(text="Yolo", callback_data="risk:Yolo"),
    )
    return b.as_markup()


def kb_close_position(trade_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Close Position", callback_data=f"close_position:{trade_id}"))
    return b.as_markup()


def kb_emotion_close() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="Relief", callback_data="emotion_close:Relief"),
        InlineKeyboardButton(text="Regret", callback_data="emotion_close:Regret"),
        InlineKeyboardButton(text="Greedy", callback_data="emotion_close:Greedy"),
    )
    b.row(
        InlineKeyboardButton(text="Fear", callback_data="emotion_close:Fear"),
        InlineKeyboardButton(text="Confident", callback_data="emotion_close:Confident"),
        InlineKeyboardButton(text="Other ✍️", callback_data="emotion_close:Other"),
    )
    return b.as_markup()


def kb_reason_close() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="Target hit", callback_data="reason_close:Target hit"),
        InlineKeyboardButton(text="Stop loss", callback_data="reason_close:Stop loss"),
    )
    b.row(
        InlineKeyboardButton(text="Market fear", callback_data="reason_close:Market fear"),
        InlineKeyboardButton(text="Paper hands", callback_data="reason_close:Paper hands"),
    )
    b.row(InlineKeyboardButton(text="Other ✍️", callback_data="reason_close:Other"))
    return b.as_markup()


def kb_discipline() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="Yes", callback_data="discipline:Yes"),
        InlineKeyboardButton(text="No", callback_data="discipline:No"),
        InlineKeyboardButton(text="I had no plan", callback_data="discipline:I had no plan"),
    )
    return b.as_markup()


def kb_after_close(trade_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="View Report", callback_data=f"view_report:{trade_id}"),
        InlineKeyboardButton(text="Mark as Invalid", callback_data=f"mark_invalid:{trade_id}"),
    )
    b.row(InlineKeyboardButton(text="⬅ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_mark_invalid_confirm() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="Yes, mark invalid", callback_data="invalid_confirm:yes"),
        InlineKeyboardButton(text="Cancel", callback_data="invalid_confirm:no"),
    )
    return b.as_markup()


def kb_positions_list_back() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_empty() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[])


def kb_open_trades_list(open_trades: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for trade_id, symbol in open_trades:
        b.row(InlineKeyboardButton(text=f"📌 {symbol}", callback_data=f"position_detail:{trade_id}"))
    b.row(InlineKeyboardButton(text="⬅ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_position_detail(trade_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✅ Close Position", callback_data=f"close_position:{trade_id}"))
    b.row(InlineKeyboardButton(text="🚫 Mark Invalid Token", callback_data=f"mark_invalid:{trade_id}"))
    b.row(InlineKeyboardButton(text="⬅ Back", callback_data="positions_list"))
    return b.as_markup()


def kb_mark_invalid_reason() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="Forgot to close", callback_data="invalid_reason:Forgot to close"),
        InlineKeyboardButton(text="Wrong token", callback_data="invalid_reason:Wrong token"),
    )
    b.row(
        InlineKeyboardButton(text="Test trade", callback_data="invalid_reason:Test trade"),
        InlineKeyboardButton(text="Other ✍️", callback_data="invalid_reason:Other"),
    )
    return b.as_markup()
