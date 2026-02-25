from datetime import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from bot.database.db import get_trade_by_id, update_trade_close
from bot.services import fetch_token_data as fetch_td
from bot.keyboards import (
    kb_emotion_close,
    kb_reason_close,
    kb_discipline,
    kb_after_close,
)
from bot.states import ClosePositionStates

router = Router()

CLOSE_NO_OPEN = "You have no open position to close. Send a token CA to open one."
Q5 = "What was your emotion when closing?"
Q6 = "Why did you close?"
Q7 = "Did you follow your plan?"
TRADE_RECORDED = "✅ Trade recorded successfully."


def _format_close_summary(
    symbol: str, open_p: float, close_p: float, pnl: float, duration_mins: int
) -> str:
    op = f"${open_p:.8f}" if open_p < 0.0001 else f"${open_p:.6f}"
    cp = f"${close_p:.8f}" if close_p < 0.0001 else f"${close_p:.6f}"
    return (
        f"🔴 Position Closed: {symbol}\n\n"
        f"Open: {op}\n"
        f"Close: {cp}\n"
        f"Result: {pnl:+.1f}%\n"
        f"Duration: {duration_mins} minutes\n\n"
        f"Now help me understand why you closed."
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
    duration_mins = int((close_time - open_time).total_seconds() / 60)
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
        duration_mins=duration_mins,
    )
    await state.set_state(ClosePositionStates.emotion)
    msg = _format_close_summary(
        trade.token_symbol, trade.open_price, close_price, pnl, duration_mins
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
    trade_id = data["trade_id"]
    await update_trade_close(
        trade_id=trade_id,
        close_time=data["close_time"],
        close_price=data["close_price"],
        mcap_close=data.get("mcap_close"),
        duration=float(data["duration_mins"]),
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
