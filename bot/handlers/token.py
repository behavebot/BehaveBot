import re
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.database.db import get_open_trades, get_last_closed_trade_for_token
from bot.services import (
    fetch_token_data,
    set_pending_token,
    clear_pending_token,
    get_cached_token,
    set_cached_token,
)
from bot.keyboards import (
    kb_token_preview,
    kb_open_or_view_cancel,
    kb_open_new_or_past_cancel,
    main_menu_keyboard,
    kb_back_to_menu,
    MAIN_MENU_BUTTON_TEXTS,
)
from bot.states import OpenPositionStates, ClosePositionStates, MarkInvalidStates

router = Router()

LOADING_MSG = "Fetching latest data…"
TOKEN_FETCH_FAIL = "Could not fetch token data for this address. Check the contract address and try again."
CA_WHILE_ANSWERING = "Finish this step or use /cancel to reset."


def _fsm_expects_free_text(state: str | None) -> bool:
    if not state:
        return False
    return any(
        state.startswith(x)
        for x in (
            "OpenPositionStates:emotion_note",
            "OpenPositionStates:reason_note",
            "OpenPositionStates:category_note",
            "ClosePositionStates:emotion_note",
            "ClosePositionStates:reason_note",
            "MarkInvalidStates:reason_note",
        )
    )


def _fmt_token_msg(td) -> str:
    mcap = f"${td.mcap:,.0f}" if td.mcap else "N/A"
    liq = f"${td.liquidity:,.0f}" if td.liquidity else "N/A"
    vol = f"${td.volume_1h:,.0f}" if td.volume_1h else "N/A"
    age = td.age or "N/A"
    price = f"${td.price:.8f}" if td.price < 0.0001 else f"${td.price:.6f}"
    network = getattr(td, "chain", None) or getattr(td, "network", None) or "N/A"
    dex = getattr(td, "dex_name", None) or "N/A"
    token_block = (
        f"🪙 TOKEN SNAPSHOT\n"
        f"🌐 Network: {network}\n"
        f"💰 Price: {price}\n"
        f"🏦 Market Cap: {mcap}\n"
        f"⏳ Age: {age}\n"
    )
    pool_block = (
        f"💧 POOL INFO\n"
        f"💧 Liquidity: {liq}\n"
        f"📊 Volume (1H): {vol}\n"
        f"🔁 Dex: {dex}\n"
    )
    tax_block = (
        f"🛡 TOKEN TAX\n"
        f"Tax info not available\n"
    )
    return f"📊 {td.name} (${td.symbol})\n\n{token_block}\n{pool_block}\n{tax_block}\nDo you want to open a position?"


@router.message(F.text)
async def on_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        return
    if text.startswith("/"):
        return
    if text in MAIN_MENU_BUTTON_TEXTS:
        return
    if len(text) < 20:
        return
    raw = (text or "").strip()
    ca = raw.lower() if re.match(r"^0x[a-fA-F0-9]{40}$", raw) else ("0x" + raw.lower() if re.match(r"^[a-fA-F0-9]{40}$", raw) else None)
    if not ca:
        current = await state.get_state()
        if current and (
            current.startswith("OpenPositionStates:")
            or current.startswith("ClosePositionStates:")
            or current.startswith("MarkInvalidStates:")
        ):
            await message.answer(CA_WHILE_ANSWERING)
        return
    await state.clear()
    clear_pending_token(message.from_user.id)
    cached = get_cached_token(ca)
    if cached:
        td = cached
    else:
        loading = await message.answer(LOADING_MSG)
        td = await fetch_token_data(text)
        try:
            await loading.delete()
        except Exception:
            pass
        if td:
            set_cached_token(td.token_address, td)
    if not td:
        await message.answer(TOKEN_FETCH_FAIL)
        return
    set_pending_token(message.from_user.id, td)
    open_trades = await get_open_trades(message.from_user.id)
    has_same_open = any(t.token_address.lower() == td.token_address for t in open_trades)
    if has_same_open:
        await message.answer(
            "You already have an open position for this token. Close it first before opening again."
        )
        clear_pending_token(message.from_user.id)
        return
    if open_trades:
        lines = []
        for t in open_trades:
            open_dt = (
                t.open_time
                if isinstance(t.open_time, datetime)
                else datetime.fromisoformat(str(t.open_time))
            )
            mins = int((datetime.utcnow() - open_dt).total_seconds() / 60)
            lines.append(f"• {t.token_symbol} ({mins} min)")
        msg = (
            f"You currently have {len(open_trades)} open position(s):\n"
            + "\n".join(lines)
            + f"\n\nToken: {td.name} (${td.symbol}). Open new position?"
        )
        await message.answer(msg, reply_markup=kb_open_or_view_cancel())
        return
    prev = await get_last_closed_trade_for_token(message.from_user.id, td.token_address)
    if prev and prev.close_price and prev.open_price:
        pnl = ((prev.close_price - prev.open_price) / prev.open_price) * 100
        msg = (
            f"You traded {td.symbol} before.\n\n"
            f"Previous result: {pnl:+.1f}%\n\n"
            f"Token: {td.name} (${td.symbol}). Open new position?"
        )
        await message.answer(msg, reply_markup=kb_open_new_or_past_cancel())
        return
    await message.answer(_fmt_token_msg(td), reply_markup=kb_token_preview())


@router.callback_query(F.data == "token_cancel")
async def token_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    from bot.handlers.start import show_main_menu
    await show_main_menu(callback, state)


@router.callback_query(F.data == "token_refresh")
async def token_refresh(callback: CallbackQuery, state: FSMContext) -> None:
    from bot.services import get_pending_token
    await callback.answer()
    pending = get_pending_token(callback.from_user.id)
    if not pending:
        await callback.message.edit_text("No token in preview. Send a contract address.")
        return
    await callback.message.edit_text(LOADING_MSG)
    td = await fetch_token_data(pending.token_address)
    if not td:
        await callback.message.edit_text(TOKEN_FETCH_FAIL)
        return
    set_pending_token(callback.from_user.id, td)
    await callback.message.edit_text(_fmt_token_msg(td), reply_markup=kb_token_preview())
