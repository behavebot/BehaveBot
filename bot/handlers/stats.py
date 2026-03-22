from collections import defaultdict
from datetime import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery
from config import ADMIN_IDS

from bot.database.db import (
    get_valid_trades_for_stats,
    get_valid_trades_for_stats_by_network,
    get_closed_trades_by_token,
    get_closed_trades_by_token_network,
    get_exit_totals_for_trades,
)
from bot.keyboards import kb_back_to_menu, kb_stats_chain_only, kb_stats_chain_token_list
from bot.handlers.ui_flow import show_internal_screen

router = Router()


def _trade_entry_total(t) -> float:
    """Entry total USD for PnL: open_value_usd or open_quantity * open_price."""
    v = getattr(t, "open_value_usd", None)
    if v is not None and v > 0:
        return float(v)
    q = getattr(t, "open_quantity", None) or 0
    p = getattr(t, "open_price", None) or 0
    return float(q * p) if q and p else 0.0


def _trade_pnl_from_totals(entry_total: float, exit_total: float) -> float:
    """PnL % from entry/exit totals; safe for zero entry."""
    if not entry_total or entry_total <= 0:
        return 0.0
    return ((exit_total - entry_total) / entry_total) * 100.0


TOKEN_PER_PAGE = 5


def _format_time_slot_local(utc_start_hour: int, slot_hours: int, offset_hours: int) -> str:
    """Format UTC time slot for display in user's timezone. E.g. 0, 3, 7 -> '07:00–10:00 (UTC+7)'."""
    local_start = (utc_start_hour + offset_hours) % 24
    local_end = (utc_start_hour + slot_hours + offset_hours) % 24
    tz_label = f"UTC+{offset_hours}" if offset_hours >= 0 else f"UTC{offset_hours}"
    return f"{local_start:02d}:00–{local_end:02d}:00 ({tz_label})"


def _build_stats(
    user_id: int,
    trades: list,
    exit_totals: dict,
    page: int = 0,
    per_page: int = TOKEN_PER_PAGE,
    tz_offset: int = 0,
) -> tuple[str, list[tuple[str, float]], int]:
    """Returns (text, token_list_for_page, total_pages). token_list_for_page is the slice for current page."""
    if not trades:
        return (
            "📊 My Stats\n\n"
            "No closed trades yet. Open and close positions to see your behavior statistics.",
            [],
            0,
        )
    total = len(trades)
    # Date context from trades table timestamps
    first_dt = None
    last_dt = None
    for t in trades:
        raw = t.close_time or t.open_time
        if not raw:
            continue
        dt = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw))
        if first_dt is None or dt < first_dt:
            first_dt = dt
        if last_dt is None or dt > last_dt:
            last_dt = dt
    emotions = defaultdict(list)
    categories = defaultdict(list)
    hours_utc = defaultdict(list)
    token_pnls = defaultdict(list)
    wins = 0
    for t in trades:
        entry_total = _trade_entry_total(t)
        exit_total = exit_totals.get(t.trade_id, 0.0) or 0.0
        pnl = _trade_pnl_from_totals(entry_total, exit_total)
        if entry_total > 0 and exit_total >= entry_total:
            wins += 1
        elif entry_total > 0:
            pass  # loss
        if t.emotion_open:
            emotions[t.emotion_open].append(pnl)
        if t.token_category:
            categories[t.token_category].append(pnl)
        if t.close_time:
            ct = (
                t.close_time
                if isinstance(t.close_time, datetime)
                else datetime.fromisoformat(str(t.close_time))
            )
            h = ct.hour
            hours_utc[h].append(pnl)
        if t.token_symbol:
            token_pnls[t.token_symbol].append(pnl)
    losses = total - wins
    lines = [
        "📊 My Stats",
        "",
    ]
    if first_dt and last_dt:
        lines.extend([
            f"📅 Data Range: {first_dt.strftime('%d %b %Y')} — {last_dt.strftime('%d %b %Y')}",
            "",
        ])
    lines.extend([
        f"Total Trades: {total}",
        f"Wins: {wins}",
        f"Losses: {losses}",
        "",
        "🧠 Emotion vs Realized PnL",
        "",
    ])
    for emo, pnls in sorted(emotions.items(), key=lambda x: -len(x[1])):
        avg = sum(pnls) / len(pnls) if pnls else 0
        note = " *Note: custom entry" if emo == "Other" else ""
        lines.append(f"{emo} → {len(pnls)} trades → {round(avg, 1):+.1f}%{note}")
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
        best_slot = _format_time_slot_local(best_b[0], 3, tz_offset)
        worst_slot = _format_time_slot_local(worst_b[0], 3, tz_offset)
        lines.append(f"{best_slot} → {round(best_avg, 1):+.1f}%")
        lines.append("")
        lines.append("Worst Time:")
        lines.append(f"{worst_slot} → {round(worst_avg, 1):+.1f}%")
        lines.append("")
    lines.append("Token Category:")
    for cat, pnls in sorted(categories.items(), key=lambda x: -len(x[1])):
        avg = sum(pnls) / len(pnls) if pnls else 0
        note = " *Note: custom" if cat == "Other" else ""
        lines.append(f"{cat} → {round(avg, 1):+.1f}%{note}")
    full_token_list = []
    if token_pnls:
        for sym, pnls in sorted(token_pnls.items(), key=lambda x: -sum(x[1]) / len(x[1]) if x[1] else 0):
            avg = sum(pnls) / len(pnls) if pnls else 0
            full_token_list.append((sym, avg))
    total_pages = max(1, (len(full_token_list) + per_page - 1) // per_page) if full_token_list else 0
    page = max(0, min(page, total_pages - 1)) if total_pages else 0
    token_list_page = full_token_list[page * per_page : (page + 1) * per_page] if full_token_list else []
    if full_token_list:
        lines.append("")
        lines.append("💰 Token performance")
        lines.append("")
        if total_pages > 1:
            lines.append(f"Page {page + 1} / {total_pages}")
            lines.append("")
        for sym, avg in token_list_page:
            pct = round(avg, 1)
            pct_str = f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"
            lines.append(f"${sym} → {pct_str}")
    return "\n".join(lines), token_list_page, total_pages


async def _render_stats_screen(callback: CallbackQuery) -> None:
    """Step 1: show only chain selection buttons."""
    from bot.database.db import get_user_timezone_offset, get_user_premium_status
    user_id = callback.from_user.id
    trades = await get_valid_trades_for_stats(user_id)
    trade_ids = [t.trade_id for t in trades if t.trade_id]
    exit_totals = await get_exit_totals_for_trades(trade_ids) if trade_ids else {}
    tz_offset = await get_user_timezone_offset(user_id)
    text, _token_list, _total_pages = _build_stats(user_id, trades, exit_totals, page=0, per_page=9999, tz_offset=tz_offset)
    status = await get_user_premium_status(user_id)
    badge = "💎 BehaveBot Pro" if status.get("is_premium") else "Basic Trader"
    text = f"{badge}\n\n{text}"
    await show_internal_screen(callback, text, kb_stats_chain_only())


@router.callback_query(F.data == "stats")
async def show_stats(callback: CallbackQuery) -> None:
    await _render_stats_screen(callback)

def _chain_code_to_network(code: str) -> str | None:
    code = (code or "").strip().upper()
    if code == "BNB":
        return "BNB Chain"
    if code == "SOL":
        return "Solana"
    if code == "BASE":
        return "Base"
    return None


@router.callback_query(F.data.startswith("stats_chain_pick:"))
async def stats_chain_pick_cb(callback: CallbackQuery) -> None:
    await callback.answer()
    code = callback.data.split(":", 1)[1] if ":" in callback.data else ""
    await _render_chain_tokens(callback, code, page=0)


@router.callback_query(F.data.startswith("stats_chain_page:"))
async def stats_chain_page_cb(callback: CallbackQuery) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) < 3:
        return
    code = parts[1]
    try:
        page = int(parts[2])
    except ValueError:
        page = 0
    await _render_chain_tokens(callback, code, page=page)


async def _render_chain_tokens(callback: CallbackQuery, chain_code: str, page: int = 0) -> None:
    from bot.database.db import get_user_premium_status
    from bot.utils.formatters import format_pnl
    user_id = callback.from_user.id
    network = _chain_code_to_network(chain_code)
    if not network:
        await show_internal_screen(callback, "📊 My Stats\n\nSelect a chain:", kb_stats_chain_only())
        return
    trades = await get_valid_trades_for_stats_by_network(user_id, network)
    trade_ids = [t.trade_id for t in trades if t.trade_id]
    exit_totals = await get_exit_totals_for_trades(trade_ids) if trade_ids else {}

    # Build token → avg pnl%
    token_pnls = {}
    token_counts = {}
    for t in trades:
        entry_total = _trade_entry_total(t)
        exit_total = exit_totals.get(t.trade_id, 0.0) or 0.0
        pnl = _trade_pnl_from_totals(entry_total, exit_total)
        sym = (t.token_symbol or "").strip()
        if not sym:
            continue
        token_pnls[sym] = token_pnls.get(sym, 0.0) + pnl
        token_counts[sym] = token_counts.get(sym, 0) + 1

    full_list = []
    for sym, total_pnl in token_pnls.items():
        n = token_counts.get(sym, 1) or 1
        full_list.append((sym, total_pnl / n))
    full_list.sort(key=lambda x: x[0])

    per_page = 5
    total_pages = max(1, (len(full_list) + per_page - 1) // per_page) if full_list else 1
    page = max(0, min(page, total_pages - 1))
    page_items = full_list[page * per_page : (page + 1) * per_page]

    status = await get_user_premium_status(user_id)
    badge = "💎 BehaveBot Pro" if status.get("is_premium") else "Basic Trader"
    header = f"{badge}\n\n📊 My Stats — {network}\n\n"
    if not full_list:
        text = header + "No closed trades for this chain yet."
    else:
        lines = [header, f"Tokens (page {page + 1}/{total_pages})", ""]
        for sym, avg in page_items:
            lines.append(f"{sym} → {format_pnl(avg)}")
        text = "\n".join(lines)

    await callback.message.edit_text(
        text,
        reply_markup=kb_stats_chain_token_list(chain_code.upper(), page_items, page, total_pages),
    )


def _fmt_trade_behavior(
    t,
    exit_total: float = 0.0,
    resolved_symbol: str = None,
    resolved_name: str = None,
    open_time_str: str | None = None,
    close_time_str: str | None = None,
) -> str:
    """Full behavioral breakdown for one closed trade (stats token history).
    PnL uses entry_total_usd and exit_total (from trade_exits) for correct DCA/partial handling."""
    from bot.utils.formatters import (
        get_network_icon,
        format_duration_seconds,
        format_token_display,
        format_price,
        format_pnl,
        format_compact_number,
    )

    sym = (resolved_symbol or t.token_symbol or "?").strip()
    name = resolved_name or getattr(t, "token_name", None)
    token_display = format_token_display(sym, name)
    chain_label = get_network_icon(t.network or "")
    contract = (t.token_address or "—")
    price_open = format_price(t.open_price) if t.open_price is not None else "—"
    price_close = format_price(t.close_price) if t.close_price is not None else "—"
    entry_total = _trade_entry_total(t)
    pnl = _trade_pnl_from_totals(entry_total, exit_total)
    pnl_emoji = "📈" if pnl >= 0 else "📉"
    pnl_str = format_pnl(pnl)
    duration_str = format_duration_seconds(t.duration or 0)
    emotion_open = (t.emotion_open or "").strip()
    if emotion_open and t.emotion_open_note:
        emotion_open = f"{emotion_open} ({t.emotion_open_note})"
    emotion_close = (t.emotion_close or "").strip()
    if emotion_close and t.emotion_close_note:
        emotion_close = f"{emotion_close} ({t.emotion_close_note})"
    date_block = ""
    if open_time_str or close_time_str:
        date_block = (
            "\n\n📅 Date\n"
            + (f"Open: {open_time_str}\n" if open_time_str else "")
            + (f"Close: {close_time_str}\n" if close_time_str else "")
        )
    lines = [
        f"🪙 {token_display}",
        f"🌐 Chain: {chain_label}",
        "",
        f"📄 Contract\n<code>{contract}</code>\n(Tap for copy address)",
    ]
    behavioral_lines = []
    cat = (t.token_category or "").strip()
    if cat:
        cat_line = f"🏷 Category: {cat}"
        if t.token_category_note:
            cat_line += f" ({t.token_category_note})"
        behavioral_lines.append(cat_line)
    reason = (t.reason_open or "").strip()
    if reason:
        reason_line = f"🎯 Entry Reason: {reason}"
        if t.reason_open_note:
            reason_line += f" ({t.reason_open_note})"
        behavioral_lines.append(reason_line)
    if emotion_open:
        behavioral_lines.append(f"😈 Emotion Open: {emotion_open}")
    if emotion_close:
        behavioral_lines.append(f"😱 Emotion Close: {emotion_close}")
    if (t.risk_level or "").strip():
        behavioral_lines.append(f"⚖ Risk Level: {t.risk_level}")
    if behavioral_lines:
        lines.extend(["", "🧠 Behavioral Breakdown", ""])
        lines.extend(behavioral_lines)
    market_lines = []
    if t.mcap_open is not None:
        market_lines.append(f"🏦 Market Cap Open: ${format_compact_number(t.mcap_open)}")
    if t.mcap_close is not None:
        market_lines.append(f"🏦 Market Cap Close: ${format_compact_number(t.mcap_close)}")
    if t.open_price is not None:
        market_lines.append(f"💲 Price Open: ~ {price_open}")
    if t.close_price is not None:
        market_lines.append(f"💲 Price Close: ~ {price_close}")
    if market_lines:
        lines.extend(["", "📊 Market Data", ""])
        lines.extend(market_lines)
    lines.extend(["", f"{pnl_emoji} PnL", pnl_str])
    if date_block:
        lines.extend(["", date_block.strip()])
    lines.extend(["", f"⏱ Duration\n{duration_str}"])
    return "\n".join(lines)


@router.callback_query(F.data.startswith("stat_token:"))
async def show_token_history(callback: CallbackQuery) -> None:
    from bot.database.db import get_token_metadata, get_trade_note
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
    trade_ids = [t.trade_id for t in trades if t.trade_id]
    exit_totals = await get_exit_totals_for_trades(trade_ids) if trade_ids else {}
    total_entry = sum(_trade_entry_total(t) for t in trades)
    total_exit = sum(exit_totals.get(t.trade_id, 0.0) or 0.0 for t in trades)
    pnls = [_trade_pnl_from_totals(_trade_entry_total(t), exit_totals.get(t.trade_id, 0.0) or 0.0) for t in trades]
    avg_pnl = sum(pnls) / len(pnls) if pnls else 0.0
    portfolio_pct = ((total_exit - total_entry) / total_entry * 100.0) if total_entry and total_entry > 0 else 0.0
    from bot.utils.formatters import format_pnl
    lines = [
        f"🪙 ${symbol} — closed trades",
        "",
        "📊 Performance",
        f"Average Trade: {format_pnl(avg_pnl)}",
        f"Portfolio Realized PnL: {format_pnl(portfolio_pct)}",
        f"Total Trades: {len(trades)}",
        "",
    ]
    if len(trades) == 1:
        t = trades[0]
        meta = await get_token_metadata(t.token_address) if t.token_address else None
        resolved_symbol = (meta["symbol"] if meta else None) or t.token_symbol
        resolved_name = (meta["name"] if meta else None) or getattr(t, "token_name", None)
        exit_total = exit_totals.get(t.trade_id, 0.0) or 0.0
        lines.append(_fmt_trade_behavior(t, exit_total, resolved_symbol, resolved_name))
        note = await get_trade_note(t.trade_id, callback.from_user.id) if t.trade_id else None
        note_text = (note.get("note_text") or "").strip() if note else ""
        if note_text:
            lines.append("")
            lines.append(f"📝 Note\n\"{note_text}\"")
        text = "\n".join(lines)
        from bot.keyboards import kb_stats_trade_detail
        admin_delete_cb = f"admin_delete_trade_prompt:{t.trade_id}:-:0" if callback.from_user.id in ADMIN_IDS else None
        await callback.message.edit_text(
            text,
            reply_markup=kb_stats_trade_detail(t.trade_id, bool(note_text), symbol, admin_delete_cb=admin_delete_cb),
        )
    else:
        for i, t in enumerate(trades, 1):
            lines.append(f"——— Trade #{i} ———")
            exit_total = exit_totals.get(t.trade_id, 0.0) or 0.0
            entry_total = _trade_entry_total(t)
            pnl = _trade_pnl_from_totals(entry_total, exit_total)
            pnl_str = format_pnl(pnl)
            entry_str = f"${entry_total:,.2f}" if entry_total else "—"
            note = await get_trade_note(t.trade_id, callback.from_user.id) if t.trade_id else None
            note_indicator = " 📝" if (note and (note.get("note_text") or "").strip()) else ""
            lines.append(f"Entry: {entry_str} | Realized PnL: {pnl_str}{note_indicator}")
            lines.append("")
        lines.append("Tap a trade to see full details and add or edit note.")
        text = "\n".join(lines)
        from bot.keyboards import kb_stats_token_trades
        await callback.message.edit_text(text, reply_markup=kb_stats_token_trades(symbol, trades))


@router.callback_query(F.data.startswith("back_to_chain:"))
async def back_to_chain_list(callback: CallbackQuery) -> None:
    """Return to chain token list at the correct page."""
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) < 3:
        return
    chain_code = parts[1]
    try:
        page = int(parts[2])
    except (IndexError, ValueError):
        page = 0
    await _render_chain_tokens(callback, chain_code, page=page)


@router.callback_query(F.data.startswith("stat_token_chain:"))
async def show_token_history_chain(callback: CallbackQuery) -> None:
    """Token history filtered by chain (from chain token list)."""
    from bot.database.db import get_token_metadata, get_trade_note
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) < 3:
        return
    chain_code = parts[1]
    symbol = parts[2]
    try:
        page = int(parts[3]) if len(parts) >= 4 else 0
    except (IndexError, ValueError):
        page = 0
    network = _chain_code_to_network(chain_code)
    if not network:
        return
    trades = await get_closed_trades_by_token_network(callback.from_user.id, symbol, network)
    if not trades:
        await callback.message.edit_text(f"No closed trades for {symbol} on {network}.", reply_markup=kb_back_to_menu())
        return
    trade_ids = [t.trade_id for t in trades if t.trade_id]
    exit_totals = await get_exit_totals_for_trades(trade_ids) if trade_ids else {}
    total_entry = sum(_trade_entry_total(t) for t in trades)
    total_exit = sum(exit_totals.get(t.trade_id, 0.0) or 0.0 for t in trades)
    pnls = [_trade_pnl_from_totals(_trade_entry_total(t), exit_totals.get(t.trade_id, 0.0) or 0.0) for t in trades]
    avg_pnl = sum(pnls) / len(pnls) if pnls else 0.0
    portfolio_pct = ((total_exit - total_entry) / total_entry * 100.0) if total_entry and total_entry > 0 else 0.0
    from bot.utils.formatters import format_pnl
    lines = [
        f"🪙 ${symbol} — {network}",
        "",
        "📊 Performance",
        f"Average Trade: {format_pnl(avg_pnl)}",
        f"Portfolio Realized PnL: {format_pnl(portfolio_pct)}",
        f"Total Trades: {len(trades)}",
        "",
    ]
    if len(trades) == 1:
        t = trades[0]
        meta = await get_token_metadata(t.token_address) if t.token_address else None
        resolved_symbol = (meta["symbol"] if meta else None) or t.token_symbol
        resolved_name = (meta["name"] if meta else None) or getattr(t, "token_name", None)
        exit_total = exit_totals.get(t.trade_id, 0.0) or 0.0
        lines.append(_fmt_trade_behavior(t, exit_total, resolved_symbol, resolved_name))
        note = await get_trade_note(t.trade_id, callback.from_user.id) if t.trade_id else None
        note_text = (note.get("note_text") or "").strip() if note else ""
        if note_text:
            lines.append("")
            lines.append(f"📝 Note\n\"{note_text}\"")
        text = "\n".join(lines)
        from bot.keyboards import kb_stats_trade_detail
        admin_delete_cb = (
            f"admin_delete_trade_prompt:{t.trade_id}:{chain_code}:{page}"
            if callback.from_user.id in ADMIN_IDS
            else None
        )
        await callback.message.edit_text(
            text,
            reply_markup=kb_stats_trade_detail(
                t.trade_id,
                bool(note_text),
                symbol,
                chain_code=chain_code,
                page=page,
                admin_delete_cb=admin_delete_cb,
            ),
        )
    else:
        for i, t in enumerate(trades, 1):
            lines.append(f"——— Trade #{i} ———")
            exit_total = exit_totals.get(t.trade_id, 0.0) or 0.0
            entry_total = _trade_entry_total(t)
            pnl = _trade_pnl_from_totals(entry_total, exit_total)
            pnl_str = format_pnl(pnl)
            entry_str = f"${entry_total:,.2f}" if entry_total else "—"
            note = await get_trade_note(t.trade_id, callback.from_user.id) if t.trade_id else None
            note_indicator = " 📝" if (note and (note.get("note_text") or "").strip()) else ""
            lines.append(f"Entry: {entry_str} | Realized PnL: {pnl_str}{note_indicator}")
            lines.append("")
        lines.append("Tap a trade to see full details and add or edit note.")
        text = "\n".join(lines)
        from bot.keyboards import kb_stats_token_trades
        await callback.message.edit_text(
            text,
            reply_markup=kb_stats_token_trades(symbol, trades, chain_code=chain_code, page=page),
        )


@router.callback_query(F.data.startswith("stat_trade_detail:"))
async def show_trade_detail(callback: CallbackQuery) -> None:
    """Show individual trade detail with Add/Edit Note. Back returns to chain list if opened from chain."""
    from bot.database.db import get_trade_by_id, get_token_metadata, get_trade_note
    await callback.answer()
    parts = callback.data.split(":")
    try:
        trade_id = int(parts[1])
    except (IndexError, ValueError):
        return
    symbol = parts[2] if len(parts) > 2 else ""
    chain_code = parts[3] if len(parts) > 3 else None
    try:
        page = int(parts[4]) if len(parts) > 4 else 0
    except (IndexError, ValueError):
        page = 0
    await _render_trade_detail(callback, trade_id, symbol=symbol, chain_code=chain_code, page=page)


async def _render_trade_detail(
    callback: CallbackQuery,
    trade_id: int,
    symbol: str = "",
    chain_code: str | None = None,
    page: int = 0,
) -> None:
    from bot.database.db import get_trade_by_id, get_token_metadata, get_trade_note
    trade = await get_trade_by_id(trade_id, callback.from_user.id)
    if not trade:
        await callback.message.edit_text("Trade not found.", reply_markup=kb_back_to_menu())
        return
    exit_totals = await get_exit_totals_for_trades([trade_id])
    exit_total = exit_totals.get(trade_id, 0.0) or 0.0
    meta = await get_token_metadata(trade.token_address) if trade.token_address else None
    resolved_symbol = (meta["symbol"] if meta else None) or trade.token_symbol
    resolved_name = (meta["name"] if meta else None) or getattr(trade, "token_name", None)
    from bot.utils.formatters import format_user_time
    ot = trade.open_time if isinstance(trade.open_time, datetime) else datetime.fromisoformat(str(trade.open_time))
    open_time_str = await format_user_time(callback.from_user.id, ot.isoformat()) if ot else "—"
    close_time_str = None
    if trade.close_time:
        ct = trade.close_time if isinstance(trade.close_time, datetime) else datetime.fromisoformat(str(trade.close_time))
        close_time_str = await format_user_time(callback.from_user.id, ct.isoformat()) if ct else None
    lines = [_fmt_trade_behavior(trade, exit_total, resolved_symbol, resolved_name, open_time_str=open_time_str, close_time_str=close_time_str)]
    note = await get_trade_note(trade_id, callback.from_user.id)
    note_text = (note.get("note_text") or "").strip() if note else ""
    if note_text:
        lines.append("")
        lines.append(f"📝 Note\n\"{note_text}\"")
    text = "\n".join(lines)
    from bot.keyboards import kb_stats_trade_detail
    admin_delete_cb = None
    if callback.from_user.id in ADMIN_IDS:
        cc = chain_code or "-"
        admin_delete_cb = f"admin_delete_trade_prompt:{trade_id}:{cc}:{page}"
    await callback.message.edit_text(
        text,
        reply_markup=kb_stats_trade_detail(
            trade_id,
            bool(note_text),
            symbol or resolved_symbol,
            chain_code=chain_code,
            page=page if chain_code is not None else None,
            admin_delete_cb=admin_delete_cb,
        ),
    )


@router.callback_query(F.data.startswith("back_to_trade_detail:"))
async def back_to_trade_detail(callback: CallbackQuery) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) < 4:
        return
    try:
        trade_id = int(parts[1])
        page = int(parts[3])
    except (ValueError, IndexError):
        return
    chain_code = parts[2]
    if chain_code == "-":
        chain_code = None
    await _render_trade_detail(callback, trade_id, chain_code=chain_code, page=page)


@router.callback_query(F.data.startswith("admin_delete_trade_prompt:"))
async def admin_delete_trade_prompt(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user.id not in ADMIN_IDS:
        return
    parts = callback.data.split(":")
    if len(parts) < 4:
        return
    try:
        trade_id = int(parts[1])
        page = int(parts[3])
    except (ValueError, IndexError):
        return
    chain_code = parts[2]
    if chain_code == "-":
        chain_code = None
    from bot.keyboards import kb_admin_delete_trade_confirm
    await callback.message.edit_text(
        "Are you sure you want to delete this trade data?",
        reply_markup=kb_admin_delete_trade_confirm(trade_id, chain_code=chain_code, page=page),
    )


@router.callback_query(F.data.startswith("admin_delete_trade_confirm:"))
async def admin_delete_trade_confirm(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user.id not in ADMIN_IDS:
        return
    parts = callback.data.split(":")
    if len(parts) < 4:
        return
    try:
        trade_id = int(parts[1])
        page = int(parts[3])
    except (ValueError, IndexError):
        return
    chain_code = parts[2]
    if chain_code == "-":
        chain_code = None
    from bot.database.db import delete_trade_and_exits
    _ = await delete_trade_and_exits(trade_id, callback.from_user.id)
    await callback.message.answer("Trade deleted successfully. MyStats updated.")
    if chain_code:
        await _render_chain_tokens(callback, chain_code, page=page)
    else:
        await _render_stats_screen(callback)
