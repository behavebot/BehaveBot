"""Pre-trade behavioral warnings (read-only stats). Not AI Insight; soft nudge only."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database.db import (
    get_valid_trades_for_stats,
    get_exit_totals_for_trades,
    get_recent_trades_count,
    get_user_premium_status_fresh,
)


def _trade_entry_total(t) -> float:
    v = getattr(t, "open_value_usd", None)
    if v is not None and v > 0:
        return float(v)
    q = getattr(t, "open_quantity", None) or 0
    p = getattr(t, "open_price", None) or 0
    return float(q * p) if q and p else 0.0


def _trade_pnl_from_totals(entry_total: float, exit_total: float) -> float:
    if not entry_total or entry_total <= 0:
        return 0.0
    return ((exit_total - entry_total) / entry_total) * 100.0


COOLDOWN = timedelta(minutes=5)
_last_warning_utc: dict[int, datetime] = {}


def _mark_shown(user_id: int) -> None:
    _last_warning_utc[user_id] = datetime.utcnow()


def _cooldown_active(user_id: int) -> bool:
    last = _last_warning_utc.get(user_id)
    if not last:
        return False
    return datetime.utcnow() - last < COOLDOWN


def _close_dt(t) -> datetime | None:
    if not getattr(t, "close_time", None):
        return None
    ct = t.close_time
    if isinstance(ct, datetime):
        return ct.replace(tzinfo=None) if ct.tzinfo else ct
    try:
        return datetime.fromisoformat(str(ct).replace("Z", ""))
    except Exception:
        return None


def _open_bucket_utc(ts: datetime) -> int:
    """3-hour UTC bucket start hour (0,3,...,21) matching premium insight."""
    t = ts.replace(tzinfo=None) if ts.tzinfo else ts
    return (t.hour // 3) * 3


async def build_ai_warning(
    user_id: int,
    token: str,
    timestamp: datetime,
    emotion: Optional[str] = None,
) -> Optional[str]:
    """
    Rule-based pre-trade warning from closed-trade history only (read-only).
    Returns None if no trigger. `token` reserved for future use.
    """
    del token  # API stability; no token-specific rules yet
    trades = await get_valid_trades_for_stats(user_id)
    if len(trades) < 5:
        return None

    trade_ids = [t.trade_id for t in trades if t.trade_id]
    exit_totals = await get_exit_totals_for_trades(trade_ids) if trade_ids else {}

    def pnl_for(t) -> float:
        entry = _trade_entry_total(t)
        ex = exit_totals.get(t.trade_id, 0.0) or 0.0
        return _trade_pnl_from_totals(entry, ex)

    # Priority 1 — burst (10-minute window, same as spec)
    n_recent = await get_recent_trades_count(user_id, 10)
    if n_recent >= 3:
        return (
            "🚨 Behavior Alert\n"
            "You are entering multiple trades in a short time.\n"
            "This pattern often leads to losses."
        )

    # Priority 2 — loss streak (last 3 closes, newest first)
    last3 = trades[:3]
    if len(last3) >= 2:
        losses = sum(1 for t in last3 if pnl_for(t) < 0)
        if losses >= 2:
            return (
                "⚠️ AI Warning\n"
                "Recent trades show a losing streak.\n"
                "Pause before entering another position."
            )

    # Priority 3 — worst emotion (only when emotion known; bucket needs ≥3 trades)
    emo_in = (emotion or "").strip()
    if emo_in:
        by_e: dict[str, list[float]] = defaultdict(list)
        for t in trades:
            e = (t.emotion_open or "").strip()
            if e:
                by_e[e].append(pnl_for(t))
        eligible_e = {k: v for k, v in by_e.items() if len(v) >= 3}
        if eligible_e:
            worst_key, wvals = min(
                eligible_e.items(), key=lambda kv: sum(kv[1]) / len(kv[1])
            )
            if worst_key.lower() == emo_in.lower():
                avg = sum(wvals) / len(wvals)
                return (
                    "⚠️ AI Warning\n"
                    "This emotional state leads to losses.\n"
                    f"Average result: {avg:+.1f}%"
                )

    # Priority 4 — worst time window (bucket ≥3 trades)
    cur_b = _open_bucket_utc(timestamp)
    bucket_pnl: dict[int, list[float]] = defaultdict(list)
    for t in trades:
        ct = _close_dt(t)
        if not ct:
            continue
        hb = (ct.hour // 3) * 3
        bucket_pnl[hb].append(pnl_for(t))

    eligible_b = {k: v for k, v in bucket_pnl.items() if len(v) >= 3}
    if eligible_b:
        wb, wvals = min(eligible_b.items(), key=lambda kv: sum(kv[1]) / len(kv[1]))
        if cur_b == wb:
            avg = sum(wvals) / len(wvals)
            return (
                "⚠️ AI Warning\n"
                "You are trading during your worst time window.\n"
                f"Average result: {avg:+.1f}%"
            )

    return None


FREEMIUM_TEASER_TEXT = (
    "⚠️ This is not random.\n\n"
    "You're repeating the same mistake — and it's already affecting your trades.\n\n"
    "The system can see it clearly.\n"
    "You just don't.\n\n"
    "Unlock the full insight before it costs you more.\n\n"
    "👉 Upgrade to Premium"
)


def _freemium_unlock_markup() -> InlineKeyboardMarkup:
    """Single CTA; uses existing premium_landing handler (same funnel as 💎 Premium)."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔓 Unlock Premium", callback_data="premium_landing"))
    return b.as_markup()


async def try_send_pretrade_warning(
    chat_target: CallbackQuery | Message,
    user_id: int,
    token: str,
    timestamp: datetime,
    emotion: Optional[str] = None,
) -> None:
    """Send at most one warning per cooldown; never raises; does not block flow.

    Freemium: full rule evaluation still runs (build_ai_warning); non-premium users
    only see a teaser + unlock button when a real trigger would have fired.
    """
    if _cooldown_active(user_id):
        return
    full_text = await build_ai_warning(user_id, token, timestamp, emotion=emotion)
    if not full_text:
        return

    status = await get_user_premium_status_fresh(user_id)
    is_premium = bool(status.get("is_premium", False))
    if is_premium:
        display_text = full_text
        reply_markup = None
    else:
        display_text = FREEMIUM_TEASER_TEXT
        reply_markup = _freemium_unlock_markup()

    _mark_shown(user_id)
    msg = chat_target.message if isinstance(chat_target, CallbackQuery) else chat_target
    await msg.answer(display_text, reply_markup=reply_markup)
