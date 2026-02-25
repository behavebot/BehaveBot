import re
from dataclasses import dataclass
from typing import Optional

import aiohttp

from config import DEXSCREENER_BASE


@dataclass
class TokenData:
    token_address: str
    name: str
    symbol: str
    chain: str
    price: float
    mcap: Optional[float]
    liquidity: Optional[float]
    volume_1h: Optional[float]
    age: Optional[str]
    chart_url: Optional[str]
    dex_name: Optional[str]


def _normalize_ca(text: str) -> Optional[str]:
    text = text.strip()
    if re.match(r"^0x[a-fA-F0-9]{40}$", text):
        return text.lower()
    if re.match(r"^[a-fA-F0-9]{40}$", text):
        return "0x" + text.lower()
    return None


def _safe_float(val, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


async def fetch_token_data(token_address: str) -> Optional[TokenData]:
    ca = _normalize_ca(token_address)
    if not ca:
        return None
    url = f"{DEXSCREENER_BASE}/{ca}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
    except Exception:
        return None
    pairs = data.get("pairs")
    if not pairs or not isinstance(pairs, list):
        return None
    pair = None
    for p in pairs:
        base = p.get("baseToken") or {}
        if (base.get("address") or "").lower() == ca:
            pair = p
            break
    if pair is None:
        pair = pairs[0]
    base = pair.get("baseToken") or {}
    chain = pair.get("chainId") or "unknown"
    price = _safe_float(pair.get("priceUsd"))
    liquidity = _safe_float(
        pair.get("liquidity", {}).get("usd")
        if isinstance(pair.get("liquidity"), dict)
        else pair.get("liquidity")
    )
    if liquidity == 0:
        liquidity = _safe_float(pair.get("liquidity"))
    volume = pair.get("volume")
    if isinstance(volume, dict):
        volume_1h = _safe_float(volume.get("h24"), 0.0)
    else:
        volume_1h = _safe_float(volume, 0.0)
    fdv = pair.get("fdv")
    mcap = _safe_float(fdv, 0.0) if fdv else None
    if mcap == 0:
        mcap = None
    created = pair.get("pairCreatedAt") or pair.get("pairCreationTime")
    age = None
    if created:
        try:
            from datetime import datetime
            ts = int(created) / 1000 if created > 1e12 else int(created)
            d = datetime.utcnow() - datetime.utcfromtimestamp(ts)
            if d.days == 0:
                hours = d.seconds // 3600
                age = f"{hours} hours" if hours else f"{d.seconds // 60} min"
            else:
                age = f"{d.days} days"
        except Exception:
            pass
    chart_url = pair.get("url")
    dex_name = pair.get("dexId") or pair.get("name")
    if isinstance(dex_name, str):
        dex_name = dex_name
    else:
        dex_name = None
    return TokenData(
        token_address=ca,
        name=base.get("name") or "Unknown",
        symbol=base.get("symbol") or "?",
        chain=chain,
        price=price,
        mcap=mcap,
        liquidity=liquidity if liquidity else None,
        volume_1h=volume_1h if volume_1h else None,
        age=age,
        chart_url=chart_url,
        dex_name=dex_name,
    )
