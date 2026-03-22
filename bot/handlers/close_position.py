from datetime import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from bot.database.db import (
    get_trade_by_id,
    update_trade_close,
    update_trade_emotion_close,
    update_trade_reason_close,
    update_trade_discipline,
    insert_trade_timeline_event,
    insert_trade_exit,
)
from bot.database.models import TradeExit
from bot.services import fetch_token_data as fetch_td
from bot.keyboards import (
    kb_emotion_close,
    kb_emotion_close_auto,
    kb_reason_close,
    kb_reason_close_auto,
    kb_discipline,
    kb_discipline_auto,
    kb_after_close,
    kb_back_to_menu,
)
from bot.states import ClosePositionStates

router = Router()

CLOSE_NO_OPEN = "You have no open position to close. Send a token CA to open one."
Q5 = "How did you feel when closing this trade?"
Q6 = "Why did you close this trade?"
Q7 = "Did you follow your trading plan?"
TRADE_RECORDED = "✅ Trade recorded successfully."
AUTO_CLOSE_DONE = "✅ Thanks for helping improve your behavioral tracking."


def _ask_reason_close_auto(trade_id: int):
    return Q6, kb_reason_close_auto(trade_id)


def _ask_discipline_auto(trade_id: int):
    return Q7, kb_discipline_auto(trade_id)


@router.callback_query(F.data.startswith("emotion_close_auto:"))
async def emotion_close_auto_cb(callback: CallbackQuery, state: FSMContext) -> None:
    """Emotion close after auto-close; then ask reason (same flow as manual)."""
    await callback.answer()
    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        return
    try:
        trade_id = int(parts[1])
        emotion = parts[2].strip()
    except (ValueError, IndexError):
        return
    user_id = callback.from_user.id
    if emotion == "Other":
        await state.update_data(auto_close_trade_id=trade_id)
        await state.set_state(ClosePositionStates.auto_emotion_note)
        await callback.message.edit_text("Please write your emotion:")
        return
    updated = await update_trade_emotion_close(trade_id, user_id, emotion, None)
    if not updated:
        await callback.message.edit_text("Trade not found.", reply_markup=kb_back_to_menu())
        return
    q6, kb = _ask_reason_close_auto(trade_id)
    await callback.message.edit_text(q6, reply_markup=kb)


@router.message(ClosePositionStates.auto_emotion_note, F.text)
async def auto_emotion_note_msg(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    trade_id = data.get("auto_close_trade_id")
    await state.clear()
    if not trade_id:
        await message.answer("Session expired.", reply_markup=kb_back_to_menu())
        return
    await update_trade_emotion_close(trade_id, message.from_user.id, "Other", message.text)
    q6, kb = _ask_reason_close_auto(trade_id)
    await message.answer(q6, reply_markup=kb)


@router.callback_query(F.data.startswith("reason_close_auto:"))
async def reason_close_auto_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        return
    try:
        trade_id = int(parts[1])
        reason = parts[2].strip()
    except (ValueError, IndexError):
        return
    user_id = callback.from_user.id
    if reason == "Other":
        await state.update_data(auto_close_trade_id=trade_id)
        await state.set_state(ClosePositionStates.auto_reason_note)
        await callback.message.edit_text("Please specify your reason:")
        return
    await update_trade_reason_close(trade_id, user_id, reason, None)
    q7, kb = _ask_discipline_auto(trade_id)
    await callback.message.edit_text(q7, reply_markup=kb)


@router.message(ClosePositionStates.auto_reason_note, F.text)
async def auto_reason_note_msg(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    trade_id = data.get("auto_close_trade_id")
    await state.clear()
    if not trade_id:
        await message.answer("Session expired.", reply_markup=kb_back_to_menu())
        return
    await update_trade_reason_close(trade_id, message.from_user.id, "Other", message.text)
    q7, kb = _ask_discipline_auto(trade_id)
    await message.answer(q7, reply_markup=kb)


@router.callback_query(F.data.startswith("discipline_auto:"))
async def discipline_auto_cb(callback: CallbackQuery) -> None:
    await callback.answer()
    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        return
    try:
        trade_id = int(parts[1])
        discipline = parts[2].strip()
    except (ValueError, IndexError):
        return
    user_id = callback.from_user.id
    await update_trade_discipline(trade_id, user_id, discipline)
    await callback.message.edit_text(AUTO_CLOSE_DONE, reply_markup=kb_back_to_menu())


def _format_close_summary(
    symbol: str, open_p: float, close_p: float, pnl: float, duration_seconds: float
) -> str:
    from bot.utils.formatters import format_duration_seconds
    op = f"${open_p:.8f}" if open_p < 0.0001 else f"${open_p:.6f}"
    cp = f"${close_p:.8f}" if close_p < 0.0001 else f"${close_p:.6f}"
    result_str = f"{round(pnl, 1):+.1f}%"
    duration_str = format_duration_seconds(duration_seconds)
    return (
        f"📊 TRADE CLOSED\n\n"
        f"🪙 Token: ${symbol}\n\n"
        f"📥 Entry: {op}\n"
        f"📤 Exit: {cp}\n"
        f"Realized PnL: {result_str}\n"
        f"⏱ Duration: {duration_str}\n\n"
        f"How did you feel when closing this trade?"
    )


@router.callback_query(F.data.startswith("close_position:"))
async def start_close_position(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    try:
        trade_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.message.answer(CLOSE_NO_OPEN)
        return
    user_id = callback.from_user.id
    trade = await get_trade_by_id(trade_id, user_id)
    if not trade or trade.close_time is not None:
        await callback.message.answer(CLOSE_NO_OPEN)
        return
    td = await fetch_td(trade.token_address)
    close_price = td.price if td else trade.open_price
    open_time = (
        trade.open_time
        if isinstance(trade.open_time, datetime)
        else datetime.fromisoformat(str(trade.open_time))
    )
    close_time = datetime.utcnow()
    duration_seconds = (close_time - open_time).total_seconds()
    pnl = (
        ((close_price - trade.open_price) / trade.open_price) * 100
        if trade.open_price
        else 0
    )
    mcap_close = td.mcap if td else None
    await state.update_data(
        trade_id=trade_id,
        token_symbol=trade.token_symbol,
        open_price=trade.open_price,
        close_price=close_price,
        close_time=close_time.isoformat(),
        mcap_close=mcap_close,
        duration_seconds=duration_seconds,
    )
    await state.set_state(ClosePositionStates.emotion)
    msg = _format_close_summary(
        trade.token_symbol, trade.open_price, close_price, pnl, duration_seconds
    )
    await callback.message.edit_text(msg, reply_markup=kb_emotion_close())


@router.callback_query(F.data.startswith("emotion_close:"), ClosePositionStates.emotion)
async def emotion_close_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    value = callback.data.replace("emotion_close:", "")
    if value == "Other":
        await state.set_state(ClosePositionStates.emotion_note)
        await callback.message.edit_text("Please write your emotion:")
        return
    await state.update_data(emotion_close=value)
    await state.set_state(ClosePositionStates.reason)
    await callback.message.edit_text(Q6, reply_markup=kb_reason_close())


@router.message(ClosePositionStates.emotion_note, F.text)
async def emotion_close_note_msg(message: Message, state: FSMContext) -> None:
    await state.update_data(emotion_close="Other", emotion_close_note=message.text)
    await state.set_state(ClosePositionStates.reason)
    await message.answer(Q6, reply_markup=kb_reason_close())


@router.callback_query(F.data.startswith("reason_close:"), ClosePositionStates.reason)
async def reason_close_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    value = callback.data.replace("reason_close:", "")
    if value == "Other":
        await state.set_state(ClosePositionStates.reason_note)
        await callback.message.edit_text("Please specify your reason:")
        return
    await state.update_data(reason_close=value)
    await state.set_state(ClosePositionStates.discipline)
    await callback.message.edit_text(Q7, reply_markup=kb_discipline())


@router.message(ClosePositionStates.reason_note, F.text)
async def reason_close_note_msg(message: Message, state: FSMContext) -> None:
    await state.update_data(reason_close="Other", reason_close_note=message.text)
    await state.set_state(ClosePositionStates.discipline)
    await message.answer(Q7, reply_markup=kb_discipline())


@router.callback_query(F.data.startswith("discipline:"), ClosePositionStates.discipline)
async def discipline_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    value = callback.data.replace("discipline:", "")
    data = await state.get_data()
    trade_id = data.get("trade_id")
    if trade_id is None:
        await state.clear()
        await callback.message.edit_text(CLOSE_NO_OPEN, reply_markup=kb_back_to_menu())
        return
    duration_sec = data.get("duration_seconds") or data.get("duration_mins") or 0
    close_price = data.get("close_price") or 0
    t = await get_trade_by_id(trade_id, callback.from_user.id)
    if t:
        rq = t.remaining_quantity if t.remaining_quantity is not None else t.open_quantity or 0
        close_value = (rq * close_price) if (close_price and rq) else None
        await insert_trade_timeline_event(trade_id, "FULL_CLOSE", value_usd=close_value, amount=rq)
        # Record exit for trade accounting (entry_total vs exit_total PnL)
        await insert_trade_exit(TradeExit(
            id=None,
            trade_id=trade_id,
            amount=rq,
            price=close_price or 0,
            value_usd=close_value,
            timestamp=datetime.utcnow().isoformat(),
        ))
    await update_trade_close(
        trade_id=trade_id,
        close_time=data["close_time"],
        close_price=close_price,
        mcap_close=data.get("mcap_close"),
        duration=float(duration_sec),
        emotion_close=data.get("emotion_close", ""),
        emotion_close_note=data.get("emotion_close_note"),
        reason_close=data.get("reason_close", ""),
        reason_close_note=data.get("reason_close_note"),
        discipline=value,
    )
    await state.clear()
    await callback.message.edit_text(
        TRADE_RECORDED,
        reply_markup=kb_after_close(trade_id),
    )
