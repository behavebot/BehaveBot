from typing import Optional
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
    "📓 Journal",
    "💎 Premium",
    "🚀 Earn & Invite",
    "🧭 Command List",
    "📨 Feedback",
    "⚙️ Settings",
    "🛠 Admin Panel",
)


def main_menu_keyboard(user_id: int | None = None) -> ReplyKeyboardMarkup:
    """Main menu: Reply only. 2–3 buttons per row. If user_id in ADMIN_IDS, add Admin Panel."""
    from config import ADMIN_IDS
    rows = [
        [KeyboardButton(text="📊 My Stats"), KeyboardButton(text="📈 My Positions")],
        [KeyboardButton(text="📓 Journal")],
        [KeyboardButton(text="💎 Premium"), KeyboardButton(text="🚀 Earn & Invite")],
        [KeyboardButton(text="📖 Guide"), KeyboardButton(text="⚙️ Settings")],
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


ADMIN_PANEL_TEXT = (
    "🛠 <b>Admin Panel</b>\n\n"
    "📊 Core · 💰 Payments · 👥 Users · 📩 Comms · ⚙️ System\n\n"
    "Choose an action:"
)


def kb_admin_panel(is_premium_active: bool | None = None) -> InlineKeyboardMarkup:
    """Admin panel: grouped actions + nav."""
    if is_premium_active is True:
        premium_label = "❌ Disable Premium"
    elif is_premium_active is False:
        premium_label = "⭐ Enable Premium"
    else:
        premium_label = "⭐ Premium Access"
    b = InlineKeyboardBuilder()
    # 📊 Core Control
    b.row(
        InlineKeyboardButton(text="📌 Grant Premium", callback_data="admin_premium_unlock"),
        InlineKeyboardButton(text="🚫 Revoke Premium", callback_data="admin_premium_lock"),
    )
    b.row(InlineKeyboardButton(text=premium_label, callback_data="admin_premium_toggle_self"))
    # 💰 Payments
    b.row(InlineKeyboardButton(text="💳 Pending Payments", callback_data="admin_payments"))
    # 👥 Users & System
    b.row(
        InlineKeyboardButton(text="🌐 Referral Network", callback_data="admin_referral_network"),
        InlineKeyboardButton(text="🧠 Track Behaviour", callback_data="admin_track_behaviour"),
    )
    # 📩 Communication
    b.row(
        InlineKeyboardButton(text="📩 Report CS", callback_data="admin_support"),
        InlineKeyboardButton(text="📢 Send Announcement", callback_data="admin_announcement_start"),
    )
    b.row(InlineKeyboardButton(text="📑 User Feedback", callback_data="admin_feedback_viewer"))
    # ⚙️ System
    b.row(
        InlineKeyboardButton(text="🛠 Maintenance", callback_data="admin_maintenance_menu"),
        InlineKeyboardButton(text="📊 Admin MyStats", callback_data="admin_mystats"),
    )
    # 🔙 Navigation
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_admin_premium_input_nav() -> InlineKeyboardMarkup:
    """While waiting for user ID (grant/revoke premium)."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_admin_maintenance() -> InlineKeyboardMarkup:
    """Maintenance sub-menu."""
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="🟢 Turn Bot ON", callback_data="admin_maintenance_off"),
        InlineKeyboardButton(text="🔴 Turn Maintenance ON", callback_data="admin_maintenance_on"),
    )
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_back_to_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_premium_landing() -> InlineKeyboardMarkup:
    """Main Premium entry: View AI Analysis Preview, Unlock Premium, Back."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🧠 AI Insight Preview", callback_data="premium_unified_preview"))
    b.row(InlineKeyboardButton(text="🎁 Try Free Access", callback_data="premium_try_free_premium"))
    b.row(InlineKeyboardButton(text="💎 Unlock Premium", callback_data="premium_landing_unlock"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_back_from_unified_preview() -> InlineKeyboardMarkup:
    """From unified AI preview: Unlock Premium, Back to Premium."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="💎 Unlock Premium", callback_data="premium_landing_unlock"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_premium_preview() -> InlineKeyboardMarkup:
    """Preview screen: Unlock Full Premium, Try Free Access, Back."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🚀 Unlock Full Premium", callback_data="premium_landing_unlock"))
    b.row(InlineKeyboardButton(text="🎁 Try Free Access", callback_data="premium_landing_free"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_premium_pricing() -> InlineKeyboardMarkup:
    """Legacy pricing keyboard — same plan callbacks as payment flow (no extra steps)."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="💳 Monthly", callback_data="pay_sel_monthly"))
    b.row(InlineKeyboardButton(text="💳 Yearly", callback_data="pay_sel_yearly"))
    b.row(InlineKeyboardButton(text="💳 Lifetime", callback_data="pay_sel_lifetime"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_premium_payment_plans() -> InlineKeyboardMarkup:
    """Step 0: pick plan → then edit to wallet + instructions (see kb_payment_plan_back_only)."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="💳 Monthly", callback_data="pay_sel_monthly"))
    b.row(InlineKeyboardButton(text="💳 Yearly", callback_data="pay_sel_yearly"))
    b.row(InlineKeyboardButton(text="💳 Lifetime", callback_data="pay_sel_lifetime"))
    b.row(InlineKeyboardButton(text="⬅️ Back", callback_data="payment_back_premium"))
    return b.as_markup()


def kb_payment_plan_back_only() -> InlineKeyboardMarkup:
    """Step 1: after plan selected — back to plan picker (same message, edit_text)."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Back", callback_data="payment_back_plan_select"))
    return b.as_markup()


def kb_premium_free_access() -> InlineKeyboardMarkup:
    """Free access: Get Referral Link, Leaderboard, Back."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔗 Get Referral Link", callback_data="premium_free_invite"))
    b.row(InlineKeyboardButton(text="💸 How to Earn USD", callback_data="premium_free_how_to_earn"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_back_to_premium_landing() -> InlineKeyboardMarkup:
    """Back to Premium landing (from pricing or free flow)."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_premium_hub() -> InlineKeyboardMarkup:
    """Non-premium hub: single entry to Premium Insight."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🧠 Premium Insight", callback_data="premium_insight_unified"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_premium_active_hub() -> InlineKeyboardMarkup:
    """Premium hub: unified insight only."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🧠 Premium Insight", callback_data="premium_insight_unified"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_after_premium_insight() -> InlineKeyboardMarkup:
    """After unified Premium Insight screen."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_premium_insight_locked() -> InlineKeyboardMarkup:
    """Non-premium user tapped Premium Insight — CTA to unlock / referral."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_back_to_premium_hub() -> InlineKeyboardMarkup:
    """Back to Premium Hub (from a module or locked preview)."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_referral_main() -> InlineKeyboardMarkup:
    """Referral program screen (from /referral): Copy Link, My Stats, Leaderboard, Back."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔗 Copy Link", callback_data="referral_copy_link"))
    b.row(
        InlineKeyboardButton(text="📊 My Stats", callback_data="referral_my_stats"),
        InlineKeyboardButton(text="🏆 Leaderboard", callback_data="referral_leaderboard"),
    )
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_referral_system() -> InlineKeyboardMarkup:
    """Earn & Invite screen: Generate Link, Earning Guide, My Stats, Top Alpha, Back."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔗 Generate Invite Link", callback_data="referral_generate_link"))
    b.row(InlineKeyboardButton(text="💰 Earning Guide", callback_data="referral_earning_guide"))
    b.row(
        InlineKeyboardButton(text="📊 My Referral Stats", callback_data="referral_my_stats"),
        InlineKeyboardButton(text="🏆 Top Alpha Referrers", callback_data="referral_top_alpha"),
    )
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_stats_tokens(token_list: list[tuple[str, float]]) -> InlineKeyboardMarkup:
    """One button per token: label 'SYMBOL → +10.1%', callback_data stat_token:SYMBOL. Then Back to Menu."""
    b = InlineKeyboardBuilder()
    for symbol, pnl in token_list:
        label = f"{symbol} → {pnl:+.1f}%"
        cb = f"stat_token:{symbol}"[:64]
        b.row(InlineKeyboardButton(text=label, callback_data=cb))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()

def kb_stats_chain_only() -> InlineKeyboardMarkup:
    """Step 2 of My Stats: select chain only."""
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="🟡 BNB Chain", callback_data="stats_chain_pick:BNB"),
        InlineKeyboardButton(text="🟣 SOL Chain", callback_data="stats_chain_pick:SOL"),
    )
    b.row(InlineKeyboardButton(text="🔵 Base Chain", callback_data="stats_chain_pick:BASE"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_stats_chain_token_list(
    chain_code: str,
    token_list_page: list[tuple[str, float]],
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    """Chain token list with Prev/Next pagination (max 5 tokens shown)."""
    b = InlineKeyboardBuilder()
    for symbol, pnl in token_list_page:
        label = f"{symbol} → {pnl:+.1f}%"
        cb = f"stat_token_chain:{chain_code}:{symbol}:{page}"[:64]
        b.row(InlineKeyboardButton(text=label, callback_data=cb))
    # Clean one-row navigation (max 2 buttons), no emoji on Back.
    nav: list[InlineKeyboardButton] = []
    if total_pages <= 1:
        nav = [InlineKeyboardButton(text="Back", callback_data="stats")]
    elif page <= 0:
        nav = [
            InlineKeyboardButton(text="Back", callback_data="stats"),
            InlineKeyboardButton(text="Next", callback_data=f"stats_chain_page:{chain_code}:{page+1}"),
        ]
    elif page >= total_pages - 1:
        nav = [InlineKeyboardButton(text="Prev", callback_data=f"stats_chain_page:{chain_code}:{page-1}")]
    else:
        nav = [
            InlineKeyboardButton(text="Prev", callback_data=f"stats_chain_page:{chain_code}:{page-1}"),
            InlineKeyboardButton(text="Next", callback_data=f"stats_chain_page:{chain_code}:{page+1}"),
        ]
    b.row(*nav)
    return b.as_markup()


def kb_stats_tokens_paginated(
    token_list_page: list[tuple[str, float]],
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    """Token performance: 5 tokens per page, Prev | Next (disabled on first/last), Back to Menu. Buttons use .1f precision."""
    b = InlineKeyboardBuilder()
    for symbol, pnl in token_list_page:
        label = f"{symbol} → {pnl:+.1f}%"
        cb = f"stat_token:{symbol}"[:64]
        b.row(InlineKeyboardButton(text=label, callback_data=cb))
    if total_pages > 1:
        row = []
        if page > 0:
            row.append(InlineKeyboardButton(text="⬅ Previous", callback_data=f"stats_page:{page - 1}"))
        if page < total_pages - 1:
            row.append(InlineKeyboardButton(text="➡ Next", callback_data=f"stats_page:{page + 1}"))
        if row:
            b.row(*row)
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_stats_back() -> InlineKeyboardMarkup:
    """Back to Stats (show stats again) and Back to Menu."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Back to Stats", callback_data="stats"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_stats_trade_detail(
    trade_id: int,
    has_note: bool = False,
    symbol: str = "",
    chain_code: str | None = None,
    page: int | None = None,
    admin_delete_cb: str | None = None,
) -> InlineKeyboardMarkup:
    """Trade detail: Edit/Add Note. Back goes to chain list if chain_code+page set, else to stats/token."""
    b = InlineKeyboardBuilder()
    if has_note:
        b.row(InlineKeyboardButton(text="✏ Edit Note", callback_data=f"edit_trade_note:{trade_id}"))
    else:
        b.row(InlineKeyboardButton(text="📝 Add Note", callback_data=f"add_trade_note:{trade_id}"))
    if admin_delete_cb:
        b.row(InlineKeyboardButton(text="🗑 Delete Trade", callback_data=admin_delete_cb[:64]))
    if chain_code is not None and page is not None:
        b.row(InlineKeyboardButton(text="Back", callback_data=f"back_to_chain:{chain_code}:{page}"[:64]))
    else:
        if symbol:
            b.row(InlineKeyboardButton(text=f"Back to ${symbol}", callback_data=f"stat_token:{symbol}"[:64]))
        b.row(InlineKeyboardButton(text="Back to Stats", callback_data="stats"))
    return b.as_markup()


def kb_admin_delete_trade_confirm(trade_id: int, chain_code: str | None = None, page: int | None = None) -> InlineKeyboardMarkup:
    """Admin confirmation keyboard for deleting one trade."""
    b = InlineKeyboardBuilder()
    cc = chain_code or "-"
    pg = page if page is not None else 0
    b.row(
        InlineKeyboardButton(text="✅ Confirm Delete", callback_data=f"admin_delete_trade_confirm:{trade_id}:{cc}:{pg}"[:64]),
        InlineKeyboardButton(text="❌ Cancel", callback_data=f"back_to_trade_detail:{trade_id}:{cc}:{pg}"[:64]),
    )
    return b.as_markup()


def kb_stats_token_trades(
    symbol: str,
    trades: list,
    chain_code: str | None = None,
    page: int | None = None,
) -> InlineKeyboardMarkup:
    """Token history with individual trade buttons. If chain_code+page set, Back returns to chain list."""
    b = InlineKeyboardBuilder()
    for i, t in enumerate(trades, 1):
        trade_id = getattr(t, "trade_id", None)
        if trade_id:
            if chain_code is not None and page is not None:
                cb = f"stat_trade_detail:{trade_id}:{symbol}:{chain_code}:{page}"[:64]
            else:
                cb = f"stat_trade_detail:{trade_id}:{symbol}"[:64]
            b.row(InlineKeyboardButton(text=f"📋 Trade #{i}", callback_data=cb))
    if chain_code is not None and page is not None:
        b.row(InlineKeyboardButton(text="Back", callback_data=f"back_to_chain:{chain_code}:{page}"[:64]))
    else:
        b.row(InlineKeyboardButton(text="Back to Stats", callback_data="stats"))
        b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_main() -> InlineKeyboardMarkup:
    return kb_back_to_menu()


def kb_guide_feedback() -> InlineKeyboardMarkup:
    return kb_back_to_menu()


def main_menu_keyboard_inline(user_id: int | None = None) -> InlineKeyboardMarkup:
    """Inline main menu under welcome (/start). Use as reply_markup with welcome text."""
    return kb_main_menu_inline(user_id)


def kb_main_menu_inline(user_id: int | None = None) -> InlineKeyboardMarkup:
    """Inline main menu shown under welcome message (no persistent reply keyboard)."""
    from config import ADMIN_IDS
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="📊 My Stats", callback_data="menu_stats"),
        InlineKeyboardButton(text="📈 My Positions", callback_data="menu_positions"),
    )
    b.row(
        InlineKeyboardButton(text="📓 Journal", callback_data="menu_journal"),
    )
    b.row(
        InlineKeyboardButton(text="💎 Premium", callback_data="menu_premium"),
        InlineKeyboardButton(text="🚀 Earn & Invite", callback_data="menu_referral"),
    )
    b.row(
        InlineKeyboardButton(text="📖 Guide", callback_data="menu_guide"),
        InlineKeyboardButton(text="⚙️ Settings", callback_data="menu_settings"),
    )
    b.row(
        InlineKeyboardButton(text="🧭 Command List", callback_data="menu_command_list"),
        InlineKeyboardButton(text="📨 Feedback", callback_data="menu_feedback"),
    )
    if user_id is not None and user_id in ADMIN_IDS:
        b.row(InlineKeyboardButton(text="🛠 Admin Panel", callback_data="menu_admin_panel"))
    return b.as_markup()

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
        InlineKeyboardButton(text="😤 FOMO", callback_data="emotion_open:FOMO"),
        InlineKeyboardButton(text="😌 Calm", callback_data="emotion_open:Calm"),
        InlineKeyboardButton(text="😨 Fear", callback_data="emotion_open:Fear"),
    )
    b.row(
        InlineKeyboardButton(text="😎 Confident", callback_data="emotion_open:Confident"),
        InlineKeyboardButton(text="🤑 Greedy", callback_data="emotion_open:Greedy"),
        InlineKeyboardButton(text="😡 Revenge", callback_data="emotion_open:Revenge"),
    )
    b.row(InlineKeyboardButton(text="✍️ Other", callback_data="emotion_open:Other"))
    return b.as_markup()


def kb_reason_open() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="🐦 Following Twitter", callback_data="reason_open:Following Twitter"),
        InlineKeyboardButton(text="📈 Chart setup", callback_data="reason_open:Chart setup"),
    )
    b.row(
        InlineKeyboardButton(text="👥 Friend signal", callback_data="reason_open:Friend signal"),
        InlineKeyboardButton(text="🚀 Pump chase", callback_data="reason_open:Pump chase"),
    )
    b.row(
        InlineKeyboardButton(text="🧠 Planned trade", callback_data="reason_open:Plan"),
        InlineKeyboardButton(text="✍️ Other", callback_data="reason_open:Other"),
    )
    return b.as_markup()


def kb_category() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="🐸 Meme", callback_data="category:Meme"),
        InlineKeyboardButton(text="🤖 AI", callback_data="category:AI"),
        InlineKeyboardButton(text="🏦 DeFi", callback_data="category:DeFi"),
    )
    b.row(
        InlineKeyboardButton(text="🎮 Gaming", callback_data="category:Gaming"),
        InlineKeyboardButton(text="🖼 NFT", callback_data="category:NFT"),
        InlineKeyboardButton(text="✍️ Other", callback_data="category:Other"),
    )
    return b.as_markup()


def kb_risk() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="🟢 Low Risk", callback_data="risk:Low Risk"),
        InlineKeyboardButton(text="🟡 Medium Risk", callback_data="risk:Medium Risk"),
    )
    b.row(
        InlineKeyboardButton(text="🔴 High Risk", callback_data="risk:High Risk"),
        InlineKeyboardButton(text="💀 YOLO", callback_data="risk:Yolo"),
    )
    return b.as_markup()


def kb_close_position(trade_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✅ Close Position", callback_data=f"close_position:{trade_id}"))
    return b.as_markup()


def kb_emotion_close() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="😌 Calm", callback_data="emotion_close:Calm"),
        InlineKeyboardButton(text="😤 FOMO", callback_data="emotion_close:FOMO"),
        InlineKeyboardButton(text="😡 Revenge", callback_data="emotion_close:Revenge"),
    )
    b.row(
        InlineKeyboardButton(text="😨 Panic", callback_data="emotion_close:Panic"),
        InlineKeyboardButton(text="😎 Confident", callback_data="emotion_close:Confident"),
        InlineKeyboardButton(text="✍️ Other", callback_data="emotion_close:Other"),
    )
    return b.as_markup()


def kb_emotion_close_auto(trade_id: int) -> InlineKeyboardMarkup:
    """Emotion close after auto-close — same options as manual close."""
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="😌 Calm", callback_data=f"emotion_close_auto:{trade_id}:Calm"),
        InlineKeyboardButton(text="😤 FOMO", callback_data=f"emotion_close_auto:{trade_id}:FOMO"),
        InlineKeyboardButton(text="😡 Revenge", callback_data=f"emotion_close_auto:{trade_id}:Revenge"),
    )
    b.row(
        InlineKeyboardButton(text="😨 Panic", callback_data=f"emotion_close_auto:{trade_id}:Panic"),
        InlineKeyboardButton(text="😎 Confident", callback_data=f"emotion_close_auto:{trade_id}:Confident"),
        InlineKeyboardButton(text="✍️ Other", callback_data=f"emotion_close_auto:{trade_id}:Other"),
    )
    return b.as_markup()


def kb_reason_close_auto(trade_id: int) -> InlineKeyboardMarkup:
    """Reason close after auto-close — same options as manual."""
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="🎯 Target hit", callback_data=f"reason_close_auto:{trade_id}:Target hit"),
        InlineKeyboardButton(text="🛑 Stop loss", callback_data=f"reason_close_auto:{trade_id}:Stop loss"),
    )
    b.row(
        InlineKeyboardButton(text="😨 Market fear", callback_data=f"reason_close_auto:{trade_id}:Market fear"),
        InlineKeyboardButton(text="🧻 Paper hands", callback_data=f"reason_close_auto:{trade_id}:Paper hands"),
    )
    b.row(InlineKeyboardButton(text="✍️ Other", callback_data=f"reason_close_auto:{trade_id}:Other"))
    return b.as_markup()


def kb_discipline_auto(trade_id: int) -> InlineKeyboardMarkup:
    """Discipline after auto-close."""
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="✅ Yes", callback_data=f"discipline_auto:{trade_id}:Yes"),
        InlineKeyboardButton(text="❌ No", callback_data=f"discipline_auto:{trade_id}:No"),
        InlineKeyboardButton(text="🤷 I had no plan", callback_data=f"discipline_auto:{trade_id}:I had no plan"),
    )
    return b.as_markup()


def kb_reason_close() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="🎯 Target hit", callback_data="reason_close:Target hit"),
        InlineKeyboardButton(text="🛑 Stop loss", callback_data="reason_close:Stop loss"),
    )
    b.row(
        InlineKeyboardButton(text="😨 Market fear", callback_data="reason_close:Market fear"),
        InlineKeyboardButton(text="🧻 Paper hands", callback_data="reason_close:Paper hands"),
    )
    b.row(InlineKeyboardButton(text="✍️ Other", callback_data="reason_close:Other"))
    return b.as_markup()


def kb_discipline() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="✅ Yes", callback_data="discipline:Yes"),
        InlineKeyboardButton(text="❌ No", callback_data="discipline:No"),
        InlineKeyboardButton(text="🤷 I had no plan", callback_data="discipline:I had no plan"),
    )
    return b.as_markup()


def kb_after_close(trade_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="📋 Copy contract", callback_data=f"copy_contract:{trade_id}"),
        InlineKeyboardButton(text="View Report", callback_data=f"view_report:{trade_id}"),
    )
    b.row(InlineKeyboardButton(text="Mark as Invalid", callback_data=f"mark_invalid:{trade_id}"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
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
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_empty() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[])


def kb_open_trades_list(open_trades: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for trade_id, symbol in open_trades:
        b.row(InlineKeyboardButton(text=f"📌 {symbol}", callback_data=f"position_detail:{trade_id}"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()



def kb_position_detail(trade_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✅ Close Position", callback_data=f"close_position:{trade_id}"))
    b.row(InlineKeyboardButton(text="🚫 Mark Invalid Token", callback_data=f"mark_invalid:{trade_id}"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_my_position(trade_id: int) -> InlineKeyboardMarkup:
    """Single 'My Position' button (e.g. after auto-DCA)."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📌 My Position", callback_data=f"position_detail:{trade_id}"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
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


# --- Settings / Wallet Auto Trade Detection ---


def kb_settings_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔗 Connect Wallet", callback_data="settings_connect_wallet"))
    b.row(InlineKeyboardButton(text="👛 Connected Wallets", callback_data="settings_connected_wallets"))
    b.row(InlineKeyboardButton(text="🤖 Auto Trade Detection", callback_data="settings_auto_detection"))
    b.row(InlineKeyboardButton(text="🌐 Timezone", callback_data="settings_timezone"))
    b.row(InlineKeyboardButton(text="💬 Contact Support", callback_data="support_start"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_payment_rejected_followup() -> InlineKeyboardMarkup:
    """After payment rejection: home + contact support."""
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="🏠 Back to Menu", callback_data=BACK_TO_MENU_DATA),
        InlineKeyboardButton(text="💬 Contact Support", callback_data="support_start"),
    )
    return b.as_markup()


# Timezone options: (offset_hours, label for button/display)
TIMEZONE_OPTIONS = [
    (0, "🌍 UTC (0)"),
    (1, "🇬🇧 UTC+1 (London / Europe)"),
    (3, "🇸🇦 UTC+3 (Middle East)"),
    (5, "🇮🇳 UTC+5 (India)"),
    (7, "🇮🇩 UTC+7 (WIB - Indonesia)"),
    (8, "🇸🇬 UTC+8 (Singapore / Hong Kong)"),
    (9, "🇯🇵 UTC+9 (Japan / Korea)"),
    (10, "🇦🇺 UTC+10 (Australia)"),
    (-3, "🇧🇷 UTC-3 (Brazil)"),
    (-5, "🇺🇸 UTC-5 (US East)"),
    (-8, "🇺🇸 UTC-8 (US West)"),
]


def kb_timezone_select(current_offset: Optional[int] = None) -> InlineKeyboardMarkup:
    """Timezone selection. If current_offset is set, the matching option is marked with ✅."""
    b = InlineKeyboardBuilder()
    for offset, label in TIMEZONE_OPTIONS:
        display = (label + " ✅") if (current_offset is not None and offset == current_offset) else label
        b.row(InlineKeyboardButton(text=display, callback_data=f"tz_set:{offset}"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_back_to_settings() -> InlineKeyboardMarkup:
    """Back to Settings menu (used from Connect Wallet, Connected Wallets)."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_connect_wallet_networks() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Solana", callback_data="wallet_network:Solana"))
    b.row(InlineKeyboardButton(text="BNB Chain", callback_data="wallet_network:BNB Chain"))
    b.row(InlineKeyboardButton(text="Base", callback_data="wallet_network:Base"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_record_trade_detected() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📝 Record Trade", callback_data="detected_record_trade"))
    b.row(InlineKeyboardButton(text="⏭ Ignore", callback_data="detected_ignore"))
    return b.as_markup()


def kb_record_trade_detected_with_id(pending_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📝 Record Trade", callback_data=f"pending_record:{pending_id}"))
    b.row(
        InlineKeyboardButton(text="⏭ Ignore", callback_data=f"detected_delete:{pending_id}"),
        InlineKeyboardButton(text="📥 Move to Pending", callback_data=f"detected_move_pending:{pending_id}"),
    )
    return b.as_markup()


def kb_dca_confirm(pending_dca_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📈 Add to position", callback_data=f"dca_confirm:{pending_dca_id}"))
    b.row(InlineKeyboardButton(text="⏭ Ignore", callback_data=f"dca_ignore:{pending_dca_id}"))
    return b.as_markup()


def kb_connected_wallets(wallets: list[tuple]) -> InlineKeyboardMarkup:
    """wallets: list of (wallet_id, user_id, wallet_address, network, auto_tracking_enabled, created_at)."""
    b = InlineKeyboardBuilder()
    for w in wallets:
        wallet_id, _, address, network, enabled, _ = w
        short = (address[:6] + "..." + address[-4:]) if len(address) > 14 else address
        label = f"{short} ({network})"
        b.row(InlineKeyboardButton(text=label, callback_data=f"wallet_detail:{wallet_id}"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_wallet_detail(wallet_id: int, auto_tracking_enabled: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    toggle_text = "Disable Auto Tracking" if auto_tracking_enabled else "Enable Auto Tracking"
    b.row(InlineKeyboardButton(text=toggle_text, callback_data=f"wallet_toggle:{wallet_id}"))
    b.row(InlineKeyboardButton(text="Remove Wallet", callback_data=f"wallet_remove:{wallet_id}"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_auto_detection_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📥 Pending", callback_data="pending_trades_list"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()

def kb_trade_review_actions(row_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📝 Record", callback_data=f"trade_review_record:{row_id}"))
    b.row(InlineKeyboardButton(text="⏭ Ignore", callback_data=f"trade_review_ignore:{row_id}"))
    b.row(InlineKeyboardButton(text="⬅️ Back", callback_data="pending_trades_list"))
    return b.as_markup()


def kb_trade_review_emotions() -> InlineKeyboardMarkup:
    """Emotion selection for Pending record flow (closed trades)."""
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="Calm", callback_data="tr_emotion:Calm"),
        InlineKeyboardButton(text="Fear", callback_data="tr_emotion:Fear"),
    )
    b.row(
        InlineKeyboardButton(text="Greed", callback_data="tr_emotion:Greed"),
        InlineKeyboardButton(text="FOMO", callback_data="tr_emotion:FOMO"),
    )
    b.row(
        InlineKeyboardButton(text="Revenge", callback_data="tr_emotion:Revenge"),
        InlineKeyboardButton(text="Other", callback_data="tr_emotion:Other"),
    )
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_pending_trades_list(pending_trades: list) -> InlineKeyboardMarkup:
    """pending_trades: list of PendingTrade objects."""
    b = InlineKeyboardBuilder()
    for pt in pending_trades:
        label = f"{pt.symbol} ({pt.network})"
        b.row(InlineKeyboardButton(text=label, callback_data=f"pending_detail:{pt.id}"))
    b.row(InlineKeyboardButton(text="⬅️ Back", callback_data="settings_auto_detection"))
    return b.as_markup()

def kb_pending_mixed_list(items: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """
    items: list of (label, callback_data) already prepared by handlers.
    Used to show a single Pending queue containing open + closed detections.
    """
    b = InlineKeyboardBuilder()
    for label, cb in items:
        b.row(InlineKeyboardButton(text=label, callback_data=cb))
    b.row(InlineKeyboardButton(text="⬅️ Back", callback_data="settings_auto_detection"))
    return b.as_markup()


def kb_pending_trade_actions(pending_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📝 Record", callback_data=f"pending_record:{pending_id}"))
    b.row(InlineKeyboardButton(text="⏭ Ignore", callback_data=f"pending_ignore:{pending_id}"))
    b.row(InlineKeyboardButton(text="⬅️ Back", callback_data="pending_trades_list"))
    return b.as_markup()


def kb_position_detail_auto(trade_id: int) -> InlineKeyboardMarkup:
    """Position detail for auto trades — no Close Position button."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🚫 Mark Invalid Token", callback_data=f"mark_invalid:{trade_id}"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()
