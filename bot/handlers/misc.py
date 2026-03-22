from datetime import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from bot.database.db import get_trade_by_id, set_trade_invalid, get_open_trades, get_trade_timeline, get_exit_totals_for_trades, get_trade_exits
from bot.keyboards import kb_back_to_menu, kb_after_close, kb_open_trades_list, kb_position_detail, kb_position_detail_auto
from bot.states import MarkInvalidStates

router = Router()


def _fmt_usd_compact(value) -> str:
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"${v:,.0f}" if v >= 100 else f"${v:.2f}"


@router.callback_query(F.data == "view_past_trades")
async def view_past_trades(callback: CallbackQuery) -> None:
    from bot.database.db import get_valid_trades_for_stats, get_user_timezone_offset
    from bot.handlers.stats import _build_stats
    await callback.answer()
    user_id = callback.from_user.id
    trades = await get_valid_trades_for_stats(user_id)
    trade_ids = [t.trade_id for t in trades if t.trade_id]
    exit_totals = await get_exit_totals_for_trades(trade_ids) if trade_ids else {}
    tz_offset = await get_user_timezone_offset(user_id)
    text, _, _ = _build_stats(user_id, trades, exit_totals, page=0, tz_offset=tz_offset)
    await callback.message.edit_text(text, reply_markup=kb_back_to_menu())


@router.callback_query(F.data.startswith("position_detail:"))
async def position_detail(callback: CallbackQuery) -> None:
    from bot.database.db import get_trade_timeline, get_token_metadata
    from bot.services import fetch_token_data
    from bot.utils.formatters import get_network_icon, format_duration_seconds, format_user_time, format_pnl, format_token_amount

    await callback.answer()
    try:
        trade_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return
    trade = await get_trade_by_id(trade_id, callback.from_user.id)
    if not trade or trade.close_time is not None:
        await callback.message.edit_text("Position not found.", reply_markup=kb_back_to_menu())
        return
    user_id = callback.from_user.id
    meta = await get_token_metadata(trade.token_address) if trade.token_address else None
    sym = (meta["symbol"] if meta else None) or trade.token_symbol or "?"
    name = (meta["name"] if meta else None) or getattr(trade, "token_name", None)
    from bot.utils.formatters import format_token_display
    token_display = format_token_display(sym, name)
    chain_label = get_network_icon(trade.network or "")
    entry_usd = trade.open_value_usd or ((trade.open_quantity or 0) * (trade.open_price or 0))
    qty = trade.remaining_quantity if trade.remaining_quantity is not None else trade.open_quantity or 0
    base_price = trade.open_price or 0.0
    current_price = base_price
    live_price = False
    td = await fetch_token_data(trade.token_address) if trade.token_address else None
    if td and getattr(td, "price", None):
        current_price = td.price
        live_price = True
    current_value = qty * current_price if qty and current_price else entry_usd or 0
    pnl_str = "—"
    if entry_usd and entry_usd > 0:
        pnl_pct = ((current_value - entry_usd) / entry_usd) * 100
        pnl_str = format_pnl(pnl_pct)
    ot = trade.open_time if isinstance(trade.open_time, datetime) else datetime.fromisoformat(str(trade.open_time))
    duration_sec = (datetime.utcnow() - ot).total_seconds()
    open_time_str = await format_user_time(user_id, ot.isoformat() if hasattr(ot, "isoformat") else str(ot))

    timeline = await get_trade_timeline(trade_id)
    timeline_lines = []
    for ev in timeline:
        etype = ev.get("event_type") or ""
        val = ev.get("value_usd")
        amt = ev.get("amount")
        if etype == "OPEN":
            if val is not None:
                timeline_lines.append(f"Buy — ${val:.2f}")
            elif amt is not None:
                timeline_lines.append(f"Buy — {format_token_amount(amt)}")
        elif etype == "DCA":
            if val is not None:
                timeline_lines.append(f"DCA — ${val:.2f}")
            elif amt is not None:
                timeline_lines.append(f"DCA — {format_token_amount(amt)}")
        elif etype == "PARTIAL_EXIT":
            if val is not None:
                timeline_lines.append(f"Partial Sell — ${val:.2f}")
            elif amt is not None:
                timeline_lines.append(f"Partial Sell — {format_token_amount(amt)}")
        elif etype == "FULL_CLOSE":
            if val is not None:
                timeline_lines.append(f"Close — ${val:.2f}")
            elif amt is not None:
                timeline_lines.append(f"Close — {format_token_amount(amt)}")

    blocks = [
        f"🪙 {token_display}",
        f"🌐 Chain: {chain_label}",
        "",
        f"Value: {_fmt_usd_compact(entry_usd)}",
        f"Position size: {format_token_amount(qty) if qty is not None else '—'}",
        f"Open time: {open_time_str}",
        f"Duration: {format_duration_seconds(duration_sec)}",
    ]
    if live_price and qty is not None and current_price is not None:
        now_line = f"Now: {_fmt_usd_compact(current_value)}"
        if entry_usd and entry_usd > 0:
            now_line += f" ({pnl_str})"
        blocks.insert(4, now_line)
    price_display = f"${current_price:.6f}" if current_price and current_price < 1 else f"${current_price:.2f}"
    blocks.append(f"Price: {price_display}" if live_price else f"Price: ~ {price_display}")
    if timeline_lines:
        blocks.append("")
        blocks.append("📜 TRADE TIMELINE")
        blocks.extend(timeline_lines)
    blocks.append("")
    blocks.append("Choose an action:")
    text = "\n".join(blocks)
    if trade.trade_mode == "auto":
        await callback.message.edit_text(text, reply_markup=kb_position_detail_auto(trade_id))
    else:
        await callback.message.edit_text(text, reply_markup=kb_position_detail(trade_id))


@router.callback_query(F.data == "positions_list")
async def positions_list(callback: CallbackQuery) -> None:
    from bot.database.db import get_token_metadata
    from bot.services import fetch_token_data
    from bot.utils.formatters import format_pnl, format_token_display

    await callback.answer()
    open_trades = await get_open_trades(callback.from_user.id)
    if not open_trades:
        await callback.message.edit_text("You have no open positions.", reply_markup=kb_back_to_menu())
        return
    lines = ["📊 OPEN POSITIONS", ""]
    for t in open_trades:
        meta = await get_token_metadata(t.token_address) if t.token_address else None
        sym = (meta["symbol"] if meta else None) or t.token_symbol or "?"
        name = (meta["name"] if meta else None) or getattr(t, "token_name", None)
        token_display = format_token_display(sym, name)
        entry_usd = t.open_value_usd or ((t.open_quantity or 0) * (t.open_price or 0))
        qty = t.remaining_quantity if t.remaining_quantity is not None else t.open_quantity or 0
        base_price = t.open_price or 0.0
        current_price = base_price
        live_price = False
        td = await fetch_token_data(t.token_address) if t.token_address else None
        if td and getattr(td, "price", None):
            current_price = td.price
            live_price = True
        current_value = qty * current_price if qty and current_price else entry_usd or 0
        pnl_str = "—"
        if live_price and entry_usd and entry_usd > 0:
            pnl_pct = ((current_value - entry_usd) / entry_usd) * 100
            pnl_str = format_pnl(pnl_pct)
        lines.append(token_display)
        lines.append(f"Value: {_fmt_usd_compact(entry_usd)}")
        if live_price and qty is not None and current_price is not None:
            now_line = f"Now: {_fmt_usd_compact(current_value)}"
            if entry_usd and entry_usd > 0:
                now_line += f" ({pnl_str})"
            lines.append(now_line)
        lines.append("")
    lines.append("Tap a position:")
    pairs = [(t.trade_id, t.token_symbol) for t in open_trades]
    await callback.message.edit_text("\n".join(lines), reply_markup=kb_open_trades_list(pairs))


def _trade_entry_total(trade) -> float:
    """Entry total USD for PnL."""
    v = getattr(trade, "open_value_usd", None)
    if v is not None and v > 0:
        return float(v)
    q = getattr(trade, "open_quantity", None) or 0
    p = getattr(trade, "open_price", None) or 0
    return float(q * p) if q and p else 0.0


async def _format_trade_report(
    user_id: int,
    trade,
    timeline_events: list = None,
    exit_total: float = 0.0,
    resolved_symbol: str = None,
    resolved_name: str = None,
) -> str:
    """Structured trade report for My Stats / View Report. PnL uses entry_total and exit_total (from trade_exits).
    Timestamps shown in user timezone via format_user_time."""
    from bot.utils.formatters import (
        get_network_icon,
        format_duration_seconds,
        format_user_time,
        format_token_display,
        format_price,
        format_pnl,
        format_compact_number,
    )

    sym = (resolved_symbol or trade.token_symbol or "?").strip()
    name = resolved_name or getattr(trade, "token_name", None)
    token_display = format_token_display(sym, name)
    chain_label = get_network_icon(trade.network or "")
    contract = (trade.token_address or "—")
    price_open = format_price(trade.open_price) if trade.open_price is not None else "—"
    price_close = format_price(trade.close_price) if trade.close_price is not None else "—"
    entry_total = _trade_entry_total(trade)
    if entry_total and entry_total > 0 and exit_total is not None:
        pnl = ((exit_total - entry_total) / entry_total) * 100.0
    else:
        pnl = 0.0
    pnl_emoji = "📈" if pnl >= 0 else "📉"
    pnl_str = format_pnl(pnl)
    duration_sec = trade.duration or 0
    duration_str = format_duration_seconds(duration_sec)
    emotion_open = (trade.emotion_open or "").strip()
    if emotion_open and trade.emotion_open_note:
        emotion_open = f"{emotion_open} ({trade.emotion_open_note})"
    emotion_close = (trade.emotion_close or "").strip()
    if emotion_close and trade.emotion_close_note:
        emotion_close = f"{emotion_close} ({trade.emotion_close_note})"

    open_ts_raw = trade.open_time.isoformat() if hasattr(trade.open_time, "isoformat") else str(trade.open_time or "")
    open_ts = await format_user_time(user_id, open_ts_raw) if open_ts_raw else "—"
    close_ts = "—"
    if getattr(trade, "close_time", None):
        ct_raw = trade.close_time.isoformat() if hasattr(trade.close_time, "isoformat") else str(trade.close_time or "")
        close_ts = await format_user_time(user_id, ct_raw) if ct_raw else "—"

    lines = [
        f"🪙 {token_display}",
        f"🌐 Chain: {chain_label}",
        "",
        f"📄 Contract\n<code>{contract}</code>\n(Tap for copy address)",
        "",
        f"📅 Date\nOpen: {open_ts}\nClose: {close_ts}",
    ]
    behavioral_lines = []
    cat = (trade.token_category or "").strip()
    if cat:
        cat_line = f"🏷 Category: {cat}"
        if trade.token_category_note:
            cat_line += f" ({trade.token_category_note})"
        behavioral_lines.append(cat_line)
    reason = (trade.reason_open or "").strip()
    if reason:
        reason_line = f"🎯 Entry Reason: {reason}"
        if trade.reason_open_note:
            reason_line += f" ({trade.reason_open_note})"
        behavioral_lines.append(reason_line)
    if emotion_open:
        behavioral_lines.append(f"😈 Emotion Open: {emotion_open}")
    if emotion_close:
        behavioral_lines.append(f"😱 Emotion Close: {emotion_close}")
    if (trade.risk_level or "").strip():
        behavioral_lines.append(f"⚖ Risk Level: {trade.risk_level}")
    if behavioral_lines:
        lines.extend(["", "🧠 Behavioral Breakdown", ""])
        lines.extend(behavioral_lines)
    market_lines = []
    if trade.mcap_open is not None:
        market_lines.append(f"🏦 Market Cap Open: ${format_compact_number(trade.mcap_open)}")
    if trade.mcap_close is not None:
        market_lines.append(f"🏦 Market Cap Close: ${format_compact_number(trade.mcap_close)}")
    if trade.open_price is not None:
        market_lines.append(f"💲 Price Open: ~ {price_open}")
    if trade.close_price is not None:
        market_lines.append(f"💲 Price Close: ~ {price_close}")
    if market_lines:
        lines.extend(["", "📊 Market Data", ""])
        lines.extend(market_lines)
    lines.extend(["", f"{pnl_emoji} PnL", pnl_str, "", f"⏱ Duration\n{duration_str}"])
    base = "\n".join(lines)
    if timeline_events:
        timeline_lines = []
        for ev in timeline_events:
            etype = ev.get("event_type") or ""
            val = ev.get("value_usd")
            amt = ev.get("amount")
            if etype == "OPEN":
                if val is not None:
                    timeline_lines.append(f"Buy — ${val:.2f}")
                elif amt is not None:
                    timeline_lines.append(f"Buy — {amt:.4g}")
            elif etype == "DCA":
                if val is not None:
                    timeline_lines.append(f"DCA — ${val:.2f}")
                elif amt is not None:
                    timeline_lines.append(f"DCA — {amt:.4g}")
            elif etype == "PARTIAL_EXIT":
                if val is not None:
                    timeline_lines.append(f"Partial Sell — ${val:.2f}")
                elif amt is not None:
                    timeline_lines.append(f"Partial Sell — {amt:.4g}")
            elif etype == "FULL_CLOSE":
                if val is not None:
                    timeline_lines.append(f"Close — ${val:.2f}")
                elif amt is not None:
                    timeline_lines.append(f"Close — {amt:.4g}")
        if timeline_lines:
            base += "\n\n📜 TRADE TIMELINE\n" + "\n".join(timeline_lines)
    return base


@router.callback_query(F.data.startswith("copy_contract:"))
async def copy_contract_cb(callback: CallbackQuery) -> None:
    """Send contract address so user can copy; show confirmation."""
    try:
        trade_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return
    trade = await get_trade_by_id(trade_id, callback.from_user.id)
    if not trade or not trade.token_address:
        return
    await callback.answer("Contract address copied.")
    await callback.message.answer(
        f"📄 Contract\n<code>{trade.token_address}</code>\n(Tap for copy address)",
    )


@router.callback_query(F.data.startswith("view_report:"))
async def view_report(callback: CallbackQuery) -> None:
    from bot.database.db import get_token_metadata, get_trade_note
    await callback.answer()
    try:
        trade_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return
    trade = await get_trade_by_id(trade_id, callback.from_user.id)
    if not trade:
        await callback.message.answer("Trade not found.")
        return
    user_id = callback.from_user.id
    meta = await get_token_metadata(trade.token_address) if trade.token_address else None
    resolved_symbol = (meta["symbol"] if meta else None) or trade.token_symbol
    resolved_name = (meta["name"] if meta else None) or getattr(trade, "token_name", None)
    timeline = await get_trade_timeline(trade_id)
    exits = await get_trade_exits(trade_id)
    exit_total = sum((ex.value_usd or (ex.amount * ex.price) or 0) for ex in exits) if exits else 0.0
    text = await _format_trade_report(
        user_id,
        trade,
        timeline_events=timeline if timeline else None,
        exit_total=exit_total,
        resolved_symbol=resolved_symbol,
        resolved_name=resolved_name,
    )
    note = await get_trade_note(trade_id, user_id)
    note_text = (note.get("note_text") or "").strip() if note else ""
    if note_text:
        text += f"\n\n📝 Note\n\"{note_text}\""
    await callback.message.edit_text(text, reply_markup=kb_after_close(trade_id))


@router.callback_query(F.data.startswith("mark_invalid:"))
async def mark_invalid_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    try:
        trade_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return
    await state.update_data(invalid_trade_id=trade_id)
    await state.set_state(MarkInvalidStates.confirm)
    from bot.keyboards import kb_mark_invalid_confirm
    await callback.message.edit_text(
        "Mark this trade as invalid?\nIt will be excluded from statistics but still saved.",
        reply_markup=kb_mark_invalid_confirm(),
    )


@router.callback_query(F.data.startswith("invalid_confirm:"), MarkInvalidStates.confirm)
async def mark_invalid_confirm_cb(callback: CallbackQuery, state: FSMContext) -> None:
    from bot.handlers.start import WELCOME
    from bot.keyboards import kb_mark_invalid_reason, kb_empty
    await callback.answer()
    if callback.data.endswith(":no"):
        await state.clear()
        await callback.message.edit_text(WELCOME, reply_markup=kb_empty())
        return
    await state.set_state(MarkInvalidStates.reason)
    await callback.message.edit_text("Reason:", reply_markup=kb_mark_invalid_reason())


@router.callback_query(F.data.startswith("invalid_reason:"), MarkInvalidStates.reason)
async def mark_invalid_reason_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    value = callback.data.replace("invalid_reason:", "")
    if value == "Other":
        await state.set_state(MarkInvalidStates.reason_note)
        await callback.message.edit_text("Please specify reason:")
        return
    data = await state.get_data()
    trade_id = data.get("invalid_trade_id")
    if trade_id:
        await set_trade_invalid(trade_id, value)
    await state.clear()
    await callback.message.edit_text(
        "Trade marked as invalid and excluded from statistics.",
        reply_markup=kb_back_to_menu(),
    )


@router.message(MarkInvalidStates.reason_note, F.text)
async def mark_invalid_reason_note(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    trade_id = data.get("invalid_trade_id")
    if trade_id:
        await set_trade_invalid(trade_id, message.text or "Other")
    await state.clear()
    await message.answer(
        "Trade marked as invalid and excluded from statistics.",
        reply_markup=kb_back_to_menu(),
    )
