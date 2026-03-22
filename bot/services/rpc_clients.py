"""
RPC clients for Wallet Auto Trade Detection (Solana, BNB Chain, Base).
Uses aiohttp. RPC URLs configured via .env (SOL_RPC, BNB_RPC, BASE_RPC).
"""

import json
import logging
from typing import Any, Optional

import aiohttp

from config import SOL_RPC, BNB_RPC, BASE_RPC, SOL_RPC_PUBLIC_FALLBACK

logger = logging.getLogger(__name__)


def _mask_rpc_url(url: str) -> str:
    """Return URL with API key masked for safe logging (e.g. https://rpc.ankr.com/bsc/***)."""
    if not url or not isinstance(url, str):
        return "not set"
    u = url.strip()
    if not u:
        return "not set"
    # Mask anything after last path segment that looks like an API key (long hex/alphanumeric)
    last_slash = u.rfind("/")
    if last_slash >= 0 and len(u) - last_slash > 20:
        return u[: last_slash + 1] + "***"
    return u[:60] + "..." if len(u) > 60 else u


def _log_rpc_endpoints() -> None:
    """Log configured RPC endpoints at startup (API keys masked)."""
    if BNB_RPC:
        logger.info("Using RPC endpoint for BNB: %s", _mask_rpc_url(BNB_RPC))
    if BASE_RPC:
        logger.info("Using RPC endpoint for Base: %s", _mask_rpc_url(BASE_RPC))
    if SOL_RPC:
        logger.info("Using RPC endpoint for Solana: %s", _mask_rpc_url(SOL_RPC))


_log_rpc_endpoints()

# ERC20 Transfer(address,address,uint256) topic0
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def _rpc_url(network: str) -> str:
    if network == "Solana":
        return SOL_RPC
    if network == "BNB Chain":
        return BNB_RPC
    if network == "Base":
        return BASE_RPC
    return ""


async def _solana_post(method: str, params: list) -> Optional[dict]:
    """Post JSON-RPC to Solana RPC. On 403, retry with public fallback. No hardcoded URLs (use config)."""
    url = (SOL_RPC or "").strip() or SOL_RPC_PUBLIC_FALLBACK
    if not url:
        logger.warning("Solana RPC: no endpoint")
        return None
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                raw = await resp.text()
                if resp.status == 403 and url != SOL_RPC_PUBLIC_FALLBACK and SOL_RPC_PUBLIC_FALLBACK:
                    logger.warning("Solana RPC 403, retrying with public fallback")
                    async with session.post(SOL_RPC_PUBLIC_FALLBACK, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as retry_resp:
                        raw = await retry_resp.text()
                        if retry_resp.status != 200:
                            return None
                        try:
                            data = json.loads(raw)
                            return data.get("result")
                        except Exception:
                            return None
                if resp.status != 200:
                    logger.warning("Solana RPC %s: status=%s body=%s", method, resp.status, raw[:200])
                    return None
                try:
                    data = json.loads(raw)
                except Exception:
                    return None
                return data.get("result")
    except Exception as e:
        logger.warning("Solana RPC %s: %s", method, e)
        return None


async def _evm_post(url: str, method: str, params: list) -> Optional[Any]:
    """Post JSON-RPC to EVM (BNB/Base). Returns result field only."""
    data = await _evm_post_raw(url, method, params)
    return data.get("result") if isinstance(data, dict) else None


async def _evm_post_raw(url: str, method: str, params: list) -> Optional[dict]:
    """Post JSON-RPC to EVM; returns full response dict for debugging."""
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                raw = await resp.text()
                try:
                    data = json.loads(raw)
                except Exception:
                    data = {"_raw": raw[:500], "status": resp.status}
                if resp.status != 200:
                    logger.warning("EVM RPC %s: status=%s response=%s", method, resp.status, raw[:300])
                    return data if isinstance(data, dict) else None
                return data if isinstance(data, dict) else None
    except Exception as e:
        logger.warning("EVM RPC %s: %s", method, e)
        return None


def _to_hex_address(addr: str) -> str:
    """EVM address to 32-byte hex topic (left-padded)."""
    a = addr.lower().replace("0x", "")
    return "0x" + a.zfill(64)


async def get_solana_transactions(address: str, limit: int = 20) -> list[dict]:
    """
    Get recent signatures for a Solana address.
    method: getSignaturesForAddress, params: [wallet_address, {"limit": N}].
    Returns list of {"signature": str, "blockTime": int or None}, newest first.
    """
    if not SOL_RPC:
        logger.warning("RPC Solana: endpoint not set, skipping")
        return []
    result = await _solana_post("getSignaturesForAddress", [address, {"limit": limit}])
    num = len(result) if result and isinstance(result, list) else 0
    logger.info(
        "RPC Solana: endpoint=%s wallet=%s signatures=%d",
        _mask_rpc_url(SOL_RPC),
        address[:8] + "..." + address[-4:] if address and len(address) > 16 else (address or "?"),
        num,
    )
    if not result or not isinstance(result, list):
        logger.debug("RPC Solana: non-list or empty result (result type=%s)", type(result).__name__)
        return []
    out = []
    for item in result:
        out.append({
            "signature": item.get("signature", ""),
            "blockTime": item.get("blockTime"),
        })
    return out


async def get_solana_transaction(signature: str) -> Optional[dict]:
    """Get a single Solana transaction by signature (for parsing)."""
    result = await _solana_post(
        "getTransaction",
        [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
    )
    return result


async def get_evm_transactions(address: str, network: str, from_block: int, to_block: int) -> list[dict]:
    """
    Get Transfer logs for an EVM address in block range.
    Returns list of {"tx_hash": str, "blockNumber": int, "token_address": str, "symbol": str or None}.
    """
    url = _rpc_url(network)
    if not url:
        logger.warning("RPC %s: no endpoint configured", network)
        return []
    # Get logs: Transfer(from, to, value). We want from=address or to=address.
    # topics: [Transfer, from?, to?]. We do two calls: from=address and to=address.
    addr_topic = _to_hex_address(address)
    logs_from = await _evm_post(
        url,
        "eth_getLogs",
        [{
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
            "topics": [TRANSFER_TOPIC, addr_topic],
        }],
    )
    logs_to = await _evm_post(
        url,
        "eth_getLogs",
        [{
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
            "topics": [TRANSFER_TOPIC, None, addr_topic],
        }],
    )
    seen = set()
    out = []
    for direction, log_list in (("out", logs_from or []), ("in", logs_to or [])):
        for log in log_list if isinstance(log_list, list) else []:
            tx_hash = log.get("transactionHash")
            if not tx_hash:
                continue
            tx_hash = tx_hash if isinstance(tx_hash, str) else ("0x" + tx_hash.hex() if hasattr(tx_hash, "hex") else "")
            block_hex = log.get("blockNumber")
            block = int(block_hex, 16) if isinstance(block_hex, str) else (block_hex or 0)
            token_address = log.get("address")
            if token_address is not None and isinstance(token_address, bytes):
                token_address = "0x" + token_address.hex()
            if token_address is not None and not isinstance(token_address, str):
                token_address = str(token_address)
            key = (tx_hash, token_address)
            if key in seen:
                continue
            seen.add(key)
            symbol = await get_erc20_symbol(url, token_address) if token_address else None
            amount_raw = 0
            data = log.get("data")
            if data and isinstance(data, str):
                amount_raw = _decode_uint256(data)
            decimals = await get_erc20_decimals(url, token_address) if token_address else 18
            amount = (amount_raw / (10**decimals)) if amount_raw else None
            topics = log.get("topics") or []
            from_address = ""
            to_address = ""
            if len(topics) >= 3:
                from_address = "0x" + topics[1][-40:] if isinstance(topics[1], str) and len(topics[1]) >= 40 else ""
                to_address = "0x" + topics[2][-40:] if isinstance(topics[2], str) and len(topics[2]) >= 40 else ""
            out.append({
                "tx_hash": tx_hash,
                "blockNumber": block,
                "token_address": token_address or "",
                "symbol": symbol,
                "direction": direction,
                "amount": amount,
                "from_address": from_address,
                "to_address": to_address,
            })
    out.sort(key=lambda x: x["blockNumber"], reverse=True)
    logger.info(
        "RPC %s: endpoint=%s, %d transfer logs returned",
        network,
        _mask_rpc_url(url) if url else "not set",
        len(out),
    )
    for i, o in enumerate(out[:5]):
        logger.debug(
            "RPC %s raw_tx[%d]: tx_hash=%s block=%s token=%s symbol=%s direction=%s amount=%s",
            network, i, o.get("tx_hash", "")[:18], o.get("blockNumber"), o.get("token_address", "")[:18],
            o.get("symbol"), o.get("direction"), o.get("amount"),
        )
    if len(out) > 5:
        logger.debug("RPC %s: ... and %d more transfer logs", network, len(out) - 5)
    return out


def _decode_uint256(hex_str: str) -> int:
    """Decode 32-byte hex to int."""
    if not hex_str or not isinstance(hex_str, str):
        return 0
    s = hex_str[2:] if hex_str.startswith("0x") else hex_str
    try:
        return int(s[:64], 16)  # first 32 bytes
    except (ValueError, TypeError):
        return 0


async def get_erc20_decimals(rpc_url: str, token_address: str) -> int:
    """Call decimals() on an ERC20 contract. Returns 18 on failure (common default)."""
    data = "0x313ce567"
    result = await _evm_post(
        rpc_url,
        "eth_call",
        [{"to": token_address, "data": data}, "latest"],
    )
    if not result or result == "0x":
        return 18
    try:
        if isinstance(result, str) and result.startswith("0x"):
            return int(result[2:], 16)
        return 18
    except (ValueError, TypeError):
        return 18


async def get_erc20_symbol(rpc_url: str, token_address: str) -> Optional[str]:
    """Call symbol() on an ERC20 contract. Returns None on failure."""
    # symbol() selector: 0x95d89b41
    data = "0x95d89b41"
    result = await _evm_post(
        rpc_url,
        "eth_call",
        [{"to": token_address, "data": data}, "latest"],
    )
    if not result or result == "0x":
        return None
    try:
        # ABI decode string (first 32 bytes = offset, next 32 = length, then data)
        if isinstance(result, str) and result.startswith("0x"):
            result = bytes.fromhex(result[2:])
        if len(result) >= 96:
            length = int.from_bytes(result[64:96], "big")
            return result[96 : 96 + length].decode("utf-8", errors="ignore").strip() or None
        return None
    except Exception:
        return None


async def get_evm_tx_details(network: str, tx_hash: str) -> Optional[dict]:
    """Fetch full transaction object. Returns dict with 'to', 'input', 'value', 'from' etc."""
    url = _rpc_url(network)
    if not url:
        logger.warning("get_evm_tx_details: no RPC for network=%s", network)
        return None
    result = await _evm_post(url, "eth_getTransactionByHash", [tx_hash])
    if not result or not isinstance(result, dict):
        logger.debug("RPC %s get_evm_tx_details: no result for tx=%s", network, tx_hash[:18])
        return None
    to_addr = (result.get("to") or "")
    inp = (result.get("input") or "")[:66]
    logger.debug(
        "RPC %s tx_details: tx=%s to=%s input_prefix=%s",
        network, tx_hash[:18], to_addr[:18] if to_addr else "None", inp + "..." if len(inp) == 66 else inp,
    )
    return result


async def get_evm_block_number(network: str) -> int:
    """Get latest block number for EVM network. Retries once on failure."""
    url = _rpc_url(network)
    if not url:
        logger.warning("get_evm_block_number: no RPC endpoint for network=%s", network)
        return 0
    for attempt in range(2):
        data = await _evm_post_raw(url, "eth_blockNumber", [])
        if data and isinstance(data, dict) and "result" in data:
            logger.debug("RPC %s eth_blockNumber: result=%s", network, data.get("result"))
        elif data:
            logger.info("RPC %s eth_blockNumber: raw=%s", network, str(data)[:200])
        if not isinstance(data, dict):
            if attempt == 0:
                continue
            return 0
        result = data.get("result")
        if data.get("error"):
            err = data["error"]
            logger.warning("RPC %s eth_blockNumber error: %s", network, err)
            if attempt == 0:
                continue
            return 0
        if result is None:
            if attempt == 0:
                continue
            return 0
        try:
            if isinstance(result, str) and result.startswith("0x"):
                return int(result, 16)
            return int(result)
        except (TypeError, ValueError) as e:
            logger.warning("RPC %s eth_blockNumber parse error: result=%s %s", network, result, e)
            if attempt == 0:
                continue
            return 0
    return 0


async def get_evm_block_timestamp(network: str, block_number: int) -> Optional[int]:
    """Return Unix timestamp for the given block, or None."""
    url = _rpc_url(network)
    if not url:
        return None
    result = await _evm_post(url, "eth_getBlockByNumber", [hex(block_number), False])
    if not result or not isinstance(result, dict):
        return None
    ts = result.get("timestamp")
    if ts is None:
        return None
    if isinstance(ts, str) and ts.startswith("0x"):
        return int(ts, 16)
    return int(ts)


# balanceOf(address) selector
ERC20_BALANCE_OF_SELECTOR = "0x70a08231"


def _pad_address(addr: str) -> str:
    """Pad address to 32 bytes for eth_call (remove 0x, pad left to 64 hex chars)."""
    a = (addr or "").strip()
    if a.startswith("0x"):
        a = a[2:]
    return "0x" + a.lower().zfill(64)


async def get_evm_token_balance(
    network: str, wallet_address: str, token_address: str, decimals: Optional[int] = None
) -> Optional[float]:
    """
    Return ERC20 token balance for wallet in human units, or None on error.
    Used to detect 'balance was zero' so next buy starts a new trade.
    """
    url = _rpc_url(network)
    if not url or not wallet_address or not token_address:
        return None
    if decimals is None:
        decimals = await get_erc20_decimals(url, token_address.strip())
    data = ERC20_BALANCE_OF_SELECTOR + _pad_address(wallet_address)
    result = await _evm_post(
        url,
        "eth_call",
        [{"to": token_address.strip(), "data": data}, "latest"],
    )
    if not result or result == "0x":
        return 0.0
    raw = _parse_hex_to_int(result)
    if raw == 0:
        return 0.0
    try:
        return raw / (10 ** decimals)
    except Exception:
        return None
