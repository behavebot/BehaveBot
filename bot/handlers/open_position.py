from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.database.db import (
    get_open_trades,
    insert_trade,
    get_open_trade_for_token,
    get_db,
)
from bot.database.models import Trade
from bot.services import get_pending_token, set_pending_token, clear_pending_token
from bot.keyboards import (
    kb_emotion_open,
    kb_reason_open,
    kb_category,
    kb_risk,
    kb_close_position,
    kb_open_trades_list,
    kb_back_to_menu,
)
from bot.states import OpenPositionStates

router = Router()

Q1 = "What was your emotion when opening this position?"
Q2 = "Why did you open this trade?"
Q3 = "Token category?"
Q4 = "How risky do you think this trade is?"
OTHER_EMOTION = "Please write your emotion:"
OTHER_REASON = "Please specify your reason:"
OTHER_CATEGORY = "Please specify category:\n(e.g. DeFi + Meme)"
TRACKED = "✅ Trade is now being tracked.\nPress CLOSE POSITION when you exit this trade."


@router.callback_query(F.data == "open_position")
async def start_open_position(callback: CallbackQuery, state: FSMContext) -> None:
    from bot.services import fetch_token_data
    from bot.handlers.token import LOADING_MSG
    await callback.answer()
    user_id = callback.from_user.id
    pending = get_pending_token(user_id)
    if not pending:
        await callback.message.answer("Please send a token contract address first.")
        return
    await callback.message.edit_text(LOADING_MSG)
    td = await fetch_token_data(pending.token_address)
    if not td:
        from bot.handlers.token import _fmt_token_msg
        from bot.keyboards import kb_token_preview
        await callback.message.edit_text(
            "Could not fetch latest data. Try Refresh or send the CA again.\n\n" + _fmt_token_msg(pending),
            reply_markup=kb_token_preview(),
        )
        return
    set_pending_token(user_id, td)
    pending = td
    open_trade = await get_open_trade_for_token(user_id, pending.token_address)
    if open_trade:
        await callback.message.edit_text("You already have an open position for this token.")
        return
    now = datetime.utcnow()
    trade = Trade(
        trade_id=None,
        user_id=user_id,
        token_address=pending.token_address,
        token_symbol=pending.symbol,
        open_time=now,
        close_time=None,
        open_price=pending.price,
        close_price=None,
        mcap_open=pending.mcap,
        mcap_close=None,
        duration=None,
        emotion_open="",
        emotion_open_note=None,
        reason_open="",
        reason_open_note=None,
        token_category="",
        token_category_note=None,
        risk_level="",
        emotion_close=None,
        emotion_close_note=None,
        reason_close=None,
        reason_close_note=None,
        discipline=None,
        status="valid",
    )
    trade_id = await insert_trade(trade)
    clear_pending_token(user_id)
    await state.update_data(
        trade_id=trade_id,
        token_address=pending.token_address,
        token_symbol=pending.symbol,
    )
    await state.set_state(OpenPositionStates.emotion)
    await callback.message.edit_text(Q1, reply_markup=kb_emotion_open())


@router.callback_query(F.data.startswith("emotion_open:"), OpenPositionStates.emotion)
async def emotion_open_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    value = callback.data.replace("emotion_open:", "")
    if value == "Other":
        await state.set_state(OpenPositionStates.emotion_note)
        await callback.message.edit_text(OTHER_EMOTION)
        return
    await state.update_data(emotion_open=value)
    await state.set_state(OpenPositionStates.reason)
    await callback.message.edit_text(Q2, reply_markup=kb_reason_open())


@router.message(OpenPositionStates.emotion_note, F.text)
async def emotion_open_note_msg(message: Message, state: FSMContext) -> None:
    await state.update_data(emotion_open="Other", emotion_open_note=message.text)
    await state.set_state(OpenPositionStates.reason)
    await message.answer(Q2, reply_markup=kb_reason_open())


@router.callback_query(F.data.startswith("reason_open:"), OpenPositionStates.reason)
async def reason_open_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    value = callback.data.replace("reason_open:", "")
    if value == "Other":
        await state.set_state(OpenPositionStates.reason_note)
        await callback.message.edit_text(OTHER_REASON)
        return
    await state.update_data(reason_open=value)
    await state.set_state(OpenPositionStates.category)
    await callback.message.edit_text(Q3, reply_markup=kb_category())


@router.message(OpenPositionStates.reason_note, F.text)
async def reason_open_note_msg(message: Message, state: FSMContext) -> None:
    await state.update_data(reason_open="Other", reason_open_note=message.text)
    await state.set_state(OpenPositionStates.category)
    await message.answer(Q3, reply_markup=kb_category())


@router.callback_query(F.data.startswith("category:"), OpenPositionStates.category)
async def category_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    value = callback.data.replace("category:", "")
    if value == "Other":
        await state.set_state(OpenPositionStates.category_note)
        await callback.message.edit_text(OTHER_CATEGORY)
        return
    await state.update_data(token_category=value)
    await state.set_state(OpenPositionStates.risk)
    await callback.message.edit_text(Q4, reply_markup=kb_risk())


@router.message(OpenPositionStates.category_note, F.text)
async def category_note_msg(message: Message, state: FSMContext) -> None:
    await state.update_data(token_category="Other", token_category_note=message.text)
    await state.set_state(OpenPositionStates.risk)
    await message.answer(Q4, reply_markup=kb_risk())


@router.callback_query(F.data.startswith("risk:"), OpenPositionStates.risk)
async def risk_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    value = callback.data.replace("risk:", "")
    await state.update_data(risk_level=value)
    data = await state.get_data()
    trade_id = data["trade_id"]
    db = await get_db()
    await db.execute(
        """UPDATE trades SET emotion_open=?, emotion_open_note=?, reason_open=?, reason_open_note=?,
           token_category=?, token_category_note=?, risk_level=? WHERE trade_id=?""",
        (
            data.get("emotion_open", ""),
            data.get("emotion_open_note"),
            data.get("reason_open", ""),
            data.get("reason_open_note"),
            data.get("token_category", ""),
            data.get("token_category_note"),
            data.get("risk_level", ""),
            trade_id,
        ),
    )
    await db.commit()
    await state.clear()
    await callback.message.edit_text(TRACKED, reply_markup=kb_close_position(trade_id))


@router.callback_query(F.data == "view_open_trades")
async def view_open_trades(callback: CallbackQuery) -> None:
    await callback.answer()
    open_trades = await get_open_trades(callback.from_user.id)
    if not open_trades:
        await callback.message.edit_text("You have no open positions.", reply_markup=kb_back_to_menu())
        return
    lines = []
    for t in open_trades:
        ot = (
            t.open_time
            if isinstance(t.open_time, datetime)
            else datetime.fromisoformat(str(t.open_time))
        )
        mins = int((datetime.utcnow() - ot).total_seconds() / 60)
        lines.append(f"• {t.token_symbol} ({mins} min)")
    msg = "Your open positions:\n\n" + "\n".join(lines) + "\n\nSelect one to close:"
    pairs = [(t.trade_id, t.token_symbol) for t in open_trades]
    await callback.message.edit_text(msg, reply_markup=kb_open_trades_list(pairs))
