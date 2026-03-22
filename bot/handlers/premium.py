# Premium Feature System: conversion funnel + feature-gate. No changes to trade engine.

import asyncio
from collections import defaultdict
from datetime import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command

from bot.database.db import (
    get_valid_trades_for_stats,
    get_exit_totals_for_trades,
    get_user_premium_status,
    get_user_premium_status_fresh,
    get_user_timezone_offset,
    get_trade_timeline,
    get_recent_trades_count,
    get_referral_leaderboard,
    get_referral_tree,
    set_user_premium,
)
from bot.keyboards import (
    kb_premium_hub,
    kb_premium_active_hub,
    kb_back_to_premium_hub,
    kb_premium_landing,
    kb_premium_preview,
    kb_premium_free_access,
    kb_back_from_unified_preview,
    kb_back_to_premium_landing,
    kb_admin_panel,
    kb_admin_premium_input_nav,
    kb_after_premium_insight,
    kb_premium_insight_locked,
    ADMIN_PANEL_TEXT,
)
from bot.handlers.ui_flow import show_internal_screen
from bot.handlers.stats import (
    _trade_entry_total,
    _trade_pnl_from_totals,
    _format_time_slot_local,
)
from bot.states import AdminPremiumStates

router = Router()

PREVIEW_SCREEN_TEXT = """🔍 Premium Intelligence Preview

🧠 AI Trade Insight  🔒 Locked
We already analyzed your behavior…
Your biggest mistake pattern is detected.

📊 Advanced Dashboard  🔒 Locked
Your real win rate and hidden losses are calculated.

⏱ Smart Time Analysis  🔒 Locked
We know your most profitable trading window.

🎯 Token Analytics  🔒 Locked
Your strongest and weakest token categories are mapped.

📈 Behaviour Report  🔒 Locked
Your emotional trading pattern is fully decoded.

🧬 Pattern Detection  🔒 Locked
Your hidden habits are already recognized.

🚨 Risk Alert System  🔒 Locked
We detected when you are most likely to lose.

👑 Premium Status  🔒 Locked
Unlock full control + exclusive access."""

PRICING_SCREEN_TEXT = """💎 Choose your plan:
• Monthly — $6
• Yearly — $49
• Lifetime — $79"""

FREE_ACCESS_SCREEN_TEXT = """🔗 Referral System

Invite friends and earn FREE premium access.

You get: +2 days per referral
Your friend gets: +1 day"""

LOCKED_PREVIEW = """🔒 Premium Feature

Unlock advanced trading intelligence.

Available in BehaveBot Premium.

Use /premium to upgrade."""


def _premium_hub_title(is_premium: bool) -> str:
    if is_premium:
        return "💎 BehaveBot Pro"
    return "💎 BehaveBot Premium"


PREMIUM_ACTIVE_SEP = "━━━━━━━━━━━━━━━━━━"


async def build_premium_active_message(user_id: int) -> str:
    """Build full Premium Active screen text when user has paid_premium_active or referral_premium_days > 0."""
    status = await get_user_premium_status_fresh(user_id)
    paid_remaining = 0
    plan_label = "—"
    expiry_str = "—"
    if status.get("premium_expires_at"):
        try:
            from datetime import datetime
            expiry = datetime.fromisoformat(status["premium_expires_at"].replace("Z", ""))
            paid_remaining = max(0, (expiry - datetime.utcnow()).days)
            expiry_str = status["premium_expires_at"][:10] if len(status["premium_expires_at"]) >= 10 else status["premium_expires_at"]
        except Exception:
            pass
    plan_type = (status.get("plan_type") or "").strip().lower()
    if plan_type == "monthly":
        plan_label = "Monthly"
    elif plan_type == "yearly":
        plan_label = "Yearly"
    elif plan_type == "lifetime":
        plan_label = "Lifetime"
    elif status.get("purchased_active"):
        plan_label = status.get("plan_type") or "Premium"
    referral_remaining = status.get("referral_days_remaining", 0) or 0
    total_remaining = paid_remaining + referral_remaining

    sub_lines = ["⏳ Subscription:"]
    if status.get("purchased_active") and (plan_label != "—" or paid_remaining > 0):
        sub_lines.append(f"• Paid Plan: {plan_label}")
        sub_lines.append(f"• Expired In: {paid_remaining} days")
    else:
        sub_lines.append("• No paid plan")
    lines = [
        "💎 BehaveBot Premium",
        "",
        "Status: ACTIVE ✅",
        "",
    ]
    lines.extend(sub_lines)
    lines.extend([
        "",
        "🎁 Referral bonus:",
        f"• +{referral_remaining} days",
        "",
        "Total premium remaining:",
        f"• {total_remaining} days",
        "",
        PREMIUM_ACTIVE_SEP,
        "",
        "Tap 🧠 Premium Insight for your full report.",
        "Tap 💰 Earn with Referral to extend free.",
    ])
    return "\n".join(lines)


# ---- Feature gate: show module or locked preview ----

async def _gate(callback: CallbackQuery) -> bool:
    """Return True if user is premium, else False. Caller shows locked preview when False."""
    # Use fresh status to avoid stale gating after admin grant/revoke or referral day changes.
    status = await get_user_premium_status_fresh(callback.from_user.id)
    return status.get("is_premium", False)


async def _show_locked(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(LOCKED_PREVIEW, reply_markup=kb_back_to_premium_hub())


# ---- Premium Hub (Back from module) ----

async def _render_premium_hub(callback: CallbackQuery) -> None:
    """When premium active: show full Premium Active screen. Else show short hub (legacy)."""
    status = await get_user_premium_status_fresh(callback.from_user.id)
    if status.get("is_premium", False):
        text = await build_premium_active_message(callback.from_user.id)
        await callback.message.edit_text(text, reply_markup=kb_premium_active_hub())
    else:
        title = _premium_hub_title(False)
        text = f"{title}\n\nPreview insight (locked) or earn free days — tap below."
        await callback.message.edit_text(text, reply_markup=kb_premium_hub())


@router.callback_query(F.data == "premium_hub")
async def premium_hub_cb(callback: CallbackQuery) -> None:
    await callback.answer()
    await _render_premium_hub(callback)


async def _answer_unified_insight(callback: CallbackQuery) -> None:
    await callback.answer()
    text = await _build_premium_insight_unified(callback.from_user.id)
    await callback.message.edit_text(text, reply_markup=kb_after_premium_insight())


@router.callback_query(F.data == "premium_insight_unified")
async def premium_insight_unified_cb(callback: CallbackQuery) -> None:
    if await _gate(callback):
        await _answer_unified_insight(callback)
        return
    await callback.answer()
    await callback.message.edit_text(
        "🧠 Premium Insight\n\n"
        "Full report includes: why you win/lose, real win rate, best/worst hours & tokens, "
        "psychology (FOMO, revenge), habits, and live risk signals.\n\n"
        "💰 Referrals stack free days. 💎 Or unlock paid plans below.",
        reply_markup=kb_premium_insight_locked(),
    )


@router.callback_query(F.data == "premium_active_return")
async def premium_active_return_cb(callback: CallbackQuery) -> None:
    await callback.answer()
    text = await build_premium_active_message(callback.from_user.id)
    await callback.message.edit_text(text, reply_markup=kb_premium_active_hub())


@router.callback_query(F.data == "premium_earn_referral")
async def premium_earn_referral_cb(callback: CallbackQuery) -> None:
    from bot.handlers.referral import show_referral_system_screen

    await show_referral_system_screen(callback)


# ---- Landing / Preview / Pricing / Free Access ----

PREMIUM_LANDING_TEXT = (
    "🧠 BehaveBot Premium\n\n"
    "You are not losing to the market.\n"
    "You are losing to your own behavior.\n\n"
    "BehaveBot doesn't give signals.\n"
    "It reveals how you actually trade.\n\n"
    "It breaks down your decisions into patterns:\n"
    "when you perform best,\n"
    "where you lose control,\n"
    "and what habits quietly destroy your PnL.\n\n"
    "━━━━━━━━━━\n\n"
    "⚡ What you unlock:\n\n"
    "• Behavioral pattern detection (emotion, category, timing)\n"
    "• AI Insight (Edge / Weakness / Action / Confidence)\n"
    "• Hidden loss & true performance tracking\n"
    "• Time-based edge identification\n"
    "• Real-time risk alerts before you trade\n\n"
    "━━━━━━━━━━\n\n"
    "This is not analysis.\n"
    "This is self-exposure.\n\n"
    "{STATUS_DYNAMIC}\n\n"
    "━━━━━━━━━━━━━━━━━━"
)

UNIFIED_AI_PREVIEW_TEXT = """🧠 Your AI Trading Profile (Preview)

This is a surface-level breakdown of your trading behavior.

━━━━━━━━━━

🧠 Behavior Insight
You tend to lose when trading late at night.
Win rate drops from 62% → 38% after 23:00

📊 Performance Overview
Win Rate: 54%
Hidden Losses: -7.2%
Best Category: DeFi (+18%)
Worst Category: Meme (-23%)

⏱️ Time Analysis
Best Trading Window: 09:00–12:00
Worst Window: 23:00–02:00

🎯 Pattern Detected
You increase position size after a win
→ Leads to 1 oversized loss wiping gains

⚠️ Risk Alert
Overtrading detected (3 trades in 18 minutes)
Risk: Revenge trading

💡 AI Recommendation
• Avoid trading after 22:30
• Wait confirmation before entry
• Keep position size consistent

━━━━━━━━━━

🔍 This is only a preview.

Full AI Insight reveals:
• Your real edge (when you actually perform best)
• Your biggest weakness (what consistently drains your PnL)
• Real-time behavior warnings before you trade
• Clear, rule-based actions to fix your patterns

Most traders never see this level of insight.

You can.

━━━━━━━━━━━━━━━━━━"""


def _status_line(is_premium: bool) -> str:
    if is_premium:
        return "🔓 Status: Active\nYou have full access to all premium features."
    return "🔒 Status: Locked\nUnlock to access your full behavioral intelligence."


async def _build_premium_message(user_id: int) -> str:
    from bot.database.db import get_user_premium_status_fresh
    status = await get_user_premium_status_fresh(user_id)
    return PREMIUM_LANDING_TEXT.format(STATUS_DYNAMIC=_status_line(bool(status.get("is_premium"))))


@router.callback_query(F.data == "premium_landing")
async def premium_landing_cb(callback: CallbackQuery) -> None:
    """Back to landing: unified intelligence preview + Unlock, Back."""
    await callback.answer()
    await callback.message.edit_text(await _build_premium_message(callback.from_user.id), reply_markup=kb_premium_landing())


@router.callback_query(F.data == "premium_unified_preview")
async def premium_unified_preview_cb(callback: CallbackQuery) -> None:
    """Single unified AI analysis preview — one powerful output."""
    await callback.answer()
    await callback.message.edit_text(UNIFIED_AI_PREVIEW_TEXT, reply_markup=kb_back_from_unified_preview())


@router.callback_query(F.data == "premium_try_free_premium")
async def premium_try_free_premium_cb(callback: CallbackQuery) -> None:
    """UI-only: Try Free Access redirects to Earn & Invite main page."""
    from bot.handlers.referral import show_referral_system_screen
    await show_referral_system_screen(callback)


@router.callback_query(F.data == "premium_landing_free")
async def premium_landing_free_cb(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(FREE_ACCESS_SCREEN_TEXT, reply_markup=kb_premium_free_access())


@router.callback_query(F.data == "premium_landing_unlock")
async def premium_landing_unlock_cb(callback: CallbackQuery) -> None:
    await callback.answer()
    from bot.handlers.payment import show_premium_payment_screen

    await show_premium_payment_screen(callback)


@router.callback_query(F.data == "premium_pricing_back")
async def premium_pricing_back_cb(callback: CallbackQuery) -> None:
    await callback.answer()
    text = (
        "💎 BehaveBot Premium\n\n"
        "Unlock deeper insights into your trading behavior.\n\n"
        "Choose an option below:"
    )
    await callback.message.edit_text(text, reply_markup=kb_premium_landing())


@router.callback_query(F.data == "premium_free_invite")
async def premium_free_invite_cb(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        me = await callback.bot.get_me()
        username = me.username or "BehaveBot"
        link = f"https://t.me/{username}?start=BBT-{callback.from_user.id}"
        text = f"Your referral link:\n\n<code>{link}</code>"
    except Exception:
        text = "Your referral link:\n\n" + f"https://t.me/BehaveBot?start=BBT-{callback.from_user.id}"
    try:
        await callback.message.edit_text(text, reply_markup=kb_premium_free_access(), parse_mode="HTML")
    except Exception:
        await callback.message.edit_text(text, reply_markup=kb_premium_free_access())


@router.callback_query(F.data == "premium_free_how_to_earn")
async def premium_free_how_to_earn_cb(callback: CallbackQuery) -> None:
    """Redirect to main Earn & Invite referral menu (no duplicated logic)."""
    from bot.handlers.referral import show_referral_system_screen
    await show_referral_system_screen(callback)


# ---- AI Trade Insight ----

async def _build_ai_insight(user_id: int) -> str:
    trades = await get_valid_trades_for_stats(user_id)
    if not trades:
        return "🧠 AI Trade Insight\n\nNo closed trades yet. Close some positions to see insights."
    trade_ids = [t.trade_id for t in trades if t.trade_id]
    exit_totals = await get_exit_totals_for_trades(trade_ids) if trade_ids else {}
    by_cat = defaultdict(list)
    by_emotion = defaultdict(list)
    for t in trades:
        entry = _trade_entry_total(t)
        ex = exit_totals.get(t.trade_id, 0.0) or 0.0
        pnl = _trade_pnl_from_totals(entry, ex)
        if t.token_category:
            by_cat[t.token_category].append(pnl)
        if t.emotion_open:
            by_emotion[t.emotion_open].append(pnl)
    best_cat = max(by_cat.items(), key=lambda x: sum(x[1]) / len(x[1]) if x[1] else -999) if by_cat else None
    worst_emotion = min(by_emotion.items(), key=lambda x: sum(x[1]) / len(x[1]) if x[1] else 999) if by_emotion else None
    lines = ["🧠 AI Trade Insight", ""]
    if best_cat:
        avg = sum(best_cat[1]) / len(best_cat[1])
        lines.append(f"Best performing category:\n{best_cat[0]}")
        lines.append(f"Average result: {round(avg, 1):+.1f}%")
        lines.append("")
    if worst_emotion:
        avg = sum(worst_emotion[1]) / len(worst_emotion[1])
        lines.append(f"Worst emotion:\n{worst_emotion[0]}")
        lines.append(f"Average loss when {worst_emotion[0]}: {round(avg, 1):+.1f}%")
        lines.append("")
    if worst_emotion:
        lines.append("Recommendation:")
        lines.append(f"Avoid trading during {worst_emotion[0]} emotion.")
    return "\n".join(lines) if lines else "🧠 AI Trade Insight\n\nNot enough data."


@router.callback_query(F.data == "premium_ai_insight")
async def premium_ai_insight_cb(callback: CallbackQuery) -> None:
    if not await _gate(callback):
        await callback.answer()
        # Preview for free users: one-line insight from their data
        trades = await get_valid_trades_for_stats(callback.from_user.id)
        if trades:
            trade_ids = [t.trade_id for t in trades if t.trade_id]
            exit_totals = await get_exit_totals_for_trades(trade_ids) if trade_ids else {}
            by_cat = defaultdict(list)
            for t in trades:
                if t.token_category:
                    entry = _trade_entry_total(t)
                    ex = exit_totals.get(t.trade_id, 0.0) or 0.0
                    by_cat[t.token_category].append(_trade_pnl_from_totals(entry, ex))
            best_cat = max(by_cat.items(), key=lambda x: sum(x[1]) / len(x[1]) if x[1] else -999) if by_cat else None
            if best_cat:
                preview = f"🧠 AI Insight Preview\n\nYou perform best when trading {best_cat[0]} tokens.\n\nUnlock full analysis in Premium."
            else:
                preview = LOCKED_PREVIEW
        else:
            preview = LOCKED_PREVIEW
        await callback.message.edit_text(preview, reply_markup=kb_back_to_premium_hub())
        return
    await _answer_unified_insight(callback)


# ---- Advanced Performance Dashboard ----

async def _build_dashboard(user_id: int) -> str:
    trades = await get_valid_trades_for_stats(user_id)
    if not trades:
        return "📊 Advanced Performance\n\nNo closed trades yet."
    trade_ids = [t.trade_id for t in trades if t.trade_id]
    exit_totals = await get_exit_totals_for_trades(trade_ids) if trade_ids else {}
    pnls = []
    profits = []
    losses = []
    durations = []
    dca_wins = 0
    dca_total = 0
    for t in trades:
        entry = _trade_entry_total(t)
        ex = exit_totals.get(t.trade_id, 0.0) or 0.0
        pnl = _trade_pnl_from_totals(entry, ex)
        pnls.append(pnl)
        if pnl >= 0:
            profits.append(pnl)
        else:
            losses.append(pnl)
        if t.duration is not None:
            durations.append(float(t.duration))
        timeline = await get_trade_timeline(t.trade_id) if t.trade_id else []
        dca_events = [e for e in timeline if (e.get("event_type") or "").upper() in ("DCA", "BUY", "OPEN")]
        if len(dca_events) > 1:
            dca_total += 1
            if pnl >= 0:
                dca_wins += 1
    avg_pnl = sum(pnls) / len(pnls) if pnls else 0
    avg_profit = sum(profits) / len(profits) if profits else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    avg_dur = sum(durations) / len(durations) if durations else 0
    from bot.utils.formatters import format_duration_seconds
    avg_dur_str = format_duration_seconds(avg_dur)
    rr = abs(avg_profit / avg_loss) if avg_loss and avg_loss != 0 else 0
    dca_rate = (dca_wins / dca_total * 100) if dca_total else 0
    lines = [
        "📊 Advanced Performance",
        "",
        f"Average profit: {round(avg_profit, 1):+.1f}%",
        f"Average loss: {round(avg_loss, 1):+.1f}%",
        "",
        f"Risk reward ratio: {rr:.2f}R",
        "",
        f"Average holding time: {avg_dur_str}",
        "",
        f"DCA success rate: {round(dca_rate, 0):.0f}%",
    ]
    return "\n".join(lines)


async def _build_performance_lite(user_id: int) -> str:
    """Compact performance for unified Premium Insight."""
    trades = await get_valid_trades_for_stats(user_id)
    if not trades:
        return "No closed trades yet."
    trade_ids = [t.trade_id for t in trades if t.trade_id]
    exit_totals = await get_exit_totals_for_trades(trade_ids) if trade_ids else {}
    pnls = []
    by_cat: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        entry = _trade_entry_total(t)
        ex = exit_totals.get(t.trade_id, 0.0) or 0.0
        pnl = _trade_pnl_from_totals(entry, ex)
        pnls.append(pnl)
        if t.token_category:
            by_cat[t.token_category].append(pnl)
    wins = sum(1 for p in pnls if p >= 0)
    wr = wins / len(pnls) * 100 if pnls else 0.0
    losses = [p for p in pnls if p < 0]
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    best_line = "—"
    worst_line = "—"
    if by_cat:
        best = max(by_cat.items(), key=lambda x: sum(x[1]) / len(x[1]) if x[1] else -999)
        worst = min(by_cat.items(), key=lambda x: sum(x[1]) / len(x[1]) if x[1] else 999)
        best_line = f"{best[0]} ({sum(best[1]) / len(best[1]):+.1f}%)"
        worst_line = f"{worst[0]} ({sum(worst[1]) / len(worst[1]):+.1f}%)"
    return (
        f"Win rate: {wr:.0f}%\n"
        f"Hidden losses (avg per losing trade): {avg_loss:.1f}%\n"
        f"Best category: {best_line}\n"
        f"Worst category: {worst_line}"
    )


async def _build_ai_summary_unified(trades: list, exit_totals: dict) -> str:
    """Three lines: strongest edge, biggest weakness, one action — no markdown, minimal overlap with stat blocks."""
    if not trades:
        return "No closed trades yet. Close trades to unlock actionable patterns."

    user_id = trades[0].user_id
    tz_offset = await get_user_timezone_offset(user_id)
    recent_n = await get_recent_trades_count(user_id, 20)
    MIN_GRP = 3
    n_all = len(trades)
    small = n_all < 10

    by_emotion: dict[str, list[float]] = defaultdict(list)
    by_cat: dict[str, list[float]] = defaultdict(list)
    bucket_pnl: dict[int, list[float]] = defaultdict(list)

    for t in trades:
        entry = _trade_entry_total(t)
        ex = exit_totals.get(t.trade_id, 0.0) or 0.0
        pnl = _trade_pnl_from_totals(entry, ex)
        if t.emotion_open:
            by_emotion[str(t.emotion_open)].append(pnl)
        if t.token_category:
            by_cat[str(t.token_category)].append(pnl)
        if t.close_time:
            try:
                ct = t.close_time if isinstance(t.close_time, datetime) else datetime.fromisoformat(str(t.close_time))
                b = (ct.hour // 3) * 3
                bucket_pnl[b].append(pnl)
            except Exception:
                pass

    def _eligible_max(items: dict[str, list[float]]):
        ok = [(k, v) for k, v in items.items() if len(v) >= MIN_GRP]
        if not ok:
            return None
        return max(ok, key=lambda kv: sum(kv[1]) / len(kv[1]))

    def _eligible_min(items: dict[str, list[float]]):
        ok = [(k, v) for k, v in items.items() if len(v) >= MIN_GRP]
        if not ok:
            return None
        return min(ok, key=lambda kv: sum(kv[1]) / len(kv[1]))

    best_cat = _eligible_max(by_cat)
    worst_cat = _eligible_min(by_cat)
    best_emo = _eligible_max(by_emotion)
    worst_emo = _eligible_min(by_emotion)
    best_bucket = _eligible_max(bucket_pnl)
    worst_bucket = _eligible_min(bucket_pnl)

    # (kind, label_for_display, mean) — only buckets with len >= MIN_GRP
    prio = {"time": 0, "emotion": 1, "category": 2}
    edge_candidates: list[tuple[str, str, float]] = []
    if best_bucket:
        m = sum(best_bucket[1]) / len(best_bucket[1])
        slot = _format_time_slot_local(best_bucket[0], 3, tz_offset)
        edge_candidates.append(("time", slot, m))
    if best_emo:
        m = sum(best_emo[1]) / len(best_emo[1])
        edge_candidates.append(("emotion", str(best_emo[0]), m))
    if best_cat:
        m = sum(best_cat[1]) / len(best_cat[1])
        edge_candidates.append(("category", str(best_cat[0]), m))

    weak_candidates: list[tuple[str, str, float]] = []
    if worst_bucket:
        m = sum(worst_bucket[1]) / len(worst_bucket[1])
        slot = _format_time_slot_local(worst_bucket[0], 3, tz_offset)
        weak_candidates.append(("time", slot, m))
    if worst_emo:
        m = sum(worst_emo[1]) / len(worst_emo[1])
        weak_candidates.append(("emotion", str(worst_emo[0]), m))
    if worst_cat:
        m = sum(worst_cat[1]) / len(worst_cat[1])
        weak_candidates.append(("category", str(worst_cat[0]), m))

    edge_pick = None
    if edge_candidates:
        edge_pick = max(edge_candidates, key=lambda x: (x[2], -prio[x[0]]))

    weak_pick = None
    if weak_candidates:
        weak_sorted = sorted(weak_candidates, key=lambda x: (x[2], prio[x[0]]))
        for w in weak_sorted:
            if edge_pick is None or (w[0], w[1]) != (edge_pick[0], edge_pick[1]):
                weak_pick = w
                break

    def _edge_line(kind: str, label: str) -> str:
        if small:
            if kind == "time":
                return f"Edge: {label} is your strongest window right now — press it harder as data stacks."
            if kind == "emotion":
                return f"Edge: {label} is where you run hot — own it and press."
            return f"Edge: {label} is your top setup type — default to it."
        if kind == "time":
            return f"Edge: your clearest rhythm is {label} — own that window."
        if kind == "emotion":
            return f"Edge: {label} is where you actually print — double down on that headspace."
        return f"Edge: {label} is your real edge — size it on purpose, not by habit."

    def _weak_line(kind: str, label: str) -> str:
        if small:
            if kind == "time":
                return f"Weakness: {label} is where you lose control — cut it."
            if kind == "emotion":
                return f"Weakness: {label} entries are your biggest leak — stop it."
            return f"Weakness: {label} is your biggest leak — stop it."
        if kind == "time":
            return f"Weakness: {label} is where you lose control — cut it."
        if kind == "emotion":
            return f"Weakness: {label} entries are your biggest leak — stop it."
        return f"Weakness: {label} setups are your biggest leak — stop it."

    edge_line = "Edge: repeated buckets still thin — tag emotion, category, and time until it breaks open."
    if edge_pick:
        edge_line = _edge_line(edge_pick[0], edge_pick[1])

    weak_line = "Weakness: leak not pinned yet — cut size everywhere until the data names it."
    if weak_pick:
        weak_line = _weak_line(weak_pick[0], weak_pick[1])

    # One actionable line — no duplicate of Risk stats (no trade count)
    if recent_n >= 3:
        action_line = (
            "Action: burst of entries — full stop. Next trade must follow your plan — or skip it."
        )
    elif weak_pick and weak_pick[0] == "emotion":
        action_line = "Action: that state hits — step away 10 minutes — no entry allowed."
    elif edge_pick and edge_pick[0] == "time" and not small:
        action_line = (
            "Action: strong window only this week — outside it, no entries. No exceptions."
        )
    else:
        action_line = "Action: every entry — tag mood and category. No tag — no trade."

    if len(action_line) > 220:
        action_line = action_line[:217] + "…"

    # Last 3 closed trades (trades are newest-first): warn if ≥2 losses share same emotion_open
    warn_line: str | None = None
    last3 = trades[:3]
    if len(last3) >= 2:
        neg_emotions: list[str] = []
        for t in last3:
            entry = _trade_entry_total(t)
            ex = exit_totals.get(t.trade_id, 0.0) or 0.0
            pnl = _trade_pnl_from_totals(entry, ex)
            if pnl < 0:
                emo = (t.emotion_open or "").strip()
                if emo:
                    neg_emotions.append(emo)
        if len(neg_emotions) >= 2 and len(set(neg_emotions)) == 1:
            warn_line = (
                f"Warning: Recent losses cluster around {neg_emotions[0]} entries — "
                "this is a repeat pattern — not random."
            )

    if n_all < 10:
        conf_line = "Confidence: Low — data is too thin — nothing here is reliable yet."
    elif n_all < 30:
        conf_line = "Confidence: Medium — patterns are forming — but still unstable."
    else:
        conf_line = "Confidence: High — your behavior pattern is consistent and actionable."

    parts_out: list[str] = [edge_line, weak_line]
    if warn_line:
        parts_out.append(warn_line)
    parts_out.append(action_line)
    parts_out.append(conf_line)

    out = "\n\n".join(parts_out)
    if len(out) > 900:
        out = out[:897] + "…"
    return out


@router.callback_query(F.data == "premium_dashboard")
async def premium_dashboard_cb(callback: CallbackQuery) -> None:
    if not await _gate(callback):
        await _show_locked(callback)
        return
    await _answer_unified_insight(callback)


# ---- Smart Time Trading Analysis ----

async def _build_smart_time(user_id: int) -> str:
    trades = await get_valid_trades_for_stats(user_id)
    if not trades:
        return "⏱ Smart Time Analysis\n\nNo closed trades yet."
    tz_offset = await get_user_timezone_offset(user_id)
    trade_ids = [t.trade_id for t in trades if t.trade_id]
    exit_totals = await get_exit_totals_for_trades(trade_ids) if trade_ids else {}
    bucket_pnl = defaultdict(list)
    for t in trades:
        if not t.close_time:
            continue
        ct = t.close_time if isinstance(t.close_time, datetime) else datetime.fromisoformat(str(t.close_time))
        h = ct.hour
        bucket = (h // 3) * 3
        entry = _trade_entry_total(t)
        ex = exit_totals.get(t.trade_id, 0.0) or 0.0
        pnl = _trade_pnl_from_totals(entry, ex)
        bucket_pnl[bucket].append(pnl)
    if not bucket_pnl:
        return "⏱ Smart Time Analysis\n\nNo time data."
    sorted_buckets = sorted(
        bucket_pnl.items(),
        key=lambda x: sum(x[1]) / len(x[1]) if x[1] else -999,
        reverse=True,
    )
    lines = ["⏱ Smart Time Analysis", ""]
    if len(sorted_buckets) >= 1:
        b, pnls = sorted_buckets[0]
        slot = _format_time_slot_local(b, 3, tz_offset)
        avg = sum(pnls) / len(pnls) if pnls else 0
        lines.append("Best trading window:")
        lines.append(f"{slot}")
        lines.append(f"Average result: {round(avg, 1):+.1f}%")
        lines.append("")
    if len(sorted_buckets) >= 2:
        b, pnls = sorted_buckets[1]
        slot = _format_time_slot_local(b, 3, tz_offset)
        avg = sum(pnls) / len(pnls) if pnls else 0
        lines.append("Second best:")
        lines.append(f"{slot}")
        lines.append(f"Average result: {round(avg, 1):+.1f}%")
        lines.append("")
    worst = min(bucket_pnl.items(), key=lambda x: sum(x[1]) / len(x[1]) if x[1] else 999)
    slot = _format_time_slot_local(worst[0], 3, tz_offset)
    avg = sum(worst[1]) / len(worst[1]) if worst[1] else 0
    lines.append("Worst window:")
    lines.append(f"{slot}")
    lines.append(f"Average result: {round(avg, 1):+.1f}%")
    return "\n".join(lines)


@router.callback_query(F.data == "premium_smart_time")
async def premium_smart_time_cb(callback: CallbackQuery) -> None:
    if not await _gate(callback):
        await _show_locked(callback)
        return
    await _answer_unified_insight(callback)


# ---- Token Performance Deep Analytics ----

async def _build_token_analytics(user_id: int) -> str:
    trades = await get_valid_trades_for_stats(user_id)
    if not trades:
        return "🎯 Token Analytics\n\nNo closed trades yet."
    trade_ids = [t.trade_id for t in trades if t.trade_id]
    exit_totals = await get_exit_totals_for_trades(trade_ids) if trade_ids else {}
    by_cat = defaultdict(list)
    by_token = defaultdict(list)
    for t in trades:
        entry = _trade_entry_total(t)
        ex = exit_totals.get(t.trade_id, 0.0) or 0.0
        pnl = _trade_pnl_from_totals(entry, ex)
        if t.token_category:
            by_cat[t.token_category].append(pnl)
        if t.token_symbol:
            by_token[t.token_symbol].append(pnl)
    lines = ["🎯 Token Analytics", ""]
    if by_cat:
        best_cat = max(by_cat.items(), key=lambda x: sum(x[1]) / len(x[1]) if x[1] else -999)
        worst_cat = min(by_cat.items(), key=lambda x: sum(x[1]) / len(x[1]) if x[1] else 999)
        lines.append(f"Best token category:\n{best_cat[0]} {round(sum(best_cat[1])/len(best_cat[1]), 1):+.1f}%")
        lines.append("")
        lines.append(f"Worst token category:\n{worst_cat[0]} {round(sum(worst_cat[1])/len(worst_cat[1]), 1):+.1f}%")
        lines.append("")
    if by_token:
        best_tok = max(by_token.items(), key=lambda x: sum(x[1]) / len(x[1]) if x[1] else -999)
        worst_tok = min(by_token.items(), key=lambda x: sum(x[1]) / len(x[1]) if x[1] else 999)
        lines.append(f"Most profitable token:\n{best_tok[0]} {round(sum(best_tok[1])/len(best_tok[1]), 1):+.1f}%")
        lines.append("")
        lines.append(f"Largest loss:\n{worst_tok[0]} {round(sum(worst_tok[1])/len(worst_tok[1]), 1):+.1f}%")
    return "\n".join(lines) if lines else "🎯 Token Analytics\n\nNot enough data."


@router.callback_query(F.data == "premium_token_analytics")
async def premium_token_analytics_cb(callback: CallbackQuery) -> None:
    if not await _gate(callback):
        await _show_locked(callback)
        return
    await _answer_unified_insight(callback)


# ---- Trade Behaviour Report ----

async def _build_behaviour_report(user_id: int) -> str:
    trades = await get_valid_trades_for_stats(user_id)
    if not trades:
        return "📈 Behaviour Report\n\nNo closed trades yet."
    trade_ids = [t.trade_id for t in trades if t.trade_id]
    exit_totals = await get_exit_totals_for_trades(trade_ids) if trade_ids else {}
    by_emotion = defaultdict(list)
    for t in trades:
        entry = _trade_entry_total(t)
        ex = exit_totals.get(t.trade_id, 0.0) or 0.0
        pnl = _trade_pnl_from_totals(entry, ex)
        if t.emotion_open:
            by_emotion[t.emotion_open].append(pnl)
    most_used = max(by_emotion.items(), key=lambda x: len(x[1])) if by_emotion else None
    lines = ["📈 Behaviour Report", ""]
    if most_used:
        lines.append(f"Emotion used most:\n{most_used[0]}")
        lines.append("")
    for emo, pnls in sorted(by_emotion.items(), key=lambda x: -len(x[1])):
        wins = sum(1 for p in pnls if p >= 0)
        rate = wins / len(pnls) * 100 if pnls else 0
        lines.append(f"Win rate when {emo.lower()}: {round(rate, 0):.0f}%")
    fear_count = len(by_emotion.get("Fear", []))
    if fear_count:
        fear_pnls = by_emotion["Fear"]
        lines.append("")
        lines.append(f"Trades made during fear: {fear_count}")
        lines.append(f"Average result: {round(sum(fear_pnls)/len(fear_pnls), 1):+.1f}%")
    return "\n".join(lines)


@router.callback_query(F.data == "premium_behaviour_report")
async def premium_behaviour_report_cb(callback: CallbackQuery) -> None:
    if not await _gate(callback):
        await _show_locked(callback)
        return
    await _answer_unified_insight(callback)


# ---- Behavioral Pattern Detection ----

async def _build_pattern_detection(user_id: int) -> str:
    trades = await get_valid_trades_for_stats(user_id)
    if not trades:
        return "🧠 Pattern Detection\n\nNo closed trades yet."
    trade_ids = [t.trade_id for t in trades if t.trade_id]
    exit_totals = await get_exit_totals_for_trades(trade_ids) if trade_ids else {}
    # Strategy: (category, duration_bucket) -> list of pnl
    strategy_pnl = defaultdict(list)
    # Worst: emotion + category
    emotion_cat_pnl = defaultdict(list)
    for t in trades:
        entry = _trade_entry_total(t)
        ex = exit_totals.get(t.trade_id, 0.0) or 0.0
        pnl = _trade_pnl_from_totals(entry, ex)
        cat = t.token_category or "Other"
        dur = t.duration or 0
        bucket = "under 3h" if dur < 3 * 3600 else "3h+"
        strategy_pnl[(cat, bucket)].append(pnl)
        if t.emotion_open and cat:
            emotion_cat_pnl[(t.emotion_open, cat)].append(pnl)
    best_strategy = max(strategy_pnl.items(), key=lambda x: sum(x[1]) / len(x[1]) if x[1] else -999) if strategy_pnl else None
    worst_pattern = min(emotion_cat_pnl.items(), key=lambda x: sum(x[1]) / len(x[1]) if x[1] else 999) if emotion_cat_pnl else None
    lines = ["🧠 Pattern Detection", ""]
    if best_strategy:
        (cat, bucket), pnls = best_strategy
        avg = sum(pnls) / len(pnls) if pnls else 0
        lines.append("Your most successful strategy:")
        lines.append(f"{cat} tokens")
        lines.append(f"Holding time {bucket}")
        lines.append("")
        lines.append(f"Average result: {round(avg, 1):+.1f}%")
        lines.append("")
    if worst_pattern:
        (emo, cat), pnls = worst_pattern
        avg = sum(pnls) / len(pnls) if pnls else 0
        lines.append("Worst pattern:")
        lines.append(f"{emo} + {cat} tokens")
        lines.append("")
        lines.append(f"Average loss: {round(avg, 1):+.1f}%")
    return "\n".join(lines) if lines else "🧠 Pattern Detection\n\nNot enough data."


@router.callback_query(F.data == "premium_pattern")
async def premium_pattern_cb(callback: CallbackQuery) -> None:
    if not await _gate(callback):
        await _show_locked(callback)
        return
    await _answer_unified_insight(callback)


# ---- Premium Status (details page) ----

def _premium_badge(plan_type: str, has_referral: bool) -> str:
    """Optional tier: Gold / Pro / Elite."""
    pt = (plan_type or "").strip().lower()
    if pt == "lifetime":
        return "🔴 Elite"
    if pt == "yearly":
        return "🔵 Pro"
    if pt == "monthly":
        return "🟡 Gold"
    if has_referral:
        return "🔵 Pro"
    return "🟡 Gold"


async def _build_status_compact(user_id: int) -> str:
    """One block for unified insight."""
    status = await get_user_premium_status(user_id)
    plan_type = (status.get("plan_type") or "").strip().lower()
    pl = status.get("plan_type") or "—"
    if pl and str(pl).strip() != "—":
        pl = str(pl).strip().capitalize()
    ref = int(status.get("referral_days_remaining", 0) or 0)
    badge = _premium_badge(plan_type, ref > 0)
    exp = status.get("premium_expires_at")
    exp_s = (str(exp)[:10] if exp and len(str(exp)) >= 10 else str(exp)) if exp else "—"
    paid_rem = 0
    if exp:
        try:
            exd = datetime.fromisoformat(str(exp).replace("Z", ""))
            paid_rem = max(0, (exd - datetime.utcnow()).days)
        except Exception:
            pass
    total = paid_rem + ref
    return (
        f"Premium badge: {badge}\n"
        f"Plan: {pl}\n"
        f"Paid plan expiry: {exp_s}\n"
        f"Referral days: {ref}\n"
        f"Total premium left: ~{total} days"
    )


async def _build_risk_unified(user_id: int) -> str:
    n = await get_recent_trades_count(user_id, 20)
    if n >= 3:
        return (
            f"{n} trades in ~20 min — elevated pace. "
            "Pause before new entries; revenge clusters often follow losses."
        )
    return (
        f"{n} trade(s) recently. No burst alert. "
        "After a red trade, wait for a clear setup — FOMO entries underperform."
    )


def _insight_section_body(text: str, max_len: int = 380) -> str:
    lines = text.strip().split("\n")
    body = "\n".join(lines[2:]).strip() if len(lines) > 2 else text.strip()
    if not body:
        return "—"
    if len(body) > max_len:
        return body[: max_len - 2] + "…"
    return body


async def _build_premium_insight_unified(user_id: int) -> str:
    trades = await get_valid_trades_for_stats(user_id)
    if not trades:
        return (
            "🧠 Premium Insight\n\n"
            "📌 Summary\n"
            "Win Rate: —\nBest Edge: —\nBiggest Risk: —\n\n"
            "📊 Performance\n"
            "PnL: —\nAvg Loss: —\nBest Category: —\nWorst Category: —\n\n"
            "⏰ Time Edge\n"
            "Best: —\nWorst: —\n\n"
            "🎯 Token Edge\n"
            "Top Token: —\nWeak Sector: —\n\n"
            "🧩 Behavior\n"
            "Dominant: —\nBest Emotion: —\nWorst Emotion: —\n\n"
            "🔍 Pattern\n"
            "Best: —\nWorst: —\n\n"
            "🚨 Risk\n"
            "No closed trades yet.\n\n"
            "━━━━━━━━━━\n\n"
            "🧠 AI Insight\n\n"
            "Close trades to unlock actionable insights.\n\n"
            "━━━━━━━━━━\n\n"
            "Sample: 0"
        )

    trade_ids = [t.trade_id for t in trades if t.trade_id]
    exit_totals = await get_exit_totals_for_trades(trade_ids) if trade_ids else {}
    tz_offset = await get_user_timezone_offset(user_id)
    recent_n = await get_recent_trades_count(user_id, 20)

    pnls: list[float] = []
    by_cat: dict[str, list[float]] = defaultdict(list)
    by_token: dict[str, list[float]] = defaultdict(list)
    by_emotion: dict[str, list[float]] = defaultdict(list)
    by_emotion_cat: dict[tuple[str, str], list[float]] = defaultdict(list)
    by_pattern: dict[tuple[str, str], list[float]] = defaultdict(list)  # (category, duration bucket)
    bucket_pnl: dict[int, list[float]] = defaultdict(list)

    for t in trades:
        entry = _trade_entry_total(t)
        ex = exit_totals.get(t.trade_id, 0.0) or 0.0
        pnl = _trade_pnl_from_totals(entry, ex)
        pnls.append(pnl)

        cat = (t.token_category or "").strip()
        if cat:
            by_cat[cat].append(pnl)
            if t.emotion_open:
                by_emotion_cat[(str(t.emotion_open), cat)].append(pnl)

        sym = (t.token_symbol or "").strip()
        if sym:
            by_token[sym].append(pnl)

        emo = (t.emotion_open or "").strip()
        if emo:
            by_emotion[emo].append(pnl)

        dur = t.duration or 0
        dur_bucket = "under 3h" if dur < 3 * 3600 else "3h+"
        by_pattern[(cat or "Other", dur_bucket)].append(pnl)

        if t.close_time:
            try:
                ct = t.close_time if isinstance(t.close_time, datetime) else datetime.fromisoformat(str(t.close_time))
                b = (ct.hour // 3) * 3
                bucket_pnl[b].append(pnl)
            except Exception:
                pass

    wins = sum(1 for p in pnls if p >= 0)
    win_rate = (wins / len(pnls) * 100.0) if pnls else 0.0
    losses = [p for p in pnls if p < 0]
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0

    best_cat = max(by_cat.items(), key=lambda x: sum(x[1]) / len(x[1]) if x[1] else -999) if by_cat else None
    worst_cat = min(by_cat.items(), key=lambda x: sum(x[1]) / len(x[1]) if x[1] else 999) if by_cat else None
    best_token = max(by_token.items(), key=lambda x: sum(x[1]) / len(x[1]) if x[1] else -999) if by_token else None
    worst_emotion = min(by_emotion.items(), key=lambda x: sum(x[1]) / len(x[1]) if x[1] else 999) if by_emotion else None
    best_emotion = max(by_emotion.items(), key=lambda x: (sum(1 for p in x[1] if p >= 0) / len(x[1])) if x[1] else -1) if by_emotion else None
    dominant_emotion = max(by_emotion.items(), key=lambda x: len(x[1])) if by_emotion else None
    best_pattern = max(by_pattern.items(), key=lambda x: sum(x[1]) / len(x[1]) if x[1] else -999) if by_pattern else None
    worst_pattern = min(by_emotion_cat.items(), key=lambda x: sum(x[1]) / len(x[1]) if x[1] else 999) if by_emotion_cat else None
    best_bucket = max(bucket_pnl.items(), key=lambda x: sum(x[1]) / len(x[1]) if x[1] else -999) if bucket_pnl else None
    worst_bucket = min(bucket_pnl.items(), key=lambda x: sum(x[1]) / len(x[1]) if x[1] else 999) if bucket_pnl else None

    def _avg_line(item: tuple[str, list[float]] | None) -> str:
        if not item:
            return "—"
        k, vals = item
        avg = (sum(vals) / len(vals)) if vals else 0.0
        return f"{k} ({avg:+.1f}%)"

    def _emotion_wr(item: tuple[str, list[float]] | None) -> str:
        if not item:
            return "—"
        k, vals = item
        wr = (sum(1 for p in vals if p >= 0) / len(vals) * 100.0) if vals else 0.0
        return f"{k} ({wr:.0f}%)"

    biggest_risk = _avg_line(worst_emotion if worst_emotion else worst_cat)
    best_edge = _avg_line(best_cat)

    best_time = "—"
    worst_time = "—"
    if best_bucket:
        best_time = f"{_format_time_slot_local(best_bucket[0], 3, tz_offset)} ({(sum(best_bucket[1]) / len(best_bucket[1])):+.1f}%)"
    if worst_bucket:
        worst_time = f"{_format_time_slot_local(worst_bucket[0], 3, tz_offset)} ({(sum(worst_bucket[1]) / len(worst_bucket[1])):+.1f}%)"

    token_edge = "—"
    if best_token:
        k, vals = best_token
        token_edge = f"{k} ({(sum(vals) / len(vals)):+.1f}%)"

    best_pattern_line = "—"
    if best_pattern:
        (cat, dur), vals = best_pattern
        best_pattern_line = f"{cat} + {dur} ({(sum(vals) / len(vals)):+.1f}%)"
    worst_pattern_line = "—"
    if worst_pattern:
        (emo, cat), vals = worst_pattern
        worst_pattern_line = f"{emo} + {cat} ({(sum(vals) / len(vals)):+.1f}%)"

    # Risk alert: max 2 concise lines.
    risk_lines = []
    if recent_n >= 3:
        risk_lines.append(f"{recent_n} trades in ~20 min: pace is elevated.")
    if worst_emotion:
        emo, vals = worst_emotion
        risk_lines.append(f"Losses cluster when opening during {emo.lower()} ({(sum(vals)/len(vals)):+.1f}%).")
    if not risk_lines:
        risk_lines = ["No burst-risk signal right now."]
    risk_text = "\n".join(risk_lines[:2])

    total_entry = sum(_trade_entry_total(t) for t in trades)
    total_exit = sum(exit_totals.get(t.trade_id, 0.0) or 0.0 for t in trades)
    total_pnl = _trade_pnl_from_totals(total_entry, total_exit)
    ai_summary = await _build_ai_summary_unified(trades, exit_totals)

    blocks = [
        "🧠 Premium Insight",
        "",
        "📌 Summary",
        f"Win Rate: {win_rate:.0f}%",
        f"Best Edge: {best_edge}",
        f"Biggest Risk: {biggest_risk}",
        "",
        "📊 Performance",
        f"PnL: {total_pnl:+.1f}%",
        f"Avg Loss: {avg_loss:+.1f}%",
        f"Best Category: {_avg_line(best_cat)}",
        f"Worst Category: {_avg_line(worst_cat)}",
        "",
        "⏰ Time Edge",
        f"Best: {best_time}",
        f"Worst: {worst_time}",
        "",
        "🎯 Token Edge",
        f"Top Token: {token_edge}",
        f"Weak Sector: {_avg_line(worst_cat)}",
        "",
        "🧩 Behavior",
        f"Dominant: {dominant_emotion[0] if dominant_emotion else '—'}",
        f"Best Emotion: {_emotion_wr(best_emotion)}",
        f"Worst Emotion: {_emotion_wr(worst_emotion)}",
        "",
        "🔍 Pattern",
        f"Best: {best_pattern_line}",
        f"Worst: {worst_pattern_line}",
        "",
        "🚨 Risk",
        risk_text,
        "",
        "━━━━━━━━━━",
        "",
        "🧠 AI Insight",
        "",
        ai_summary or "No actionable AI insight yet.",
        "",
        "━━━━━━━━━━",
        "",
        f"Sample: {len(trades)}",
    ]
    out = "\n".join(blocks)
    if len(out) > 4090:
        out = out[:4087] + "…"
    return out


async def _build_premium_status(user_id: int) -> str:
    """Premium Status details: Badge, Subscription, Referral Bonus, Total Remaining."""
    from datetime import datetime
    status = await get_user_premium_status(user_id)
    lines = ["👑 Your Premium Status", ""]
    plan_type = (status.get("plan_type") or "").strip()
    plan_label = plan_type or "—"
    if plan_label and plan_label != "—":
        plan_label = plan_label.capitalize()
    referral_remaining = status.get("referral_days_remaining", 0) or 0
    earned = status.get("referral_days_earned", 0)
    badge = _premium_badge(plan_type, referral_remaining > 0)
    lines.append(f"Badge: {badge}")
    lines.append("")
    lines.append("Subscription:")
    purchased_active = status.get("purchased_active", False)
    premium_expires_at = status.get("premium_expires_at")
    paid_remaining = 0
    if premium_expires_at:
        try:
            expiry = datetime.fromisoformat(premium_expires_at.replace("Z", ""))
            paid_remaining = max(0, (expiry - datetime.utcnow()).days)
        except Exception:
            pass
    if purchased_active and (plan_label != "—" or paid_remaining > 0):
        lines.append(f"• Plan: {plan_label}")
        lines.append(f"• Expiry: {premium_expires_at[:10] if premium_expires_at else '—'}")
    else:
        lines.append("• No paid plan")
    lines.append("")
    lines.append("Referral Bonus:")
    lines.append(f"• Earned Days: {earned}")
    lines.append("")
    total_remaining = paid_remaining + referral_remaining
    lines.append("Total Premium Remaining:")
    lines.append(f"• {total_remaining} days")
    lines.append("")
    lines.append(PREMIUM_ACTIVE_SEP)
    if status.get("is_premium"):
        lines.append("")
        lines.append("Premium features active.")
    else:
        lines.append("")
        lines.append("Use /premium to upgrade.")
    return "\n".join(lines)


@router.callback_query(F.data == "premium_risk_alerts")
async def premium_risk_alerts_cb(callback: CallbackQuery) -> None:
    """Legacy callback: premium users get unified insight."""
    if await _gate(callback):
        await _answer_unified_insight(callback)
        return
    await callback.answer()
    text = (
        "🚨 Risk Alert System\n\n"
        "Alerts are sent automatically when we detect:\n"
        "• Rapid trading (e.g. 3+ trades in 20 minutes)\n"
        "• Loss streaks\n"
        "• Revenge trading patterns\n\n"
        "No action needed — we notify you to help you pause before bad trades."
    )
    await callback.message.edit_text(text, reply_markup=kb_back_to_premium_hub())


@router.callback_query(F.data == "premium_status")
async def premium_status_cb(callback: CallbackQuery) -> None:
    if await _gate(callback):
        await _answer_unified_insight(callback)
        return
    await callback.answer()
    text = await _build_premium_status(callback.from_user.id)
    await callback.message.edit_text(text, reply_markup=kb_back_to_premium_hub())


# ---- Admin: enable_premium / disable_premium (testing without payment) ----

@router.message(Command("enable_premium"))
async def cmd_enable_premium(message: Message) -> None:
    """Admin only: /enable_premium <user_id> — grant premium (Monthly) for testing."""
    from config import ADMIN_IDS
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Access denied.")
        return
    parts = (message.text or "").strip().split()
    if len(parts) < 2:
        await message.answer("Usage: /enable_premium <user_id>")
        return
    try:
        user_id = int(parts[1])
    except ValueError:
        await message.answer("Invalid user_id. Use a numeric ID.")
        return
    await set_user_premium(user_id, True, plan="Monthly", plan_type="monthly")
    await message.answer(f"✅ Premium enabled for user {user_id} (Monthly).")


@router.message(Command("disable_premium"))
async def cmd_disable_premium(message: Message) -> None:
    """Admin only: /disable_premium <user_id> — revoke premium for testing."""
    from config import ADMIN_IDS
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Access denied.")
        return
    parts = (message.text or "").strip().split()
    if len(parts) < 2:
        await message.answer("Usage: /disable_premium <user_id>")
        return
    try:
        user_id = int(parts[1])
    except ValueError:
        await message.answer("Invalid user_id. Use a numeric ID.")
        return
    await set_user_premium(user_id, False)
    await message.answer(f"✅ Premium disabled for user {user_id}.")


# ---- Admin: Unlock / Lock Premium (callback from panel) ----

@router.callback_query(F.data == "admin_cancel_premium_input")
async def admin_cancel_premium_input_cb(callback: CallbackQuery, state: FSMContext) -> None:
    from config import ADMIN_IDS

    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer()
        return
    await state.clear()
    await callback.answer()
    st = await get_user_premium_status_fresh(callback.from_user.id)
    await callback.message.edit_text(ADMIN_PANEL_TEXT, reply_markup=kb_admin_panel(bool(st.get("is_premium"))))


@router.callback_query(F.data == "admin_premium_unlock")
async def admin_premium_unlock_cb(callback: CallbackQuery, state: FSMContext) -> None:
    from config import ADMIN_IDS
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer()
        return
    await callback.answer()
    await state.set_state(AdminPremiumStates.waiting_user_id)
    await state.update_data(admin_premium_action="unlock")
    await callback.message.edit_text(
        "👤 Grant Premium\n\nSend the numeric user ID:",
        reply_markup=kb_admin_premium_input_nav(),
    )


@router.callback_query(F.data == "admin_premium_lock")
async def admin_premium_lock_cb(callback: CallbackQuery, state: FSMContext) -> None:
    from config import ADMIN_IDS
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer()
        return
    await callback.answer()
    await state.set_state(AdminPremiumStates.waiting_user_id)
    await state.update_data(admin_premium_action="lock")
    await callback.message.edit_text(
        "🔒 Revoke Premium\n\nSend the numeric user ID:",
        reply_markup=kb_admin_premium_input_nav(),
    )


@router.callback_query(F.data == "admin_premium_toggle_self")
async def admin_premium_toggle_self_cb(callback: CallbackQuery) -> None:
    from config import ADMIN_IDS
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer()
        return
    await callback.answer()
    uid = callback.from_user.id
    from bot.database.db import get_user_premium_status_fresh
    st = await get_user_premium_status_fresh(uid)
    turn_on = not st.get("is_premium")
    if turn_on:
        await set_user_premium(uid, True, plan="Monthly", next_billing=None, plan_type="monthly")
        msg = "✅ Your premium is now Active."
    else:
        await set_user_premium(uid, False)
        msg = "✅ Your premium is now Inactive."
    st2 = await get_user_premium_status_fresh(uid)
    await callback.message.edit_text(msg, reply_markup=kb_admin_panel(bool(st2.get("is_premium"))))


def _format_referral_tree(nodes: list, prefix: str = "") -> list[str]:
    """Format referral tree nodes as User A, ├── User B, etc."""
    lines = []
    for i, (uid, children) in enumerate(nodes):
        is_last = i == len(nodes) - 1
        branch = "└── " if is_last else "├── "
        lines.append(prefix + branch + f"User {uid}")
        if children:
            ext = "    " if is_last else "│   "
            lines.extend(_format_referral_tree(children, prefix + ext))
    return lines


@router.callback_query(F.data == "admin_referral_network")
async def admin_referral_network_cb(callback: CallbackQuery) -> None:
    from config import ADMIN_IDS
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from collections import defaultdict
    from bot.database.db import get_db
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer()
        return
    await callback.answer()
    # Lightweight adjacency-list rendering using invited_by (parent_id). No heavy recursion.
    db = await get_db()
    cursor = await db.execute("SELECT user_id, invited_by FROM user_settings WHERE invited_by IS NOT NULL")
    rows = await cursor.fetchall()
    if not rows:
        text = "🌐 Referral Network\n\nNo referral data yet."
    else:
        parent_to_children: dict[int, list[int]] = defaultdict(list)
        all_children: set[int] = set()
        for uid, parent in rows:
            try:
                parent = int(parent)
                uid = int(uid)
            except Exception:
                continue
            parent_to_children[parent].append(uid)
            all_children.add(uid)
        roots = [p for p in parent_to_children.keys() if p not in all_children]
        if not roots:
            roots = list(parent_to_children.keys())

        def render_tree(root: int) -> list[str]:
            out = [f"User {root}"]
            # Stack for DFS: (parent, child_index, prefix)
            stack: list[tuple[int, int, str]] = [(root, 0, "")]
            while stack:
                node, idx, prefix = stack.pop()
                children = parent_to_children.get(node, [])
                if idx >= len(children):
                    continue
                # Put parent back with next index
                stack.append((node, idx + 1, prefix))
                child = children[idx]
                is_last = (idx == len(children) - 1)
                branch = "└── " if is_last else "├── "
                out.append(prefix + branch + f"User {child}")
                ext = "    " if is_last else "│   "
                # Push child start
                stack.append((child, 0, prefix + ext))
            return out

        lines = ["🌐 Referral Network", ""]
        for r in roots:
            lines.extend(render_tree(int(r)))
        text = "\n".join(lines)
    from bot.keyboards.inline import BACK_TO_MENU_DATA
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    nav = InlineKeyboardBuilder()
    nav.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    await callback.message.edit_text(text, reply_markup=nav.as_markup())


@router.message(AdminPremiumStates.waiting_user_id, F.text)
async def admin_premium_receive_user_id(message: Message, state: FSMContext) -> None:
    from config import ADMIN_IDS
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return
    try:
        target_uid = int(message.text.strip())
    except ValueError:
        await message.answer("Invalid. Send a numeric user ID.", reply_markup=kb_admin_premium_input_nav())
        return
    data = await state.get_data()
    action = data.get("admin_premium_action", "unlock")
    await state.clear()
    is_premium = action == "unlock"
    await set_user_premium(target_uid, is_premium, plan="Monthly" if is_premium else None, next_billing=None, plan_type="monthly" if is_premium else None)
    action_done = "Granted premium to" if is_premium else "Revoked premium from"
    st = await get_user_premium_status_fresh(message.from_user.id)
    await message.answer(f"✅ {action_done} user {target_uid}.", reply_markup=kb_admin_panel(bool(st.get("is_premium"))))


# ---- Risk Alert (automatic; called from elsewhere) ----

async def maybe_send_risk_alerts(bot, user_id: int) -> None:
    """Send risk alert to premium user if conditions met (e.g. 3+ trades in 20 min). No-op for non-premium."""
    status = await get_user_premium_status(user_id)
    if not status.get("is_premium"):
        return
    count = await get_recent_trades_count(user_id, 20)
    if count >= 3:
        try:
            await bot.send_message(
                user_id,
                "⚠ Risk Alert\n\n"
                "You have made 3 trades in the last 20 minutes.\n\n"
                "Rapid trading is associated with lower performance.\n\n"
                "Suggestion:\nTake a short break before opening another trade.",
            )
        except Exception:
            pass
