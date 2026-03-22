"""
Settings and Wallet Auto Trade Detection.

Additive only: does not modify existing trading journal logic.
When a trade is detected (mock or future real), user can "Record Trade"
and the existing Open Position flow is reused.
"""

import re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.keyboards import (
    kb_back_to_menu,
    kb_back_to_settings,
    kb_settings_menu,
    kb_timezone_select,
    TIMEZONE_OPTIONS,
    kb_connect_wallet_networks,
    kb_record_trade_detected,
    kb_connected_wallets,
    kb_wallet_detail,
    kb_auto_detection_menu,
    kb_token_preview,
    kb_pending_trades_list,
    kb_pending_trade_actions,
    kb_trade_review_actions,
    kb_trade_review_emotions,
    kb_pending_mixed_list,
)
from bot.handlers.ui_flow import show_internal_screen
from bot.states import ConnectWalletStates, TradeReviewStates
from bot.database.db import (
    insert_wallet,
    get_user_wallets,
    remove_wallet,
    toggle_auto_tracking,
    set_user_timezone,
    get_pending_trades,
    get_pending_trade_by_id,
    get_pending_dca_by_id,
    delete_pending_dca,
    update_pending_trade_status,
    delete_pending_trade,
    get_open_trade_for_token,
    get_ignored_pendings_for_token,
    get_closed_trades_unreviewed,
    get_closed_trade_unreviewed_by_id,
    resolve_closed_trade_unreviewed,
    insert_trade,
)
from bot.services.wallet_monitor import (
    get_mock_detected_trade,
    get_pending_detected_event,
    set_pending_detected_event,
    DetectedTradeEvent,
)
from bot.services.dexscreener import TokenData

router = Router()

SETTINGS_TITLE = """⚙️ Settings

Manage your wallet tracking and automation features.

• 🔗 Connect Wallet
Link your wallet so the bot can detect your trades automatically.

• 👛 Connected Wallets
View or remove wallets currently monitored by the bot.

• 🤖 Auto Trade Detection
Enable or disable automatic trade tracking.

Choose an action below."""
CONNECT_WALLET_PROMPT = """Paste your wallet address to enable automatic trade tracking.

Supported networks:
• Solana
• BNB Chain
• Base"""
INVALID_ADDRESS = "Invalid address format for the selected network. Try again or /cancel."
WALLET_SAVED = "✅ Wallet saved. Auto trade detection is enabled for this wallet."
CONNECTED_WALLETS_EMPTY = "No wallets connected. Use 🔗 Connect Wallet to add one."
AUTO_DETECTION_TEXT = (
    "🤖 Auto Trade Detection\n\n"
    "BehaveBot tracks your wallet automatically.\n\n"
    "All unreviewed trades will appear in:\n\n"
    "📥 Pending\n\n"
    "Review them anytime:\n"
    "• Record → save your trade\n"
    "• Ignore → skip it\n\n"
    "Trades will be cleared automatically after 24 hours."
)
TRADE_DETECTED_TEMPLATE = ""

_EVM_PATTERN = re.compile(r"^0x[a-fA-F0-9]{40}$")
_SOLANA_PATTERN = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def _validate_address(address: str, network: str) -> bool:
    a = (address or "").strip()
    if network == "Solana":
        return bool(_SOLANA_PATTERN.match(a))
    if network in ("BNB Chain", "Base"):
        return bool(_EVM_PATTERN.match(a)) or (len(a) == 40 and _EVM_PATTERN.match("0x" + a))
    return False


async def _token_data_from_event(event: DetectedTradeEvent) -> TokenData:
    """Build TokenData from a detected trade; fetch price/mcap from DexScreener when possible."""
    price = event.price_usd or 0.0
    mcap = event.mcap
    liquidity = event.liquidity
    if not price and event.token_address and len(event.token_address) >= 10:
        from bot.services import fetch_token_data
        td = await fetch_token_data(event.token_address)
        if td:
            price = td.price or 0.0
            mcap = td.mcap
            liquidity = td.liquidity
    return TokenData(
        token_address=event.token_address,
        name=event.token_name,
        symbol=event.token_symbol,
        chain=event.network,
        price=price,
        mcap=mcap,
        liquidity=liquidity,
        volume_1h=None,
        age=None,
        chart_url=None,
        dex_name=None,
        from_detection=True,
        tx_timestamp=event.block_timestamp,
        open_quantity=event.amount,
        network=event.network,
    )


# --- Settings menu (Reply button + callback) ---


@router.message(F.text == "⚙️ Settings")
async def menu_settings(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_internal_screen(message, SETTINGS_TITLE, kb_settings_menu())


@router.callback_query(F.data == "settings_menu")
async def cb_settings_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(SETTINGS_TITLE, reply_markup=kb_settings_menu())


@router.callback_query(F.data == "settings_timezone")
async def cb_settings_timezone(callback: CallbackQuery) -> None:
    from bot.database.db import get_user_timezone_offset
    await callback.answer()
    current_offset = await get_user_timezone_offset(callback.from_user.id)
    await callback.message.edit_text(
        "🌐 Select your timezone",
        reply_markup=kb_timezone_select(current_offset=current_offset),
    )


@router.callback_query(F.data.startswith("tz_set:"))
async def cb_tz_set(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        offset = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.message.edit_text("Invalid timezone.", reply_markup=kb_back_to_settings())
        return
    user_id = callback.from_user.id
    await set_user_timezone(user_id, offset)
    label = next((lbl for off, lbl in TIMEZONE_OPTIONS if off == offset), f"UTC{offset:+d}")
    await callback.message.edit_text(
        "✅ Timezone updated\n\nCurrent timezone:\n" + label,
        reply_markup=kb_back_to_settings(),
    )


# --- Connect Wallet flow ---


@router.callback_query(F.data == "settings_connect_wallet")
async def connect_wallet_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ConnectWalletStates.address)
    await callback.message.edit_text(
        CONNECT_WALLET_PROMPT,
        reply_markup=kb_back_to_settings(),
    )


@router.message(ConnectWalletStates.address, F.text)
async def connect_wallet_address(message: Message, state: FSMContext) -> None:
    address = (message.text or "").strip()
    if not address:
        return
    if address.startswith("/"):
        return
    await state.update_data(wallet_address=address)
    await state.set_state(ConnectWalletStates.network)
    await message.answer("Choose network:", reply_markup=kb_connect_wallet_networks())


@router.callback_query(F.data.startswith("wallet_network:"), ConnectWalletStates.network)
async def connect_wallet_network(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    network = callback.data.replace("wallet_network:", "", 1)
    data = await state.get_data()
    address = (data.get("wallet_address") or "").strip()
    if not address:
        await callback.message.edit_text("Address missing. Start over from Settings.", reply_markup=kb_back_to_settings())
        await state.clear()
        return
    if not _validate_address(address, network):
        await callback.message.edit_text(INVALID_ADDRESS, reply_markup=kb_back_to_settings())
        await state.clear()
        return
    await insert_wallet(callback.from_user.id, address, network)
    await state.clear()
    await callback.message.edit_text(WALLET_SAVED, reply_markup=kb_back_to_settings())


# --- Connected Wallets ---


@router.callback_query(F.data == "settings_connected_wallets")
async def connected_wallets_list(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    wallets = await get_user_wallets(callback.from_user.id)
    if not wallets:
        await callback.message.edit_text(CONNECTED_WALLETS_EMPTY, reply_markup=kb_back_to_settings())
        return
    lines = ["Connected Wallets\n"]
    for i, w in enumerate(wallets, 1):
        _, _, address, network, _, _ = w
        short = (address[:6] + "..." + address[-4:]) if len(address) > 14 else address
        lines.append(f"{i}. {short} ({network})")
    text = "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=kb_connected_wallets(wallets))


@router.callback_query(F.data.startswith("wallet_detail:"))
async def wallet_detail(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    try:
        wallet_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return
    wallets = await get_user_wallets(callback.from_user.id)
    w = next((x for x in wallets if x[0] == wallet_id), None)
    if not w:
        await callback.message.edit_text("Wallet not found.", reply_markup=kb_back_to_settings())
        return
    _, _, address, network, auto_tracking_enabled, _ = w
    text = f"Wallet\n\n{address}\nNetwork: {network}\nAuto tracking: {'On' if auto_tracking_enabled else 'Off'}"
    await callback.message.edit_text(text, reply_markup=kb_wallet_detail(wallet_id, bool(auto_tracking_enabled)))


@router.callback_query(F.data.startswith("wallet_toggle:"))
async def wallet_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    try:
        wallet_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return
    new_state = await toggle_auto_tracking(wallet_id, callback.from_user.id)
    wallets = await get_user_wallets(callback.from_user.id)
    w = next((x for x in wallets if x[0] == wallet_id), None)
    if w:
        _, _, address, network, _, _ = w
        text = f"Wallet\n\n{address}\nNetwork: {network}\nAuto tracking: {'On' if new_state else 'Off'}"
        await callback.message.edit_text(text, reply_markup=kb_wallet_detail(wallet_id, new_state))


@router.callback_query(F.data.startswith("wallet_remove:"))
async def wallet_remove(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    try:
        wallet_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return
    await remove_wallet(wallet_id, callback.from_user.id)
    wallets = await get_user_wallets(callback.from_user.id)
    if not wallets:
        await callback.message.edit_text(CONNECTED_WALLETS_EMPTY, reply_markup=kb_back_to_settings())
        return
    lines = ["Connected Wallets\n"]
    for i, w in enumerate(wallets, 1):
        _, _, address, network, _, _ = w
        short = (address[:6] + "..." + address[-4:]) if len(address) > 14 else address
        lines.append(f"{i}. {short} ({network})")
    await callback.message.edit_text("\n".join(lines), reply_markup=kb_connected_wallets(wallets))


# --- Auto Trade Detection ---


@router.callback_query(F.data == "settings_auto_detection")
async def auto_detection_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.edit_text(
        AUTO_DETECTION_TEXT,
        reply_markup=kb_auto_detection_menu(),
    )


TRADE_CENTER_TEXT = ""


@router.callback_query(F.data == "trade_center")
async def trade_center_menu(callback: CallbackQuery, state: FSMContext) -> None:
    # Trade Center is deprecated in the ultra-simple Pending system.
    # Keep callback for backward-compat deep links; redirect to Pending.
    await callback.answer()
    await pending_trades_list_handler(callback, state)


@router.callback_query(F.data == "trade_review_new")
async def trade_review_new_list(callback: CallbackQuery, state: FSMContext) -> None:
    # Deprecated — redirect to Pending.
    await callback.answer()
    await pending_trades_list_handler(callback, state)


@router.callback_query(F.data.startswith("trade_review_detail:"))
async def trade_review_detail(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        row_id = int(callback.data.split(":")[1])
    except Exception:
        return
    it = await get_closed_trade_unreviewed_by_id(callback.from_user.id, row_id)
    if not it or it.get("status") != "pending":
        await callback.message.edit_text(
            "This trade is no longer pending review.",
            reply_markup=kb_auto_detection_menu(),
        )
        return
    sym = it.get("symbol") or "Unknown"
    net = it.get("network") or ""
    buy_amt = it.get("buy_amount")
    buy_val = it.get("buy_value_usd")
    sell_amt = it.get("sell_amount")
    sell_val = it.get("sell_value_usd")
    if buy_amt is not None or sell_amt is not None:
        buy_part = f"📥 Buy: {buy_amt if buy_amt is not None else '—'}" + (f" (${buy_val:.2f})" if buy_val is not None else "") + "\n"
        sell_part = f"📤 Sell: {sell_amt if sell_amt is not None else '—'}" + (f" (${sell_val:.2f})" if sell_val is not None else "") + "\n"
        body = buy_part + sell_part
    else:
        amt = it.get("amount")
        val = it.get("value_usd")
        body = f"Amount: {amt if amt is not None else '—'}\n" + (f"Value: ${val:.2f}\n" if val is not None else "")
    text = (
        "📥 Pending Trade\n\n"
        f"🪙 Token: {sym}\n"
        f"🌐 Network: {net}\n\n"
        f"{body}\n"
        "Choose an action:"
    )
    await callback.message.edit_text(text, reply_markup=kb_trade_review_actions(row_id))


@router.callback_query(F.data.startswith("trade_review_ignore:"))
async def trade_review_ignore(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    try:
        row_id = int(callback.data.split(":")[1])
    except Exception:
        return
    await resolve_closed_trade_unreviewed(callback.from_user.id, row_id, "ignored")
    await state.clear()
    await callback.message.edit_text("Ignored.", reply_markup=kb_auto_detection_menu())


@router.callback_query(F.data.startswith("trade_review_record:"))
async def trade_review_record_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    try:
        row_id = int(callback.data.split(":")[1])
    except Exception:
        return
    it = await get_closed_trade_unreviewed_by_id(callback.from_user.id, row_id)
    if not it or it.get("status") != "pending":
        return
    await state.clear()
    await state.update_data(trade_review_row_id=row_id)
    await state.set_state(TradeReviewStates.why_open)
    await callback.message.edit_text("1) Why did you open this trade?")


@router.message(TradeReviewStates.why_open, F.text)
async def trade_review_why_open(message: Message, state: FSMContext) -> None:
    await state.update_data(trade_review_why_open=message.text.strip())
    await state.set_state(TradeReviewStates.strategy)
    await message.answer("2) What was your strategy?")


@router.message(TradeReviewStates.strategy, F.text)
async def trade_review_strategy(message: Message, state: FSMContext) -> None:
    await state.update_data(trade_review_strategy=(message.text or "").strip())
    await state.set_state(TradeReviewStates.emotion)
    await message.answer("What was your emotion when opening this trade?", reply_markup=kb_trade_review_emotions())


@router.callback_query(F.data.startswith("tr_emotion:"), TradeReviewStates.emotion)
async def trade_review_emotion_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    emo = callback.data.split(":", 1)[1]
    if emo == "Other":
        await state.set_state(TradeReviewStates.emotion_note)
        await callback.message.edit_text("Please write your emotion:")
        return
    await state.update_data(trade_review_emotion=emo)
    await state.set_state(TradeReviewStates.notes)
    await callback.message.edit_text("Any notes? (optional)\nSend '-' to skip.")


@router.message(TradeReviewStates.emotion_note, F.text)
async def trade_review_emotion_note_msg(message: Message, state: FSMContext) -> None:
    await state.update_data(trade_review_emotion="Other", trade_review_emotion_note=(message.text or "").strip())
    await state.set_state(TradeReviewStates.notes)
    await message.answer("Any notes? (optional)\nSend '-' to skip.")


@router.message(TradeReviewStates.notes, F.text)
async def trade_review_notes_msg(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    row_id = int(data.get("trade_review_row_id") or 0)
    it = await get_closed_trade_unreviewed_by_id(message.from_user.id, row_id)
    if not it or it.get("status") != "pending":
        await state.clear()
        return

    why_open = (data.get("trade_review_why_open") or "").strip()
    strategy = (data.get("trade_review_strategy") or "").strip()
    notes = (message.text or "").strip()
    if notes == "-":
        notes = ""

    reason_note = f"Why opened:\n{why_open}\n\nStrategy:\n{strategy}".strip()
    if notes:
        reason_note = (reason_note + f"\n\nNotes:\n{notes}").strip()

    from datetime import datetime
    from bot.database.models import Trade
    # Create trade from paired BUY+SELL detection (closed trade) — then immediately ask close questions.
    try:
        open_dt = datetime.fromisoformat(str(it.get("buy_timestamp") or "").replace("Z", ""))
    except Exception:
        open_dt = datetime.utcnow()
    try:
        close_dt = datetime.fromisoformat(str(it.get("sell_timestamp") or "").replace("Z", ""))
    except Exception:
        close_dt = datetime.utcnow()
    token_addr_raw = it.get("token_address") or ""
    token_addr = token_addr_raw.lower() if str(token_addr_raw).startswith("0x") else token_addr_raw
    sym = (it.get("symbol") or "Unknown").strip()
    open_price = float(it.get("buy_price_usd") or 0.0)
    close_price = float(it.get("sell_price_usd") or 0.0)
    mcap_open = it.get("buy_mcap")
    mcap_close = it.get("sell_mcap")
    qty = it.get("buy_amount")

    trade = Trade(
        trade_id=None,
        user_id=message.from_user.id,
        token_address=token_addr,
        token_symbol=sym,
        token_name=None,
        open_time=open_dt,
        close_time=close_dt,
        open_price=open_price,
        close_price=close_price,
        mcap_open=mcap_open,
        mcap_close=mcap_close,
        duration=max(0.0, (close_dt - open_dt).total_seconds()),
        emotion_open=(data.get("trade_review_emotion") or ""),
        emotion_open_note=data.get("trade_review_emotion_note"),
        reason_open="Other",
        reason_open_note=reason_note,
        token_category="",
        token_category_note=None,
        risk_level="",
        emotion_close="",
        emotion_close_note=None,
        reason_close="",
        reason_close_note=None,
        discipline="",
        status="valid",
        open_quantity=qty,
        remaining_quantity=0.0,
        trade_mode="auto",
        network=it.get("network"),
        open_value_usd=it.get("buy_value_usd"),
    )
    trade_id = await insert_trade(trade)
    await resolve_closed_trade_unreviewed(message.from_user.id, row_id, "recorded")
    await state.clear()

    # Immediately continue to CLOSE POSITION questions (auto-close flow).
    from bot.handlers.close_position import Q5
    from bot.keyboards import kb_emotion_close_auto
    await message.answer(Q5, reply_markup=kb_emotion_close_auto(trade_id))


# --- Pending Trades menu (PART 1) ---


@router.callback_query(F.data == "pending_trades_list")
async def pending_trades_list_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    from datetime import datetime

    open_items = await get_pending_trades(callback.from_user.id)
    closed_items = await get_closed_trades_unreviewed(callback.from_user.id, limit=50)

    def _ts(s: str | None) -> datetime:
        try:
            return datetime.fromisoformat(str(s or "").replace("Z", ""))
        except Exception:
            return datetime.min

    merged: list[tuple[datetime, str, str]] = []
    for pt in open_items:
        merged.append((_ts(getattr(pt, "timestamp", None)), f"{pt.symbol} ({pt.network})", f"pending_detail:{pt.id}"))
    for it in closed_items:
        ts = it.get("sell_timestamp") or it.get("timestamp") or it.get("buy_timestamp")
        merged.append((_ts(ts), f"{it.get('symbol', '?')} ({it.get('network', '')})", f"trade_review_detail:{it['id']}"))

    merged.sort(key=lambda x: x[0], reverse=True)
    items = [(label, cb) for _, label, cb in merged]

    if not items:
        await callback.message.edit_text(
            "📥 Pending\n\nNo unreviewed trades right now.",
            reply_markup=kb_auto_detection_menu(),
        )
        return

    await callback.message.edit_text(
        f"📥 Pending\n\n{len(items)} unreviewed trade(s). Tap one to Record or Ignore:",
        reply_markup=kb_pending_mixed_list(items),
    )


def _format_pending_value(amount, price=None):
    if amount is None and price is None:
        return "—"
    if amount is not None and price is not None:
        v = float(amount) * float(price)
        return f"${v:,.0f}" if v >= 100 else f"${v:.2f}"
    return "—"


def _format_usd_display(value):
    if value is None:
        return "—"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.2f}K"
    return f"${value:.4f}" if value < 1 else f"${value:.2f}"


@router.callback_query(F.data.startswith("pending_detail:"))
async def pending_detail_handler(callback: CallbackQuery, state: FSMContext) -> None:
    from bot.utils.formatters import get_network_icon, format_user_time, format_compact_number
    await callback.answer()
    try:
        pending_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return
    pt = await get_pending_trade_by_id(pending_id)
    if not pt or pt.status != "pending":
        await callback.message.edit_text(
            "This trade is no longer pending.",
            reply_markup=kb_auto_detection_menu(),
        )
        return
    amount_str = f"{pt.amount:.4g}" if pt.amount is not None else "—"
    price_val = None
    mcap_val = getattr(pt, "mcap", None)
    if pt.token_address and len(str(pt.token_address)) >= 10:
        from bot.services import fetch_token_data
        td = await fetch_token_data(pt.token_address)
        if td:
            price_val = getattr(td, "price", None)
            if mcap_val is None:
                mcap_val = getattr(td, "mcap", None)
    snapshot_value = getattr(pt, "value_usd", None)
    value_str = _format_usd_display(snapshot_value)
    now_str = None
    now_pnl = None
    if price_val is not None and pt.amount is not None:
        now_val = float(pt.amount) * float(price_val)
        now_str = _format_usd_display(now_val)
        if snapshot_value is not None and snapshot_value > 0:
            now_pnl = ((now_val - snapshot_value) / snapshot_value) * 100.0
    network_label = get_network_icon(pt.network or "")
    time_display = await format_user_time(callback.from_user.id, pt.timestamp or "")
    sym_label = f"${pt.symbol}" if pt.symbol else "Unknown"
    contract = (pt.token_address or "—").strip()
    lines = [
        "📥 Pending Trade",
        "",
        f"🪙 Token: {sym_label}",
        f"🌐 Chain: {network_label}",
        "",
        f"📄 Contract\n<code>{contract}</code>\n(Tap for copy address)",
        "",
        f"Detected: {time_display}",
        f"Amount: {amount_str}",
        "",
        f"Value: {value_str}",
    ]
    if now_str is not None and now_pnl is not None:
        sign = f"{now_pnl:+.1f}%"
        lines.append(f"Now: {now_str} ({sign})")
    elif now_str is not None:
        lines.append(f"Now: {now_str}")
    if price_val is not None:
        lines.append(f"Price: ${price_val:.6f}" if price_val < 1 else f"Price: ${price_val:.2f}")
    if mcap_val is not None:
        lines.append(f"Market Cap: ${format_compact_number(mcap_val)}")
    lines.extend(["", "Choose an action:"])
    text = "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=kb_pending_trade_actions(pending_id))


@router.callback_query(F.data.startswith("pending_record:"))
async def pending_record_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Record Trade from pending queue — go straight to behavioral questions (no token snapshot).
    If user already has an open trade for this token, add pending amount as DCA instead of creating a new trade."""
    from bot.services import set_pending_token, fetch_token_data
    from bot.handlers.open_position import run_open_position_flow
    from bot.services.wallet_monitor import _apply_dca
    await callback.answer()
    try:
        pending_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return

    pt = await get_pending_trade_by_id(pending_id)
    if not pt:
        event = get_pending_detected_event(callback.from_user.id) or get_mock_detected_trade()
    else:
        if pt.status not in ("pending", "inbox"):
            await callback.message.edit_text("This trade has already been resolved.", reply_markup=kb_back_to_menu())
            return
        # If user already has an open position for this token, treat as DCA (never show "already resolved" for this case)
        token_key = (pt.token_address or "").strip().lower() if (pt.token_address or "").strip().startswith("0x") else (pt.token_address or "").strip()
        open_trade = await get_open_trade_for_token(callback.from_user.id, token_key, pt.network or None)
        if open_trade:
            price = 0.0
            if pt.token_address:
                td_fetch = await fetch_token_data(pt.token_address)
                if td_fetch and getattr(td_fetch, "price", None):
                    price = float(td_fetch.price)
            add_value = (pt.amount * price) if price else None
            ok = await _apply_dca(
                callback.from_user.id, open_trade.trade_id, pt.amount or 0, price, add_value,
                mcap=getattr(pt, "mcap", None),
            )
            await update_pending_trade_status(pending_id, "recorded")
            if ok:
                await callback.message.edit_text(
                    "✅ Added to position. The pending amount was added to your existing position.",
                    reply_markup=kb_back_to_menu(),
                )
                from bot.handlers.premium import maybe_send_risk_alerts
                await maybe_send_risk_alerts(callback.bot, callback.from_user.id)
            else:
                await callback.message.edit_text(
                    "Could not add to position (trade may be closed). You can record it as a new trade from the list.",
                    reply_markup=kb_back_to_menu(),
                )
            return
        await update_pending_trade_status(pending_id, "recorded")
        if pt.status == "inbox":
            from bot.services.wallet_monitor import cancel_pending_timeout
            cancel_pending_timeout(pending_id)
        event = get_pending_detected_event(callback.from_user.id)
        if not event or event.tx_hash != pt.tx_hash:
            event = DetectedTradeEvent(
                token_symbol=pt.symbol,
                token_name=pt.symbol,
                token_address=pt.token_address,
                network=pt.network,
                direction="OPEN",
                tx_hash=pt.tx_hash,
                amount=pt.amount,
            )

    # Merge ignored pendings for same token (within 120 min) so entry = recorded + ignored
    td = await _token_data_from_event(event)
    token_key = (pt.token_address or "").strip().lower() if (pt.token_address or "").strip().startswith("0x") else (pt.token_address or "").strip()
    ignored_list = await get_ignored_pendings_for_token(callback.from_user.id, token_key, pt.network or "", within_minutes=120)
    if ignored_list:
        total_amount = (pt.amount or 0) + sum((getattr(i, "amount", None) or 0) for i in ignored_list)
        price = getattr(td, "price", None) or 0.0
        recorded_value = getattr(pt, "value_usd", None)
        if recorded_value is None and (pt.amount or 0) and price:
            recorded_value = (pt.amount or 0) * price
        else:
            recorded_value = recorded_value or 0.0
        ignored_value = sum(
            (getattr(i, "value_usd", None) or (getattr(i, "amount", None) or 0) * price)
            for i in ignored_list
        )
        total_value = recorded_value + ignored_value
        td.open_quantity = total_amount
        td.open_value_usd = total_value if total_value else None
        for i in ignored_list:
            if getattr(i, "id", None):
                await update_pending_trade_status(i.id, "merged")
    else:
        if pt and (pt.amount or 0):
            td.open_quantity = pt.amount
            if getattr(pt, "value_usd", None) is not None:
                td.open_value_usd = pt.value_usd

    set_pending_token(callback.from_user.id, td)
    await state.clear()
    started = await run_open_position_flow(callback, state)
    if not started:
        from bot.handlers.token import _fmt_token_msg
        await callback.message.edit_text(
            _fmt_token_msg(td) + "\n\nTap Open Position to start behavior tracking.",
            reply_markup=kb_token_preview(),
        )


@router.callback_query(F.data.startswith("pending_ignore:"))
async def pending_ignore_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Ignore from pending queue."""
    await callback.answer()
    try:
        pending_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return
    pt = await get_pending_trade_by_id(pending_id)
    if pt:
        await delete_pending_trade(pending_id)
    await state.clear()
    await callback.message.edit_text("Ignored.", reply_markup=kb_auto_detection_menu())


@router.callback_query(F.data.startswith("dca_confirm:"))
async def dca_confirm_handler(callback: CallbackQuery) -> None:
    """Add DCA to existing position."""
    from bot.services.wallet_monitor import _apply_dca
    await callback.answer()
    try:
        pending_dca_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return
    row = await get_pending_dca_by_id(pending_dca_id)
    if not row:
        await callback.message.edit_text("This DCA was already handled.", reply_markup=kb_back_to_menu())
        return
    user_id, trade_id, amount, price, value_usd = row
    if user_id != callback.from_user.id:
        return
    ok = await _apply_dca(user_id, trade_id, amount, price, value_usd)
    await delete_pending_dca(pending_dca_id)
    if ok:
        await callback.message.edit_text(
            "✅ Position updated. The additional buy was added to your existing position.",
            reply_markup=kb_back_to_menu(),
        )
    else:
        await callback.message.edit_text("Could not update position (trade may be closed).", reply_markup=kb_back_to_menu())


@router.callback_query(F.data.startswith("dca_ignore:"))
async def dca_ignore_handler(callback: CallbackQuery) -> None:
    """Ignore DCA add."""
    await callback.answer()
    try:
        pending_dca_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return
    row = await get_pending_dca_by_id(pending_dca_id)
    if row and row[0] == callback.from_user.id:
        await delete_pending_dca(pending_dca_id)
    await callback.message.edit_text("Ignored.", reply_markup=kb_back_to_menu())


# --- Legacy Record Trade / Ignore (detected trade — backward compat) ---


@router.callback_query(F.data == "detected_record_trade")
async def detected_record_trade(callback: CallbackQuery, state: FSMContext) -> None:
    """Record Trade from detection message — go straight to behavioral questions (no token snapshot)."""
    from bot.services import set_pending_token
    from bot.handlers.open_position import run_open_position_flow
    from bot.handlers.token import _fmt_token_msg
    await callback.answer()
    event = get_pending_detected_event(callback.from_user.id) or get_mock_detected_trade()
    td = await _token_data_from_event(event)
    set_pending_token(callback.from_user.id, td)
    await state.clear()
    started = await run_open_position_flow(callback, state)
    if not started:
        await callback.message.edit_text(
            _fmt_token_msg(td) + "\n\nTap Open Position to start behavior tracking.",
            reply_markup=kb_token_preview(),
        )


@router.callback_query(F.data == "detected_ignore")
async def detected_ignore(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.edit_text("Ignored.", reply_markup=kb_back_to_menu())


@router.callback_query(F.data.startswith("detected_move_pending:"))
async def detected_move_pending(callback: CallbackQuery, state: FSMContext) -> None:
    """User explicitly moved the detection into 📥 Pending."""
    await callback.answer()
    try:
        pending_id = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        return
    pt = await get_pending_trade_by_id(pending_id)
    if pt and pt.status == "inbox":
        await update_pending_trade_status(pending_id, "pending")
        from bot.services.wallet_monitor import cancel_pending_timeout
        cancel_pending_timeout(pending_id)
    await state.clear()
    await callback.message.edit_text(
        "Moved to 📥 Pending.\n\nYou can review it anytime from Auto Trade Detection → Pending.",
        reply_markup=kb_back_to_menu(),
    )


@router.callback_query(F.data.startswith("detected_delete:"))
async def detected_delete(callback: CallbackQuery, state: FSMContext) -> None:
    """Ignore = hard delete (no Pending, no storage)."""
    await callback.answer()
    try:
        pending_id = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        return
    pt = await get_pending_trade_by_id(pending_id)
    if pt:
        await delete_pending_trade(pending_id)
        from bot.services.wallet_monitor import cancel_pending_timeout
        cancel_pending_timeout(pending_id)
    await state.clear()
    await callback.message.edit_text("Ignored. Deleted permanently.", reply_markup=kb_back_to_menu())
