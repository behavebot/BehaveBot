"""
Wallet Auto Trade Detection — poll every POLL_INTERVAL_SECONDS.

Transaction classification:
  DEX_SWAP         – Known DEX router interaction → auto trade detection.
  WALLET_TRANSFER  – Wallet-to-wallet send, no router → ignored.
  UNKNOWN_SOURCE   – Tokens received without router (exchange / bridge / OTC) → ask user.
  TOKEN_AIRDROP    – Tokens received with no input value, no swap → ignored.

Detection flow:
1. Poll RPC for new signatures/logs.
2. Classify each event into one of the four types above.
3. DEX_SWAP   → OPEN or CLOSE logic (DCA, partial close, trade_exits, pending queue).
4. UNKNOWN_SOURCE → Insert into pending_trades, send prompt ONCE, let user decide.
5. WALLET_TRANSFER / TOKEN_AIRDROP → log and skip (no trade accounting impact).
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from bot.database.db import (
    get_all_tracked_wallets,
    update_last_signature,
    get_open_trade_for_token,
    update_trade_remaining_quantity,
    update_trade_close,
    insert_pending_trade,
    pending_trade_exists,
    get_pending_trade_by_token,
    update_pending_trade_merge,
    insert_trade_exit,
    update_trade_open_quantity,
    get_trade_exits,
    cleanup_pending_trades_older_than_hours,
)
from bot.database.models import PendingTrade, TradeExit
from bot.services.token_filters import (
    is_stablecoin,
    is_native_token,
    is_dex_router,
    is_solana_dex_program,
    classify_evm_tx,
    TX_DEX_SWAP,
    TX_WALLET_TRANSFER,
    TX_UNKNOWN_SOURCE,
    TX_TOKEN_AIRDROP,
)
from bot.services import rpc_clients

logger = logging.getLogger(__name__)

# How long we wait for user to react to the detection prompt
# before moving it into 📥 Pending automatically.
DETECTION_RESPONSE_TIMEOUT_SECONDS = 300  # 5 minutes

_pending_timeout_tasks: dict[int, asyncio.Task] = {}
BASE_ASSETS = {"USDC", "USDT", "BNB", "ETH", "SOL"}
EPS_CLOSE_QTY = 1e-9
STABLE_TOKEN_ADDRESSES = {
    "BNB Chain": {
        "0x55d398326f99059ff775485246999027b3197955",  # USDT
        "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d",  # USDC
    },
    "Base": {
        "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",  # USDC
        "0xfde4c96c8593536e31f229ea8f37b2adab4bbd7",  # USDT
    },
    "Solana": {
        "es9vMFrzaCERmJfrF4H2P9wzW4f2xQ8g9fSx8f6f4eH",   # USDT (legacy mint)
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    },
}

def cancel_pending_timeout(pending_id: int) -> None:
    t = _pending_timeout_tasks.pop(pending_id, None)
    if t and not t.done():
        t.cancel()

POLL_INTERVAL_SECONDS = 5

_pending_detected_events: dict[int, "DetectedTradeEvent"] = {}


@dataclass
class DetectedTradeEvent:
    token_symbol: str
    token_name: str
    token_address: str
    network: str
    direction: str  # "OPEN" | "CLOSE"
    tx_hash: str = ""
    block_timestamp: Optional[int] = None
    amount: Optional[float] = None
    tx_type: str = TX_DEX_SWAP
    price_usd: Optional[float] = None
    liquidity: Optional[float] = None
    mcap: Optional[float] = None
    volume_24h: Optional[float] = None
    value_usd: Optional[float] = None
    is_valid_buy: bool = True
    pair_is_base_asset: bool = False


def resolve_trade_action(event: DetectedTradeEvent, open_trade) -> str:
    if open_trade:
        return "DCA"
    if getattr(event, "is_valid_buy", False):
        return "PROMPT"
    return "IGNORE"


def _is_base_asset_symbol(symbol: str, network: str = "") -> bool:
    s = (symbol or "").strip().upper()
    if not s:
        return False
    if s in BASE_ASSETS:
        return True
    return is_stablecoin(s) or is_native_token(s)


def _is_stable_by_address(token_address: str, network: str = "") -> bool:
    addr = (token_address or "").strip()
    if not addr:
        return False
    network_map = STABLE_TOKEN_ADDRESSES.get(network or "", set())
    if addr.startswith("0x"):
        return addr.lower() in network_map
    return addr in network_map


def is_base_asset_pair(token_in: str, token_out: str, network: str = "") -> bool:
    return _is_base_asset_symbol(token_in, network) and _is_base_asset_symbol(token_out, network)


def should_ignore_trade(event: DetectedTradeEvent) -> bool:
    """Deterministic ignore filter for stable/native-only rotations."""
    if getattr(event, "pair_is_base_asset", False):
        return True
    if _is_base_asset_symbol(event.token_symbol or "", event.network or ""):
        return True
    # Unknown symbol fallback: stable token address should still be ignored.
    if _is_stable_by_address(event.token_address or "", event.network or ""):
        return True
    return False


def _log_buy_event_decision(
    event: DetectedTradeEvent,
    *,
    classification: str,
    direction: str,
    is_dca_applied: bool,
    is_filtered: bool,
    filter_reason: str,
    pending_inserted: bool,
    duplicate_detected: bool,
) -> None:
    logger.info(
        "[BUY_DECISION] tx=%s token=%s classification=%s direction=%s filtered=%s filter_reason=%s dca=%s pending_inserted=%s duplicate=%s",
        (event.tx_hash or "")[:16],
        event.token_symbol,
        classification,
        direction,
        is_filtered,
        filter_reason,
        is_dca_applied,
        pending_inserted,
        duplicate_detected,
    )


async def _maybe_auto_dca_existing_position(bot, user_id: int, event: DetectedTradeEvent) -> bool:
    """If an open trade exists for token+network and event is BUY-like, apply DCA and skip prompts."""
    if (event.direction or "").upper() != "OPEN":
        return False
    if not getattr(event, "is_valid_buy", True):
        return False
    symbol = (event.token_symbol or "").strip()
    if should_ignore_trade(event):
        return False
    token_key = (event.token_address or "").lower() if (event.token_address or "").startswith("0x") else (event.token_address or "")
    if not token_key:
        return False
    existing = await get_open_trade_for_token(user_id, token_key, event.network or None)
    if not existing:
        return False
    await _enrich_event_market_data(event)
    new_qty = event.amount or 0.0
    if new_qty <= 0:
        return False
    new_price = event.price_usd or existing.open_price or 0.0
    new_value = new_qty * new_price
    ok = await _apply_dca(user_id, existing.trade_id, new_qty, new_price, new_value, mcap=event.mcap)
    if ok:
        from bot.keyboards import kb_my_position
        try:
            await bot.send_message(
                chat_id=user_id,
                text="📈 DCA detected — added to your position.",
                reply_markup=kb_my_position(existing.trade_id),
            )
        except Exception as e:
            logger.warning("Could not send auto-DCA message to user %s: %s", user_id, e)
    return ok


def set_pending_detected_event(user_id: int, event: DetectedTradeEvent) -> None:
    _pending_detected_events[user_id] = event


def get_pending_detected_event(user_id: int) -> Optional[DetectedTradeEvent]:
    return _pending_detected_events.pop(user_id, None)


def peek_pending_detected_event(user_id: int) -> Optional[DetectedTradeEvent]:
    return _pending_detected_events.get(user_id)


def get_mock_detected_trade() -> DetectedTradeEvent:
    return DetectedTradeEvent(
        token_symbol="PEPE",
        token_name="PEPE",
        token_address="0xdetected_pepe_base",
        network="Base",
        direction="OPEN",
        tx_hash="",
        block_timestamp=None,
        amount=None,
    )


# ---------------------------------------------------------------------------
# Main polling loop
# ---------------------------------------------------------------------------

async def poll_wallets(bot) -> None:
    logger.info("[MONITOR] Polling wallets... (interval=%ss)", POLL_INTERVAL_SECONDS)
    wallets = await get_all_tracked_wallets()
    if not wallets:
        logger.info("[MONITOR] No tracked wallets (auto_tracking_enabled=1)")
        return
    logger.info("[MONITOR] Wallets loaded: %d", len(wallets))
    for row in wallets:
        wallet_id, user_id, wallet_address, network, last_checked_signature = row
        last_sig = (last_checked_signature or "").strip() if last_checked_signature is not None else ""
        short = (wallet_address[:10] + "..." + wallet_address[-4:]) if len(wallet_address) > 18 else wallet_address
        logger.info("[MONITOR] Wallet: %s network=%s last_sig=%s", short, network, (last_sig[:16] + "..." if last_sig and len(last_sig) > 16 else last_sig or "(none)"))
        try:
            if network == "Solana":
                await _poll_solana(bot, wallet_id, user_id, wallet_address, last_sig or None)
            elif network in ("BNB Chain", "Base"):
                await _poll_evm(bot, wallet_id, user_id, wallet_address, network, last_sig or None)
        except Exception as e:
            logger.exception("Wallet monitor poll error wallet_id=%s: %s", wallet_id, e)


# ---------------------------------------------------------------------------
# Solana polling
# ---------------------------------------------------------------------------

async def _poll_solana(bot, wallet_id: int, user_id: int, address: str, last_sig: Optional[str]) -> None:
    txs = await rpc_clients.get_solana_transactions(address, limit=20)
    if not txs:
        if last_sig:
            await update_last_signature(wallet_id, "")
            logger.info("[SOL] 0 signatures returned, cursor reset")
        return
    logger.info("[SOL] Transactions returned: %d (newest first)", len(txs))
    if not last_sig or not last_sig.strip():
        new_cursor = txs[0].get("signature") or ""
        await update_last_signature(wallet_id, new_cursor)
        logger.info("[SOL] First run, cursor primed with sig=%s", (new_cursor[:20] + "..." if new_cursor else ""))
        return
    last_processed_sig: Optional[str] = None
    for tx in txs:
        sig = tx.get("signature") or ""
        if not sig:
            continue
        if sig == last_sig:
            logger.debug("[SOL] Reached cursor sig=%s, stopping", sig[:16])
            break
        logger.info("[SOL] New signature detected: %s blockTime=%s", sig[:22] + "...", tx.get("blockTime"))
        last_processed_sig = sig
        block_time = tx.get("blockTime")

        tx_type = await _classify_solana_tx(sig, address)
        logger.info("[SOL] Classified: %s sig=%s", tx_type, sig[:16])

        if tx_type == TX_TOKEN_AIRDROP:
            logger.info("[SOL] Token airdrop — ignored")
            continue
        if tx_type == TX_WALLET_TRANSFER:
            logger.info("[SOL] Wallet transfer — checking for open position exit")
            await _handle_transfer_exit(bot, user_id, sig[:16] if sig else "", "Unknown", "Solana", sig, None, None)
            continue

        event: Optional[DetectedTradeEvent] = None
        if tx_type == TX_DEX_SWAP:
            event = await _build_solana_swap_event(sig, address, block_time)
            if not event:
                continue
        else:
            event = DetectedTradeEvent(
                token_symbol="Unknown",
                token_name="Unknown",
                token_address=sig[:16] if sig else "",
                network="Solana",
                direction="OPEN",
                tx_hash=sig,
                block_timestamp=int(block_time) if block_time is not None else None,
                tx_type=tx_type,
            )

        if tx_type == TX_UNKNOWN_SOURCE:
            await _process_unknown_source(bot, user_id, event, address)
        elif event.direction == "CLOSE":
            await _handle_close_detection(bot, user_id, event, address)
        else:
            await _process_open_event(bot, user_id, event, address)
    if last_processed_sig:
        await update_last_signature(wallet_id, last_processed_sig)
        logger.info("[SOL] Cursor updated to last processed: %s", last_processed_sig[:16] + "...")


async def _classify_solana_tx(signature: str, wallet_address: str) -> str:
    """
    Classify a Solana transaction:
      - DEX_SWAP: known DEX program ID found.
      - WALLET_TRANSFER: SPL Token transfer only, wallet is the signer/sender.
      - UNKNOWN_SOURCE: tokens received, no DEX, wallet is not the signer.
      - TOKEN_AIRDROP: tokens received, no SOL spent, no DEX, likely airdrop.
    """
    tx_data = await rpc_clients.get_solana_transaction(signature)
    if not tx_data or not isinstance(tx_data, dict):
        return TX_UNKNOWN_SOURCE

    msg = tx_data.get("transaction", {}).get("message", {})
    meta = tx_data.get("meta") or {}
    account_keys = msg.get("accountKeys") or []
    instructions = msg.get("instructions") or []
    inner = meta.get("innerInstructions") or []

    program_ids: set[str] = set()
    for key in account_keys:
        if isinstance(key, dict):
            program_ids.add(key.get("pubkey", ""))
        elif isinstance(key, str):
            program_ids.add(key)
    for ix in instructions:
        pid = ix.get("programId") or ix.get("program") or ""
        if pid:
            program_ids.add(pid)
    for group in inner:
        for ix in (group.get("instructions") or []):
            pid = ix.get("programId") or ix.get("program") or ""
            if pid:
                program_ids.add(pid)

    for pid in program_ids:
        if is_solana_dex_program(pid):
            return TX_DEX_SWAP

    # No DEX program found. Determine if wallet initiated the tx.
    signer = ""
    if account_keys:
        first = account_keys[0]
        if isinstance(first, dict):
            signer = first.get("pubkey", "")
        elif isinstance(first, str):
            signer = first

    wallet_is_signer = signer.lower() == wallet_address.lower() if signer and wallet_address else False

    if wallet_is_signer:
        return TX_WALLET_TRANSFER

    # Wallet received tokens but didn't sign. Check if SOL balance changed (fee = airdrop signal).
    pre_sol = 0
    post_sol = 0
    pre_balances = meta.get("preBalances") or []
    post_balances = meta.get("postBalances") or []
    wallet_idx = None
    for i, key in enumerate(account_keys):
        pk = key.get("pubkey", "") if isinstance(key, dict) else (key if isinstance(key, str) else "")
        if pk.lower() == wallet_address.lower():
            wallet_idx = i
            break
    if wallet_idx is not None:
        pre_sol = pre_balances[wallet_idx] if wallet_idx < len(pre_balances) else 0
        post_sol = post_balances[wallet_idx] if wallet_idx < len(post_balances) else 0

    if post_sol <= pre_sol:
        return TX_TOKEN_AIRDROP

    return TX_UNKNOWN_SOURCE


async def _build_solana_swap_event(signature: str, wallet_address: str, block_time) -> Optional[DetectedTradeEvent]:
    tx_data = await rpc_clients.get_solana_transaction(signature)
    if not tx_data or not isinstance(tx_data, dict):
        return None
    meta = tx_data.get("meta") or {}

    def _owner_of(tb: dict) -> str:
        return str(tb.get("owner") or "")

    def _amount_of(tb: dict) -> float:
        ui = (tb.get("uiTokenAmount") or {})
        try:
            return float(ui.get("uiAmount") or 0.0)
        except Exception:
            return 0.0

    def _symbol_of(tb: dict) -> str:
        return str(tb.get("symbol") or tb.get("tokenSymbol") or "").strip().upper()

    pre_tokens = meta.get("preTokenBalances") or []
    post_tokens = meta.get("postTokenBalances") or []
    pre_by_mint: dict[str, dict] = {}
    post_by_mint: dict[str, dict] = {}
    for t in pre_tokens:
        mint = str(t.get("mint") or "").strip()
        if mint and _owner_of(t).lower() == wallet_address.lower():
            pre_by_mint[mint] = t
    for t in post_tokens:
        mint = str(t.get("mint") or "").strip()
        if mint and _owner_of(t).lower() == wallet_address.lower():
            post_by_mint[mint] = t

    received_non_base: list[tuple[str, str, float]] = []
    sent_non_base: list[tuple[str, str, float]] = []
    saw_base_out = False
    saw_base_in = False
    for mint in set(pre_by_mint.keys()) | set(post_by_mint.keys()):
        pre_t = pre_by_mint.get(mint)
        post_t = post_by_mint.get(mint)
        pre_amt = _amount_of(pre_t or {})
        post_amt = _amount_of(post_t or {})
        delta = post_amt - pre_amt
        sym = (_symbol_of(post_t or {}) or _symbol_of(pre_t or {}) or "UNKNOWN").upper()
        is_base = sym in BASE_ASSETS
        if delta > 0:
            if is_base:
                saw_base_in = True
            else:
                received_non_base.append((mint, sym, delta))
        elif delta < 0:
            if is_base:
                saw_base_out = True
            else:
                sent_non_base.append((mint, sym, abs(delta)))

    # Also consider native SOL movement for base in/out.
    msg = tx_data.get("transaction", {}).get("message", {})
    account_keys = msg.get("accountKeys") or []
    wallet_idx = None
    for i, key in enumerate(account_keys):
        pk = key.get("pubkey", "") if isinstance(key, dict) else (key if isinstance(key, str) else "")
        if pk.lower() == wallet_address.lower():
            wallet_idx = i
            break
    if wallet_idx is not None:
        pre_balances = meta.get("preBalances") or []
        post_balances = meta.get("postBalances") or []
        pre_sol = pre_balances[wallet_idx] if wallet_idx < len(pre_balances) else 0
        post_sol = post_balances[wallet_idx] if wallet_idx < len(post_balances) else 0
        if post_sol < pre_sol:
            saw_base_out = True
        elif post_sol > pre_sol:
            saw_base_in = True

    ts = int(block_time) if block_time is not None else None
    if received_non_base and saw_base_out:
        mint, sym, qty = received_non_base[0]
        return DetectedTradeEvent(
            token_symbol=sym or "Unknown",
            token_name=sym or "Unknown",
            token_address=mint,
            network="Solana",
            direction="OPEN",
            tx_hash=signature,
            block_timestamp=ts,
            amount=qty,
            tx_type=TX_DEX_SWAP,
            is_valid_buy=True,
        )
    if sent_non_base and saw_base_in:
        mint, sym, qty = sent_non_base[0]
        return DetectedTradeEvent(
            token_symbol=sym or "Unknown",
            token_name=sym or "Unknown",
            token_address=mint,
            network="Solana",
            direction="CLOSE",
            tx_hash=signature,
            block_timestamp=ts,
            amount=qty,
            tx_type=TX_DEX_SWAP,
            is_valid_buy=False,
        )
    return None


# ---------------------------------------------------------------------------
# EVM polling
# ---------------------------------------------------------------------------

async def _poll_evm(
    bot, wallet_id: int, user_id: int, address: str, network: str, last_sig: Optional[str]
) -> None:
    current = await rpc_clients.get_evm_block_number(network)
    if current <= 0:
        logger.warning("[EVM] %s: could not get block number", network)
        return
    from_block = max(0, current - 200)
    logger.info("[EVM] %s: latest_block=%d from_block=%d (window=200)", network, current, from_block)
    txs = await rpc_clients.get_evm_transactions(address, network, from_block, current)
    logger.info("[EVM] %s: transactions returned: %d", network, len(txs) if txs else 0)
    if not txs:
        return
    if not last_sig:
        newest_tx = txs[0].get("tx_hash") or ""
        await update_last_signature(wallet_id, newest_tx)
        logger.info("[EVM] %s: first run, cursor primed with tx=%s", network, newest_tx[:16] + "..." if newest_tx else "")
        return
    # Build per-tx summary so we can enforce strict BUY-only swaps:
    # Only prompt when (stable/native OUT) + (non-stable/non-native IN) in the same tx_hash.
    tx_summary: dict[str, dict[str, set[str]]] = {}
    for t in txs:
        h = (t.get("tx_hash") or "").strip()
        if not h:
            continue
        sym = (t.get("symbol") or "").strip().upper()
        direction = (t.get("direction") or "").strip().lower()
        s = tx_summary.setdefault(h, {"in": set(), "out": set()})
        if sym:
            if direction == "in":
                s["in"].add(sym)
            elif direction == "out":
                s["out"].add(sym)

    last_processed_tx: Optional[str] = None
    for tx in txs:
        tx_hash = tx.get("tx_hash") or ""
        if tx_hash == last_sig:
            logger.debug("[EVM] Reached cursor tx=%s, stopping", tx_hash[:16])
            break
        block_num = tx.get("blockNumber")
        symbol = (tx.get("symbol") or "").strip() or "Unknown"
        direction_raw = tx.get("direction") or "in"
        token_address = tx.get("token_address") or tx_hash
        logger.info("[EVM] Processing tx=%s block=%s symbol=%s direction=%s token=%s",
                    tx_hash[:18] + "...", block_num, symbol, direction_raw, (token_address[:10] + "..." if token_address and len(token_address) > 10 else token_address))

        last_processed_tx = tx_hash

        tx_type = await _classify_evm_tx(network, tx_hash, direction_raw)
        logger.info("[EVM] Classified: %s tx=%s symbol=%s", tx_type, tx_hash[:16], symbol)
        ins = tx_summary.get(tx_hash, {}).get("in", set())
        outs = tx_summary.get(tx_hash, {}).get("out", set())
        if ins and outs:
            # Skip stable/native-only rotations (e.g., BASE <-> USDC/USDT) before any prompt path.
            if all(_is_base_asset_symbol(x, network) for x in ins) and all(_is_base_asset_symbol(x, network) for x in outs):
                _log_buy_event_decision(
                    DetectedTradeEvent(
                        token_symbol=symbol,
                        token_name=symbol,
                        token_address=token_address,
                        network=network,
                        direction="OPEN" if direction_raw == "in" else "CLOSE",
                        tx_hash=tx_hash,
                        amount=tx.get("amount"),
                        tx_type=tx_type,
                        pair_is_base_asset=True,
                    ),
                    classification=tx_type,
                    direction="OPEN" if direction_raw == "in" else "CLOSE",
                    is_dca_applied=False,
                    is_filtered=True,
                    filter_reason="base_pair_summary",
                    pending_inserted=False,
                    duplicate_detected=False,
                )
                continue

        if tx_type == TX_TOKEN_AIRDROP:
            logger.info("[EVM] Token airdrop — ignored tx=%s", tx_hash[:16])
            continue

        if tx_type == TX_WALLET_TRANSFER:
            if direction_raw == "out" and token_address:
                logger.info("[EVM] Transfer OUT — balance-based exit check token=%s", token_address[:16])
                await _handle_transfer_exit(bot, user_id, token_address, symbol, network, tx_hash, tx.get("amount"), tx.get("blockNumber"))
                continue
            # Transfer IN: fall through to create pending and show "Token received via transfer" prompt

        event_direction = "OPEN" if direction_raw == "in" else "CLOSE"
        block_ts = None
        if block_num is not None:
            block_ts = await rpc_clients.get_evm_block_timestamp(network, block_num)

        event = DetectedTradeEvent(
            token_symbol=symbol,
            token_name=symbol,
            token_address=token_address,
            network=network,
            direction=event_direction,
            tx_hash=tx_hash,
            block_timestamp=block_ts,
            amount=tx.get("amount"),
            tx_type=tx_type,
        )
        if ins and outs and all(_is_base_asset_symbol(x, network) for x in ins) and all(_is_base_asset_symbol(x, network) for x in outs):
            event.pair_is_base_asset = True

        native_label = "BNB" if network == "BNB Chain" else "ETH" if network == "Base" else network

        if tx_type == TX_UNKNOWN_SOURCE:
            logger.info("[EVM] UNKNOWN_SOURCE: token received, no DEX — prompt user token=%s", symbol)
            await _process_unknown_source(bot, user_id, event, address)
        elif event_direction == "CLOSE":
            logger.info("[EVM] CLOSE: %s → %s token=%s amount=%s", symbol, native_label, token_address[:16], event.amount)
            await _handle_close_detection(bot, user_id, event, address)
        else:
            # Strict BUY-only filter for swaps: base asset OUT + token IN.
            if tx_type == TX_DEX_SWAP:
                in_sym = (symbol or "").strip().upper()
                if in_sym in BASE_ASSETS:
                    # Receiving stable/native is a SELL/rotation output — ignore completely.
                    _log_buy_event_decision(
                        event,
                        classification=tx_type,
                        direction=event.direction,
                        is_dca_applied=False,
                        is_filtered=True,
                        filter_reason="received_base_asset",
                        pending_inserted=False,
                        duplicate_detected=False,
                    )
                    continue
                if not (outs & BASE_ASSETS):
                    # No base asset spent → ignore.
                    _log_buy_event_decision(
                        event,
                        classification=tx_type,
                        direction=event.direction,
                        is_dca_applied=False,
                        is_filtered=True,
                        filter_reason="no_base_out_leg",
                        pending_inserted=False,
                        duplicate_detected=False,
                    )
                    continue
                event.is_valid_buy = True
            logger.info("[EVM] OPEN: %s → %s token=%s amount=%s (pending_trade)", native_label, symbol, token_address[:16], event.amount)
            await _process_open_event(bot, user_id, event, address)
    if last_processed_tx:
        await update_last_signature(wallet_id, last_processed_tx)
        logger.info("[EVM] %s: cursor updated to last processed tx=%s", network, last_processed_tx[:16] + "...")


async def _classify_evm_tx(network: str, tx_hash: str, direction: str) -> str:
    """
    Classify an EVM transaction by fetching full tx details and checking
    the 'to' address and input data against known DEX patterns.
    """
    details = await rpc_clients.get_evm_tx_details(network, tx_hash)
    if not details:
        return TX_UNKNOWN_SOURCE if direction == "in" else TX_WALLET_TRANSFER

    to_addr = (details.get("to") or "").strip()
    input_data = (details.get("input") or "").strip()

    return classify_evm_tx(to_address=to_addr, input_data=input_data, direction=direction)


# ---------------------------------------------------------------------------
# UNKNOWN_SOURCE handler — ask the user
# ---------------------------------------------------------------------------

async def _process_unknown_source(bot, user_id: int, event: DetectedTradeEvent, wallet_address: str = "") -> None:
    """
    Tokens received from unknown source (exchange withdrawal, bridge, OTC, aggregator).
    Insert into pending_trades and send prompt ONCE.
    """
    if should_ignore_trade(event):
        _log_buy_event_decision(
            event,
            classification=getattr(event, "tx_type", ""),
            direction=getattr(event, "direction", ""),
            is_dca_applied=False,
            is_filtered=True,
            filter_reason="base_asset_pair_or_symbol",
            pending_inserted=False,
            duplicate_detected=False,
        )
        return
    if await _maybe_auto_dca_existing_position(bot, user_id, event):
        _log_buy_event_decision(
            event,
            classification=getattr(event, "tx_type", ""),
            direction=getattr(event, "direction", ""),
            is_dca_applied=True,
            is_filtered=False,
            filter_reason="",
            pending_inserted=False,
            duplicate_detected=False,
        )
        return
    if event.tx_hash and await pending_trade_exists(user_id, event.tx_hash):
        logger.info("[PENDING] Duplicate skipped (unknown source): tx_hash=%s", event.tx_hash[:16])
        _log_buy_event_decision(
            event,
            classification=getattr(event, "tx_type", ""),
            direction=getattr(event, "direction", ""),
            is_dca_applied=False,
            is_filtered=False,
            filter_reason="",
            pending_inserted=False,
            duplicate_detected=True,
        )
        return

    await _enrich_event_market_data(event)

    pt = PendingTrade(
        id=None,
        user_id=user_id,
        token_address=event.token_address,
        symbol=event.token_symbol,
        network=event.network,
        amount=event.amount,
        tx_hash=event.tx_hash or "",
        timestamp=datetime.utcnow().isoformat(),
        status="inbox",
        mcap=event.mcap,
    )
    pending_id = await insert_pending_trade(pt)
    logger.info("[PENDING] Inserted id=%d user_id=%d token=%s (unknown source)", pending_id, user_id, event.token_symbol)
    _log_buy_event_decision(
        event,
        classification=getattr(event, "tx_type", ""),
        direction=getattr(event, "direction", ""),
        is_dca_applied=False,
        is_filtered=False,
        filter_reason="",
        pending_inserted=True,
        duplicate_detected=False,
    )

    set_pending_detected_event(user_id, event)
    await _send_trade_detected_message(bot, user_id, event, pending_id=pending_id)
    _schedule_pending_timeout(pending_id)


def _schedule_pending_timeout(pending_id: int) -> None:
    """After timeout, move inbox -> pending (silent)."""
    if pending_id in _pending_timeout_tasks:
        return

    async def _job():
        try:
            await asyncio.sleep(DETECTION_RESPONSE_TIMEOUT_SECONDS)
            from bot.database.db import get_pending_trade_by_id, update_pending_trade_status
            pt = await get_pending_trade_by_id(pending_id)
            if pt and pt.status == "inbox":
                await update_pending_trade_status(pending_id, "pending")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("Pending timeout job error (pending_id=%s): %s", pending_id, e)
        finally:
            _pending_timeout_tasks.pop(pending_id, None)

    _pending_timeout_tasks[pending_id] = asyncio.create_task(_job())


async def _send_unknown_source_message(bot, user_id: int, event: DetectedTradeEvent, pending_id: int) -> None:
    """Send the UNKNOWN_SOURCE prompt to the user."""
    from bot.keyboards import kb_record_trade_detected_with_id
    from bot.utils.formatters import get_network_icon

    symbol = (event.token_symbol or "Unknown").strip()
    sym_label = f"${symbol}" if symbol and symbol != "Unknown" else symbol
    amount_str = f"{event.amount:.4g}" if event.amount else "N/A"
    price_str = _format_usd(event.price_usd)
    value_str = _format_usd(event.value_usd)
    mcap_str = _format_usd(event.mcap)
    network_label = get_network_icon(event.network or "")

    text = (
        "🧠 AUTO TRADE DETECTED\n\n"
        "A token transaction was detected in your wallet.\n\n"
        f"🪙 Token: {sym_label}\n"
        f"🌐 Chain: {network_label}\n"
        f"📦 Amount: {amount_str}\n\n"
        f"💰 Value: {value_str}\n"
        f"🏷 Price: {price_str}\n"
        f"🏦 Market Cap: {mcap_str}\n\n"
        "Do you want to record this as a trade?"
    )
    try:
        await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=kb_record_trade_detected_with_id(pending_id),
        )
        logger.info("Unknown-source message sent to user_id=%s (network=%s)", user_id, event.network)
    except Exception as e:
        logger.warning("Could not send unknown-source message to user %s: %s", user_id, e)


# ---------------------------------------------------------------------------
# OPEN detection (token received — DEX_SWAP or UNKNOWN_SOURCE)
# Logic: token_received → create pending_trade (or DCA if existing auto position).
# We do not track "previous balance zero"; any receive is treated as potential OPEN.
# ---------------------------------------------------------------------------

async def _process_open_event(bot, user_id: int, event: DetectedTradeEvent, wallet_address: str = "") -> None:
    """Handle OPEN: open trade exists => forced DCA; else prompt/pending only for valid BUY."""
    token_key = (event.token_address or "").lower() if (event.token_address or "").startswith("0x") else (event.token_address or "")
    symbol = (event.token_symbol or "").strip()

    if should_ignore_trade(event):
        logger.info("[OPEN] Skipping stablecoin symbol=%s — no pending trade", symbol)
        _log_buy_event_decision(
            event,
            classification=getattr(event, "tx_type", ""),
            direction=getattr(event, "direction", ""),
            is_dca_applied=False,
            is_filtered=True,
            filter_reason="base_asset_pair_or_symbol",
            pending_inserted=False,
            duplicate_detected=False,
        )
        return

    if await _maybe_auto_dca_existing_position(bot, user_id, event):
        _log_buy_event_decision(
            event,
            classification=getattr(event, "tx_type", ""),
            direction=getattr(event, "direction", ""),
            is_dca_applied=True,
            is_filtered=False,
            filter_reason="",
            pending_inserted=False,
            duplicate_detected=False,
        )
        return
    existing = await get_open_trade_for_token(user_id, token_key, event.network or None)
    if resolve_trade_action(event, existing) == "IGNORE":
        return

    if event.tx_hash and await pending_trade_exists(user_id, event.tx_hash):
        logger.info("[OPEN] Duplicate skipped: pending_trade already exists tx_hash=%s", event.tx_hash[:16])
        _log_buy_event_decision(
            event,
            classification=getattr(event, "tx_type", ""),
            direction=getattr(event, "direction", ""),
            is_dca_applied=False,
            is_filtered=False,
            filter_reason="",
            pending_inserted=False,
            duplicate_detected=True,
        )
        return

    await _enrich_event_market_data(event)

    # Merge into existing pending for same token+network if any (only when no open trade)
    existing_pending = await get_pending_trade_by_token(user_id, token_key, event.network or "")
    if existing_pending:
        add_amt = event.amount or 0.0
        if add_amt > 0:
            add_val = event.value_usd if event.value_usd is not None else (add_amt * (event.price_usd or 0.0))
            await update_pending_trade_merge(existing_pending.id, add_amt, event.tx_hash, add_value_usd=add_val)
            merged_amount = (existing_pending.amount or 0) + add_amt
            logger.info("[PENDING] Merged into pending id=%d token=%s new_total=%s", existing_pending.id, symbol, merged_amount)
            await _send_pending_merged_message(bot, user_id, event, existing_pending.id, merged_amount)
            _log_buy_event_decision(
                event,
                classification=getattr(event, "tx_type", ""),
                direction=getattr(event, "direction", ""),
                is_dca_applied=False,
                is_filtered=False,
                filter_reason="",
                pending_inserted=False,
                duplicate_detected=False,
            )
        return

    pt = PendingTrade(
        id=None,
        user_id=user_id,
        token_address=event.token_address,
        symbol=event.token_symbol,
        network=event.network,
        amount=event.amount,
        tx_hash=event.tx_hash or "",
        timestamp=datetime.utcnow().isoformat(),
        status="inbox",
        mcap=event.mcap,
        value_usd=event.value_usd,
    )
    pending_id = await insert_pending_trade(pt)
    logger.info("[PENDING] Inserted id=%d user_id=%d token=%s (OPEN)", pending_id, user_id, event.token_symbol)
    _log_buy_event_decision(
        event,
        classification=getattr(event, "tx_type", ""),
        direction=getattr(event, "direction", ""),
        is_dca_applied=False,
        is_filtered=False,
        filter_reason="",
        pending_inserted=True,
        duplicate_detected=False,
    )

    set_pending_detected_event(user_id, event)
    await _send_trade_detected_message(bot, user_id, event, pending_id=pending_id)
    _schedule_pending_timeout(pending_id)


async def _send_dca_prompt(bot, user_id: int, event: DetectedTradeEvent, existing_trade) -> None:
    """Send DCA confirm prompt: Add to position / Ignore. On confirm, handler applies DCA."""
    from bot.database.db import insert_pending_dca
    from bot.keyboards import kb_dca_confirm

    await _enrich_event_market_data(event)
    new_qty = event.amount or 0.0
    if new_qty <= 0:
        return
    new_price = event.price_usd or existing_trade.open_price or 0.0
    new_value = new_qty * new_price

    pending_id = await insert_pending_dca(user_id, existing_trade.trade_id, new_qty, new_price, new_value)
    sym = existing_trade.token_symbol or "?"
    try:
        text = (
            "📈 Additional buy detected.\n\n"
            f"🪙 Token: ${sym}\n"
            f"📦 Amount: {new_qty:.4g}\n"
            f"💰 Value: ${new_value:.2f}\n\n"
            "Do you want to add this to your existing position?"
        )
        await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=kb_dca_confirm(pending_id),
        )
    except Exception as e:
        logger.warning("Could not send DCA prompt to user %s: %s", user_id, e)


async def _apply_dca(
    user_id: int,
    trade_id: int,
    add_qty: float,
    add_price: float,
    add_value: Optional[float],
    mcap: Optional[float] = None,
) -> bool:
    """Apply DCA to existing trade. Returns True if updated. Stores price and mcap per entry."""
    from bot.database.db import get_trade_by_id, update_trade_open_quantity

    trade = await get_trade_by_id(trade_id, user_id)
    if not trade or trade.close_time is not None:
        return False
    old_qty = trade.remaining_quantity if trade.remaining_quantity is not None else trade.open_quantity or 0.0
    old_price = trade.open_price or 0.0
    total_qty = old_qty + add_qty
    if total_qty <= 0:
        return False
    if old_price > 0 or add_price > 0:
        weighted_price = ((old_qty * old_price) + (add_qty * add_price)) / total_qty
    else:
        weighted_price = old_price
    old_value = trade.open_value_usd or (old_qty * old_price)
    total_value = old_value + (add_value if add_value is not None else add_qty * add_price)
    await update_trade_open_quantity(trade_id, total_qty, weighted_price, total_value)
    add_value_usd = add_value if add_value is not None else add_qty * add_price
    from bot.database.db import insert_trade_timeline_event
    await insert_trade_timeline_event(
        trade_id, "DCA", value_usd=add_value_usd, amount=add_qty, price=add_price, mcap=mcap
    )
    logger.info("DCA applied: trade_id=%d qty %s→%s", trade_id, old_qty, total_qty)
    return True


async def _handle_dca(bot, user_id: int, event: DetectedTradeEvent, existing_trade) -> None:
    """DCA: add to existing open position (called from confirm handler)."""
    new_qty = event.amount or 0.0
    if new_qty <= 0:
        return
    await _enrich_event_market_data(event)
    new_price = event.price_usd or existing_trade.open_price or 0.0
    new_value = new_qty * new_price
    ok = await _apply_dca(user_id, existing_trade.trade_id, new_qty, new_price, new_value)
    if not ok:
        return
    try:
        text = "📈 DCA detected — added to your position."
        await bot.send_message(chat_id=user_id, text=text)
    except Exception as e:
        logger.warning("Could not send DCA message to user %s: %s", user_id, e)


# ---------------------------------------------------------------------------
# Balance-based exit for WALLET_TRANSFER out (exchange trades, CEX)
# ---------------------------------------------------------------------------

async def _handle_transfer_exit(
    bot, user_id: int, token_address: str, symbol: str, network: str,
    tx_hash: str, amount: Optional[float], block_number: Optional[int]
) -> None:
    """
    When a WALLET_TRANSFER out is detected, check if the token has an open position.
    If so, treat it as a close/partial close so exchange trades can still close positions.
    """
    if not (token_address or "").strip():
        logger.debug("[TRANSFER_EXIT] Empty token_address — skip")
        return
    token_key = (token_address or "").lower() if (token_address or "").strip().startswith("0x") else (token_address or "").strip()
    open_trade = await get_open_trade_for_token(user_id, token_key, network)
    if not open_trade:
        logger.info("Transfer out: no open position for token=%s user=%s — ignored.", token_address[:16], user_id)
        return

    logger.info(
        "Transfer out matches open position trade_id=%d token=%s. Treating as exit.",
        open_trade.trade_id, open_trade.token_symbol,
    )
    event = DetectedTradeEvent(
        token_symbol=symbol if symbol != "Unknown" else (open_trade.token_symbol or symbol),
        token_name=symbol if symbol != "Unknown" else (open_trade.token_symbol or symbol),
        token_address=token_address,
        network=network,
        direction="CLOSE",
        tx_hash=tx_hash or "",
        amount=amount,
        tx_type=TX_WALLET_TRANSFER,
    )
    if block_number is not None:
        event.block_timestamp = await rpc_clients.get_evm_block_timestamp(network, block_number)
    await _handle_close_detection(bot, user_id, event, "")


# ---------------------------------------------------------------------------
# CLOSE detection (balance-based): token balance decrease + matches open position
# If amount >= remaining_position → full close; if amount < remaining → partial exit.
# ---------------------------------------------------------------------------

async def _handle_close_detection(bot, user_id: int, event: DetectedTradeEvent, wallet_address: str = "") -> None:
    token_key = (event.token_address or "").lower() if (event.token_address or "").startswith("0x") else (event.token_address or "")
    open_trade = await get_open_trade_for_token(user_id, token_key, event.network or None)
    if not open_trade:
        # No open trade -> ignore close signal (never create pending/review side paths).
        return

    await _enrich_event_market_data(event)
    sell_price = event.price_usd or open_trade.open_price or 0.0
    quantity = open_trade.remaining_quantity if open_trade.remaining_quantity is not None else open_trade.open_quantity
    detected_sell_amount = event.amount or 0.0
    remaining_quantity = quantity or 0.0
    sell_amount = min(detected_sell_amount, remaining_quantity) if remaining_quantity > 0 else 0.0
    if abs(remaining_quantity - sell_amount) <= EPS_CLOSE_QTY:
        sell_amount = remaining_quantity
    overflow_sell_amount = max(0.0, detected_sell_amount - sell_amount)
    if overflow_sell_amount > 0:
        logger.info(
            "[CLOSE] Overflow sell ignored trade_id=%d overflow=%s detected=%s remaining=%s",
            open_trade.trade_id, overflow_sell_amount, detected_sell_amount, remaining_quantity
        )
    if sell_amount <= 0:
        return
    sell_value_usd = sell_amount * sell_price if sell_price else None

    exit_record = TradeExit(
        id=None,
        trade_id=open_trade.trade_id,
        amount=sell_amount,
        price=sell_price,
        value_usd=sell_value_usd,
        timestamp=datetime.utcnow().isoformat(),
    )
    await insert_trade_exit(exit_record)

    from bot.database.db import insert_trade_timeline_event
    if quantity is not None and sell_amount > 0 and (quantity - sell_amount) > EPS_CLOSE_QTY:
        await insert_trade_timeline_event(
            open_trade.trade_id, "PARTIAL_EXIT", value_usd=sell_value_usd, amount=sell_amount
        )
        remaining = quantity - sell_amount
        if abs(remaining) <= EPS_CLOSE_QTY:
            remaining = 0.0
        await update_trade_remaining_quantity(open_trade.trade_id, remaining)
        logger.info("[CLOSE] Partial exit trade_id=%d sold=%s remaining=%s", open_trade.trade_id, sell_amount, remaining)
        sym = event.token_symbol or open_trade.token_symbol
        try:
            await bot.send_message(
                chat_id=user_id,
                text=f"📤 Position partially closed.\n\nSold: {sell_amount:.4g} {sym}\nRemaining: {remaining:.4g} {sym}",
            )
        except Exception as e:
            logger.warning("Could not send partial close message to user %s: %s", user_id, e)
        return

    logger.info("[CLOSE] Full close trade_id=%d token=%s", open_trade.trade_id, open_trade.token_symbol)
    await insert_trade_timeline_event(
        open_trade.trade_id, "FULL_CLOSE", value_usd=sell_value_usd, amount=sell_amount
    )
    close_time = datetime.utcnow()
    open_time = open_trade.open_time if hasattr(open_trade.open_time, "isoformat") else datetime.fromisoformat(str(open_trade.open_time))
    duration = (close_time - open_time).total_seconds() if open_time else 0.0
    await update_trade_close(
        trade_id=open_trade.trade_id,
        close_time=close_time.isoformat(),
        close_price=sell_price,
        mcap_close=event.mcap,
        duration=duration,
        emotion_close="",  # User is prompted below; if unanswered, a future job could set to "Auto"
        emotion_close_note=None,
        reason_close="",  # Filled by follow-up questions (Emotion → Reason → Discipline)
        reason_close_note=None,
        discipline="",
    )

    summary = await _build_trade_summary(open_trade, sell_price, duration_seconds=duration)
    try:
        await bot.send_message(chat_id=user_id, text=summary)
        from bot.keyboards import kb_emotion_close_auto
        await bot.send_message(
            chat_id=user_id,
            text="How did you feel when closing this trade?",
            reply_markup=kb_emotion_close_auto(open_trade.trade_id),
        )
    except Exception as e:
        logger.warning("Could not send auto-close message to user %s: %s", user_id, e)


# ---------------------------------------------------------------------------
# Trade result summary
# ---------------------------------------------------------------------------

async def _build_trade_summary(trade, close_price: float, duration_seconds: Optional[float] = None) -> str:
    from bot.utils.formatters import get_network_icon, format_user_time, format_duration_seconds

    exits = await get_trade_exits(trade.trade_id)
    sym = trade.token_symbol or "?"
    token_display = f"{trade.token_name} (${sym})" if (getattr(trade, "token_name", None) or "").strip() else f"${sym}"
    chain_label = get_network_icon(trade.network or "")

    open_ts_raw = trade.open_time.isoformat() if hasattr(trade.open_time, "isoformat") else str(trade.open_time or "")
    open_ts = await format_user_time(trade.user_id, open_ts_raw) if open_ts_raw else "—"
    close_time_val = getattr(trade, "close_time", None)
    close_ts_raw = close_time_val.isoformat() if close_time_val and hasattr(close_time_val, "isoformat") else str(close_time_val or "")
    close_ts = await format_user_time(trade.user_id, close_ts_raw) if close_ts_raw else "—"

    open_value = trade.open_value_usd or (
        (trade.open_quantity or 0) * (trade.open_price or 0)
    )
    open_str = f"${open_value:.2f}" if open_value else "N/A"

    total_exit_value = 0.0
    exit_lines = []
    if exits:
        for i, ex in enumerate(exits, 1):
            ts = await format_user_time(trade.user_id, ex.timestamp or "")
            val_str = f"${ex.value_usd:.2f}" if ex.value_usd else f"{ex.amount:.4g} @ ${ex.price:.6f}"
            exit_lines.append(f"{i}. {val_str} — {ts}")
            total_exit_value += (ex.value_usd or (ex.amount * ex.price))

    if open_value and open_value > 0:
        pnl_pct = ((total_exit_value - open_value) / open_value) * 100
    else:
        pnl_pct = 0.0

    from bot.utils.formatters import format_pnl
    duration_sec = duration_seconds if duration_seconds is not None else (getattr(trade, "duration", None) or 0)
    duration_str = format_duration_seconds(duration_sec)
    result_emoji = "📈" if pnl_pct >= 0 else "📉"
    result_str = format_pnl(pnl_pct)

    lines = [
        "📊 TRADE CLOSED",
        "",
        f"🪙 Token: {token_display}",
        f"🌐 Chain: {chain_label}",
        "",
        "📅 Date",
        f"Open: {open_ts}",
        f"Close: {close_ts}",
        "",
        "📥 Entry",
        open_str,
        "",
        "📤 Exit",
    ]
    if exit_lines:
        lines.extend(exit_lines)
    else:
        lines.append("—")
    lines.append("")
    lines.append(f"{result_emoji} Result")
    lines.append(result_str)
    lines.append("")
    lines.append("⏱ Duration")
    lines.append(duration_str)
    lines.append("")
    lines.append("🤖 Position closed automatically based on your wallet transaction.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Market data enrichment
# ---------------------------------------------------------------------------

async def _enrich_event_market_data(event: DetectedTradeEvent) -> None:
    from bot.services import fetch_token_data
    if not event.token_address:
        return
    td = await fetch_token_data(event.token_address)
    if td:
        if event.token_symbol in ("Unknown", "?", ""):
            event.token_symbol = td.symbol or event.token_symbol
            event.token_name = td.name or event.token_name
        event.price_usd = td.price if td.price else event.price_usd
        event.liquidity = td.liquidity
        event.mcap = td.mcap
        event.volume_24h = td.volume_24h
        if event.amount and td.price:
            event.value_usd = event.amount * td.price


# ---------------------------------------------------------------------------
# Detection messages
# ---------------------------------------------------------------------------

def _format_usd(value: Optional[float]) -> str:
    if value is None or value <= 0:
        return "N/A"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.2f}K"
    return f"${value:.4f}" if value < 1 else f"${value:.2f}"


async def _send_trade_detected_message(bot, user_id: int, event: DetectedTradeEvent, pending_id: int = 0) -> None:
    from bot.keyboards import kb_record_trade_detected_with_id
    from bot.utils.formatters import get_network_icon

    name = (event.token_name or "").strip()
    symbol = (event.token_symbol or "Unknown").strip()
    sym_label = f"{name} (${symbol})" if name else (f"${symbol}" if symbol and symbol != "Unknown" else symbol)
    network_label = get_network_icon(event.network or "")
    amount_str = f"{event.amount:.4g}" if event.amount else "N/A"
    price_str = _format_usd(event.price_usd)
    value_str = _format_usd(event.value_usd)
    mcap_str = _format_usd(event.mcap)

    text = (
        "🧠 AUTO TRADE DETECTED\n\n"
        "A token transaction was detected in your wallet.\n\n"
        f"🪙 Token: {sym_label}\n"
        f"🌐 Chain: {network_label}\n"
        f"📦 Amount: {amount_str}\n\n"
        f"💰 Value: {value_str}\n"
        f"🏷 Price: {price_str}\n"
        f"🏦 Market Cap: {mcap_str}\n\n"
        "Do you want to record this as a trade?"
    )
    try:
        await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=kb_record_trade_detected_with_id(pending_id),
        )
        logger.info("Detection message sent to user_id=%s (network=%s, pending_id=%d)", user_id, event.network, pending_id)
    except Exception as e:
        logger.warning("Could not send trade detected to user %s: %s", user_id, e)


async def _send_pending_merged_message(bot, user_id: int, event: DetectedTradeEvent, pending_id: int, merged_amount: float) -> None:
    """Notify user that an additional buy was merged into an existing pending trade."""
    from bot.keyboards import kb_record_trade_detected_with_id
    from bot.utils.formatters import get_network_icon

    symbol = (event.token_symbol or "Unknown").strip()
    sym_label = f"${symbol}" if symbol and symbol != "Unknown" else symbol
    network_label = get_network_icon(event.network or "")
    text = (
        "📈 Additional buy detected for the same token.\n\n"
        f"🪙 Token: {sym_label}\n"
        f"🌐 Chain: {network_label}\n\n"
        f"📦 Total pending amount: {merged_amount:.4g}\n\n"
        "Do you want to record this trade (total amount)?"
    )
    try:
        await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=kb_record_trade_detected_with_id(pending_id),
        )
    except Exception as e:
        logger.warning("Could not send pending merged message to user %s: %s", user_id, e)


async def _send_transfer_detected_message(bot, user_id: int, event: DetectedTradeEvent, pending_id: int) -> None:
    """When token is received via transfer (no swap): prompt without auto-creating trade."""
    from bot.keyboards import kb_record_trade_detected_with_id
    from bot.utils.formatters import get_network_icon

    symbol = (event.token_symbol or "Unknown").strip()
    sym_label = f"${symbol}" if symbol and symbol != "Unknown" else symbol
    price_str = _format_usd(event.price_usd)
    amount_str = f"{event.amount:.4g}" if event.amount else "N/A"
    value_str = _format_usd(event.value_usd)
    mcap_str = _format_usd(event.mcap)
    network_label = get_network_icon(event.network or "")

    text = (
        "📥 Token received via transfer.\n\n"
        f"🪙 Token: {sym_label}\n"
        f"🌐 Chain: {network_label}\n"
        f"📦 Amount: {amount_str}\n\n"
        f"💰 Value: {value_str}\n"
        f"🏷 Price: {price_str}\n"
        f"🏦 Market Cap: {mcap_str}\n\n"
        "Do you want to record this as a trade?"
    )
    try:
        await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=kb_record_trade_detected_with_id(pending_id),
        )
        logger.info("Transfer detection message sent to user_id=%s (network=%s)", user_id, event.network)
    except Exception as e:
        logger.warning("Could not send transfer message to user %s: %s", user_id, e)


# ---------------------------------------------------------------------------
# Background loop
# ---------------------------------------------------------------------------

CLEANUP_PENDING_INTERVAL_SECONDS = 900  # 15 minutes


def start_wallet_monitor(bot) -> asyncio.Task:
    async def loop():
        logger.info("Wallet monitor started")
        while True:
            try:
                await poll_wallets(bot)
            except asyncio.CancelledError:
                logger.info("Wallet monitor stopped")
                raise
            except Exception as e:
                logger.exception("Wallet monitor loop error: %s", e)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    return asyncio.create_task(loop())


def start_pending_trades_cleanup() -> asyncio.Task:
    """Run pending trade auto-cleanup every CLEANUP_PENDING_INTERVAL_SECONDS (no notification on delete)."""
    async def loop():
        logger.info("Pending trades cleanup task started")
        while True:
            try:
                await asyncio.sleep(CLEANUP_PENDING_INTERVAL_SECONDS)
                # 24h cleanup for both queues (Pending=open, Trade Review=closed).
                from bot.database.db import cleanup_trade_center_older_than_hours
                n = await cleanup_trade_center_older_than_hours(24.0)
                if n:
                    logger.info("Pending trades cleanup: removed %d old pending trade(s)", n)
            except asyncio.CancelledError:
                logger.info("Pending trades cleanup task stopped")
                raise
            except Exception as e:
                logger.exception("Pending trades cleanup error: %s", e)

    return asyncio.create_task(loop())
