from datetime import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from bot.database.db import get_trade_by_id, set_trade_invalid, get_open_trades
from bot.keyboards import kb_back_to_menu, kb_after_close, kb_open_trades_list, kb_position_detail
from bot.states import MarkInvalidStates

router = Router()


@router.callback_query(F.data == "view_past_trades")
async def view_past_trades(callback: CallbackQuery) -> None:
    from bot.database.db import get_valid_trades_for_stats
    from bot.handlers.stats import _build_stats
    await callback.answer()
    trades = await get_valid_trades_for_stats(callback.from_user.id)
    text = _build_stats(callback.from_user.id, trades)
    await callback.message.edit_text(text, reply_markup=kb_back_to_menu())


@router.callback_query(F.data.startswith("position_detail:"))
async def position_detail(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        trade_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return
    trade = await get_trade_by_id(trade_id, callback.from_user.id)
    if not trade or trade.close_time is not None:
        await callback.message.edit_text("Position not found.", reply_markup=kb_back_to_menu())
        return
    ot = trade.open_time if isinstance(trade.open_time, datetime) else datetime.fromisoformat(str(trade.open_time))
    mins = int((datetime.utcnow() - ot).total_seconds() / 60)
    text = (
        f"📌 {trade.token_symbol}\n\n"
        f"Open: ${trade.open_price}\n"
        f"Duration: {mins} min\n\n"
        f"Choose an action:"
    )
    await callback.message.edit_text(text, reply_markup=kb_position_detail(trade_id))


@router.callback_query(F.data == "positions_list")
async def positions_list(callback: CallbackQuery) -> None:
    await callback.answer()
    open_trades = await get_open_trades(callback.from_user.id)
    if not open_trades:
        await callback.message.edit_text("You have no open positions.", reply_markup=kb_back_to_menu())
        return
    lines = []
    for t in open_trades:
        ot = t.open_time if isinstance(t.open_time, datetime) else datetime.fromisoformat(str(t.open_time))
        mins = int((datetime.utcnow() - ot).total_seconds() / 60)
        mcap_str = f"${t.mcap_open:,.0f}" if t.mcap_open else "N/A"
        lines.append(f"• {t.token_symbol} | 🏦 Mcap at open: {mcap_str} | {mins} min")
    msg = "📈 My Positions\n\n" + "\n".join(lines) + "\n\nTap a position:"
    pairs = [(t.trade_id, t.token_symbol) for t in open_trades]
    await callback.message.edit_text(msg, reply_markup=kb_open_trades_list(pairs))


@router.callback_query(F.data.startswith("view_report:"))
async def view_report(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        trade_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return
    trade = await get_trade_by_id(trade_id, callback.from_user.id)
    if not trade:
        await callback.message.answer("Trade not found.")
        return
    pnl = (
        ((trade.close_price - trade.open_price) / trade.open_price) * 100
        if trade.open_price and trade.close_price
        else 0
    )
    duration = int(trade.duration) if trade.duration else 0
    mcap_open = f"${trade.mcap_open:,.0f}" if trade.mcap_open else "N/A"
    mcap_close = f"${trade.mcap_close:,.0f}" if trade.mcap_close else "N/A"
    text = (
        f"📋 Trade Report: {trade.token_symbol}\n\n"
        f"📊 Price\n"
        f"Open: ${trade.open_price}\n"
        f"Close: ${trade.close_price}\n\n"
        f"🏦 Market Cap\n"
        f"Open: {mcap_open}\n"
        f"Close: {mcap_close}\n\n"
        f"📉 Result\n"
        f"{pnl:+.1f}%\n\n"
        f"⏱ Duration\n"
        f"{duration} min\n\n"
        f"Emotion (open): {trade.emotion_open}"
        + (f" ({trade.emotion_open_note})" if trade.emotion_open_note else "")
        + "\n"
        f"Reason (open): {trade.reason_open}"
        + (f" ({trade.reason_open_note})" if trade.reason_open_note else "")
        + "\n"
        f"Category: {trade.token_category}"
        + (f" ({trade.token_category_note})" if trade.token_category_note else "")
        + "\n"
        f"Risk: {trade.risk_level}\n\n"
        f"Emotion (close): {trade.emotion_close}"
        + (f" ({trade.emotion_close_note})" if trade.emotion_close_note else "")
        + "\n"
        f"Reason (close): {trade.reason_close}"
        + (f" ({trade.reason_close_note})" if trade.reason_close_note else "")
        + "\n"
        f"Discipline: {trade.discipline}"
    )
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
