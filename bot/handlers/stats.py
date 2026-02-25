from collections import defaultdict
from datetime import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.database.db import get_valid_trades_for_stats, get_closed_trades_by_token
from bot.keyboards import kb_back_to_menu, kb_stats_tokens
from bot.handlers.ui_flow import show_internal_screen

router = Router()


def _build_stats(user_id: int, trades: list) -> tuple[str, list[tuple[str, float]]]:
    """Returns (text, token_pnls) where token_pnls is [(symbol, pnl_percent), ...]."""
    if not trades:
        return (
            "📊 My Stats\n\n"
            "No closed trades yet. Open and close positions to see your behavior statistics.",
            [],
        )
    total = len(trades)
    wins = sum(
        1
        for t in trades
        if t.close_price and t.open_price and t.close_price >= t.open_price
    )
    losses = total - wins
    emotions = defaultdict(list)
    categories = defaultdict(list)
    hours_utc = defaultdict(list)
    token_pnls = defaultdict(list)
    for t in trades:
        if t.emotion_open:
            pnl = (
                ((t.close_price - t.open_price) / t.open_price) * 100
                if t.open_price
                else 0
            )
            emotions[t.emotion_open].append(pnl)
        if t.token_category:
            pnl = (
                ((t.close_price - t.open_price) / t.open_price) * 100
                if t.open_price
                else 0
            )
            categories[t.token_category].append(pnl)
        if t.close_time:
            ct = (
                t.close_time
                if isinstance(t.close_time, datetime)
                else datetime.fromisoformat(str(t.close_time))
            )
            h = ct.hour
            pnl = (
                ((t.close_price - t.open_price) / t.open_price) * 100
                if t.open_price
                else 0
            )
            hours_utc[h].append(pnl)
        if t.token_symbol:
            pnl = (
                ((t.close_price - t.open_price) / t.open_price) * 100
                if t.open_price
                else 0
            )
            token_pnls[t.token_symbol].append(pnl)
    lines = [
        "📊 My Stats",
        "",
        f"Total Trades: {total}",
        f"Wins: {wins}",
        f"Losses: {losses}",
        "",
        "Emotion vs Result:",
    ]
    for emo, pnls in sorted(emotions.items(), key=lambda x: -len(x[1])):
        avg = sum(pnls) / len(pnls) if pnls else 0
        note = " *Note: custom entry" if emo == "Other" else ""
        lines.append(f"{emo} → {len(pnls)} trades → {avg:+.0f}%{note}")
    lines.append("")
    bucket_pnl = defaultdict(list)
    for h, pnls in hours_utc.items():
        bucket = (h // 3) * 3
        bucket_pnl[bucket].extend(pnls)
    if bucket_pnl:
        lines.append("Best Time:")
        best_b = max(
            bucket_pnl.items(),
            key=lambda x: sum(x[1]) / len(x[1]) if x[1] else -999,
        )
        worst_b = min(
            bucket_pnl.items(),
            key=lambda x: sum(x[1]) / len(x[1]) if x[1] else 999,
        )
        best_avg = sum(best_b[1]) / len(best_b[1]) if best_b[1] else 0
        worst_avg = sum(worst_b[1]) / len(worst_b[1]) if worst_b[1] else 0
        lines.append(f"{best_b[0]:02d}:00–{best_b[0]+3:02d}:00 UTC → {best_avg:+.0f}%")
        lines.append("")
        lines.append("Worst Time:")
        lines.append(f"{worst_b[0]:02d}:00–{worst_b[0]+3:02d}:00 UTC → {worst_avg:+.0f}%")
        lines.append("")
    lines.append("Token Category:")
    for cat, pnls in sorted(categories.items(), key=lambda x: -len(x[1])):
        avg = sum(pnls) / len(pnls) if pnls else 0
        note = " *Note: custom" if cat == "Other" else ""
        lines.append(f"{cat} → {avg:+.0f}%{note}")
    token_list = []
    if token_pnls:
        lines.append("")
        lines.append("Token performance:")
        for sym, pnls in sorted(token_pnls.items(), key=lambda x: -sum(x[1]) / len(x[1]) if x[1] else 0):
            avg = sum(pnls) / len(pnls) if pnls else 0
            lines.append(f"{sym} → {avg:+.0f}%")
            token_list.append((sym, avg))
    return "\n".join(lines), token_list


@router.callback_query(F.data == "stats")
async def show_stats(callback: CallbackQuery) -> None:
    trades = await get_valid_trades_for_stats(callback.from_user.id)
    text, token_list = _build_stats(callback.from_user.id, trades)
    kb = kb_stats_tokens(token_list) if token_list else kb_back_to_menu()
    await show_internal_screen(callback, text, kb)


def _fmt_trade_behavior(t) -> str:
    """Full behavioral breakdown for one closed trade."""
    mcap_open = f"${t.mcap_open:,.0f}" if t.mcap_open else "N/A"
    mcap_close = f"${t.mcap_close:,.0f}" if t.mcap_close else "N/A"
    pnl = ((t.close_price - t.open_price) / t.open_price) * 100 if t.open_price else 0
    dur = int(t.duration) if t.duration else 0
    lines = [
        "🪙 Category: " + (t.token_category or "-") + (f" ({t.token_category_note})" if t.token_category_note else ""),
        "🎯 Risk Level: " + (t.risk_level or "-"),
        "📢 Entry Reason: " + (t.reason_open or "-") + (f" ({t.reason_open_note})" if t.reason_open_note else ""),
        "😈 Emotion Open: " + (t.emotion_open or "-") + (f" ({t.emotion_open_note})" if t.emotion_open_note else ""),
        "😓 Emotion Close: " + (t.emotion_close or "-") + (f" ({t.emotion_close_note})" if t.emotion_close_note else ""),
        "📋 Discipline: " + (t.discipline or "-"),
        "",
        "🏦 Marketcap open: " + mcap_open,
        "🏦 Marketcap close: " + mcap_close,
        "",
        "📊 Price open: $" + (f"{t.open_price:.6f}" if t.open_price else "N/A"),
        "📊 Price close: $" + (f"{t.close_price:.6f}" if t.close_price else "N/A"),
        f"📉 Result: {pnl:+.1f}%",
        f"⏱ Duration: {dur} min",
    ]
    return "\n".join(lines)


@router.callback_query(F.data.startswith("stat_token:"))
async def show_token_history(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        symbol = callback.data.replace("stat_token:", "", 1)
    except Exception:
        return
    if not symbol:
        return
    trades = await get_closed_trades_by_token(callback.from_user.id, symbol)
    if not trades:
        await callback.message.edit_text(f"No closed trades for {symbol}.", reply_markup=kb_back_to_menu())
        return
    lines = [f"🪙 {symbol} — behavioral breakdown", ""]
    for i, t in enumerate(trades, 1):
        if len(trades) > 1:
            lines.append(f"——— Trade #{i} ———")
            lines.append("")
        lines.append(_fmt_trade_behavior(t))
        if i < len(trades):
            lines.append("")
    text = "\n".join(lines)
    from bot.keyboards import kb_stats_back
    await callback.message.edit_text(text, reply_markup=kb_stats_back())
