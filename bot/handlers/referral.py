"""
Earn & Invite: premium referral system. Link format BBT-<user_id>.
Rewards: +2 days inviter, +1 day referred. Commission levels 20% / 35% / 50%.
"""

import time as _time

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from bot.database.db import (
    get_user_referral_stats,
    get_referral_stats_detailed,
    get_referral_leaderboard,
)
from bot.keyboards import kb_referral_system, kb_referral_main
from bot.handlers.ui_flow import show_internal_screen

router = Router()

# Commission tiers: Level 1 (1-5): 20%, Level 2 (6-9): 35%, Level 3 (10+): 50%
REFERRAL_TIERS = [(1, 5, 20), (6, 9, 35), (10, 999, 50)]


def _tier_for_invites(invites: int) -> tuple[int, int, int]:
    """Return (level_min, level_max, rate_percent) for current tier."""
    for lo, hi, rate in REFERRAL_TIERS:
        if lo <= invites <= hi:
            return (lo, hi, rate)
    return (10, 999, 50)


def _next_tier_invites(invites: int) -> int | None:
    """Invites needed for next tier (6 or 10), or None if at max (10+)."""
    if invites >= 10:
        return None
    if invites < 5:
        return 6
    return 10


def _progress_bar(current: int, target: int, length: int = 10) -> str:
    """Visual progress bar: ████████░░ for current/target."""
    if target <= 0:
        return "█" * length
    filled = round((current / target) * length) if target else 0
    filled = min(length, max(0, filled))
    return "█" * filled + "░" * (length - filled)


REFERRAL_WELCOME_TEXT = """🚀 Earn with BehaveBot

Turn your network into real value.

Invite friends and unlock premium access + earn rewards.

🎁 Your Rewards:
+2 days Premium (first successful invite only)

🎁 Your Friend Gets:
+1 day Premium (first time only)

⚠️ Max Free Premium: 3 Days per user

━━━━━━━━━━━━━━━━━━

💰 Referral Commission System

1–5 Users → 20%
6–10 Users → 35%
10+ Users → 50%

━━━━━━━━━━━━━━━━━━

🏆 Top Alpha Referrers
Compete and climb the leaderboard.

🔥 Referral Contests (Coming Soon)"""


EARNING_GUIDE_TEXT = """💰 How You Earn

Every user you invite gives you:

• +2 days Premium access
• Commission from their purchases

━━━━━━━━━━━━━━━━━━

📊 Commission Levels:

1–5 Users → 20%
6–10 Users → 35%
10+ Users → 50%

━━━━━━━━━━━━━━━━━━

🧠 Strategy Tips:

• Share your results (P&L / stats)
• Show your premium insights
• Invite active traders, not random users

━━━━━━━━━━━━━━━━━━

🚀 Pro Tip:
Top referrers can generate passive income from premium users."""


_BOT_USERNAME: str | None = None
_BOT_USERNAME_UNTIL: float = 0.0


async def _get_bot_username(bot) -> str:
    global _BOT_USERNAME, _BOT_USERNAME_UNTIL
    now = _time.time()
    if _BOT_USERNAME and now < _BOT_USERNAME_UNTIL:
        return _BOT_USERNAME
    try:
        me = await bot.get_me()
        _BOT_USERNAME = me.username or "BehaveBot"
        _BOT_USERNAME_UNTIL = now + 600.0
        return _BOT_USERNAME
    except Exception:
        return "BehaveDevBot"


def _referral_link(bot_username: str, user_id: int) -> str:
    return f"https://t.me/{bot_username}?start=BBT-{user_id}"


async def show_referral_system_screen(origin: Message | CallbackQuery) -> None:
    """Show main Earn & Invite screen (single message / single edit)."""
    kb = kb_referral_system()
    if isinstance(origin, CallbackQuery):
        await origin.answer()
        await origin.message.edit_text(REFERRAL_WELCOME_TEXT, reply_markup=kb)
    else:
        await origin.answer(REFERRAL_WELCOME_TEXT, reply_markup=kb)


@router.message(F.text == "🚀 Earn & Invite")
async def menu_earn_invite(message: Message) -> None:
    """Main menu button: show Earn & Invite screen."""
    await show_referral_system_screen(message)


@router.message(Command("referral"))
async def cmd_referral(message: Message) -> None:
    """Show same Earn & Invite screen."""
    await show_referral_system_screen(message)


# ---- Generate Invite Link ----
@router.callback_query(F.data == "referral_generate_link")
async def referral_generate_link_cb(callback: CallbackQuery) -> None:
    await callback.answer()
    username = await _get_bot_username(callback.bot)
    link = _referral_link(username, callback.from_user.id)
    text = (
        "🔗 Your Personal Invite Link:\n\n"
        f"<code>{link}</code>\n\n"
        "Share this link and start earning 🚀"
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb_referral_system(), parse_mode="HTML")
    except Exception:
        await callback.message.edit_text(
            text.replace("<code>", "").replace("</code>", ""),
            reply_markup=kb_referral_system(),
        )


# Backward compatibility: old callback names
@router.callback_query(F.data == "referral_system_get_link")
async def referral_system_get_link_cb(callback: CallbackQuery) -> None:
    await referral_generate_link_cb(callback)


# ---- Earning Guide ----
@router.callback_query(F.data == "referral_earning_guide")
async def referral_earning_guide_cb(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        await callback.message.edit_text(EARNING_GUIDE_TEXT, reply_markup=kb_referral_system())
    except Exception:
        await callback.message.edit_text(EARNING_GUIDE_TEXT, reply_markup=kb_referral_system())


@router.callback_query(F.data == "referral_system_how_to_earn")
async def referral_system_how_to_earn_cb(callback: CallbackQuery) -> None:
    await referral_earning_guide_cb(callback)


# ---- My Referral Stats (with progress bar + projected earnings) ----
@router.callback_query(F.data == "referral_my_stats")
async def referral_my_stats_cb(callback: CallbackQuery) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    detailed = await get_referral_stats_detailed(user_id)
    total = detailed.get("total_invites", 0)
    active = detailed.get("active_users", total)
    premium_count = detailed.get("premium_conversions", 0)
    earned_days = detailed.get("earned_days", 0)

    # Projected earnings: if we had commission from premium (e.g. $6/mo * rate). Use placeholder when no real data.
    monthly_price = 6.0
    _, _, rate = _tier_for_invites(total)
    rate_frac = rate / 100.0
    if premium_count > 0:
        total_earned = premium_count * monthly_price * rate_frac
        total_earned_str = f"${total_earned:.2f}"
        earnings_label = "💰 Total Earned"
    else:
        total_earned_str = "—"
        earnings_label = "💰 Total Earned (Projected)"

    lines = [
        "📊 Your Referral Stats",
        "",
        f"Total Invites: {total}",
        f"Active Users: {active}",
        f"Premium Users: {premium_count}",
        "",
        f"{earnings_label}: {total_earned_str}",
        f"🎁 Premium Days Earned: {earned_days} days",
        "",
        "🚀 Your Progress to Next Tier",
    ]

    next_at = _next_tier_invites(total)
    if next_at is not None:
        bar = _progress_bar(total, next_at)
        lines.append(f"{bar} {total} / {next_at} users")
        lines.append("")
        lines.append(f"{next_at - total} more invites to unlock {_tier_for_invites(next_at)[2]}% commission")
    else:
        lines.append(f"{_progress_bar(10, 10)} {total} / 10+ users")
        lines.append("")
        lines.append("You're at max tier: 50% commission 🎉")

    if premium_count == 0 and total > 0:
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━")
        lines.append("💰 Projected Monthly Earnings")
        lines.append("")
        lines.append("If 10 users upgrade Monthly:")
        low = 10 * monthly_price * 0.20
        high = 10 * monthly_price * 0.50
        lines.append(f"→ You earn: ${low:.0f} – ${high:.0f}")

    text = "\n".join(lines)
    try:
        await callback.message.edit_text(text, reply_markup=kb_referral_system())
    except Exception:
        await callback.message.edit_text(text, reply_markup=kb_referral_system())


# ---- Top Alpha Referrers ----
@router.callback_query(F.data == "referral_top_alpha")
async def referral_top_alpha_cb(callback: CallbackQuery) -> None:
    await callback.answer()
    leaderboard = await get_referral_leaderboard(limit=10)
    lines = [
        "🏆 Top Alpha Referrers",
        "",
    ]
    badges = ["🥇", "🥈", "🥉"]
    for i, (uid, count) in enumerate(leaderboard):
        badge = badges[i] if i < 3 else f"{i + 1}."
        lines.append(f"{badge} User {uid} — {count} invite(s)")
    if not leaderboard:
        lines.append("No referrals yet. Be the first!")
    text = "\n".join(lines)
    try:
        await callback.message.edit_text(text, reply_markup=kb_referral_system())
    except Exception:
        await callback.message.edit_text(text, reply_markup=kb_referral_system())


@router.callback_query(F.data == "referral_leaderboard")
async def referral_leaderboard_cb(callback: CallbackQuery) -> None:
    await referral_top_alpha_cb(callback)


# ---- Legacy: Copy Link (old /referral screen) ----
@router.callback_query(F.data == "referral_copy_link")
async def referral_copy_link_cb(callback: CallbackQuery) -> None:
    await callback.answer()
    username = await _get_bot_username(callback.bot)
    link = _referral_link(username, callback.from_user.id)
    await callback.message.answer(
        f"🔗 Tap and hold to copy:\n\n<code>{link}</code>",
        parse_mode="HTML",
    )


async def _build_referral_message(bot, user_id: int) -> str:
    """Legacy: full message for old referral screen (Copy Link, My Stats, Leaderboard)."""
    stats = await get_user_referral_stats(user_id)
    total_invites = stats.get("total_invites", 0)
    earned_days = stats.get("earned_days", 0)
    leaderboard = await get_referral_leaderboard(limit=10)
    username = await _get_bot_username(bot)
    link = _referral_link(username, user_id)
    lines = [
        "🎁 Referral Program",
        "",
        "Invite your friends and unlock Premium access for FREE.",
        "",
        "Your benefits:",
        "• +2 days Premium for each successful invite",
        "",
        "Your friend's benefits:",
        "• +1 day Premium when they join",
        "",
        "📊 Your Stats:",
        f"• Total Invites: {total_invites}",
        f"• Earned Premium Days: {earned_days} days",
        "",
        "🏆 Top Alpha Referrers:",
    ]
    if leaderboard:
        for i, (_, count) in enumerate(leaderboard, 1):
            lines.append(f"{i}. {count} invite(s)")
    else:
        lines.append("No referrals yet. Be the first!")
    lines.append("")
    lines.append("Your Referral Link:")
    lines.append(f"<code>{link}</code>")
    lines.append("(Tap and hold to copy)")
    return "\n".join(lines)


