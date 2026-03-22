"""Shared UI formatters: network icons, timestamps, precision. Used only for message formatting."""

from datetime import datetime, timedelta


async def format_user_time(user_id: int, utc_timestamp) -> str:
    """Central formatter: convert UTC timestamp to user's local time for display.
    utc_timestamp: datetime or ISO date/time string. Returns e.g. '2026-03-15 14:00 (UTC+7)'.
    Use this for all user-facing timestamps."""
    from bot.database.db import get_user_timezone_offset
    if utc_timestamp is None:
        return "—"
    if hasattr(utc_timestamp, "isoformat"):
        iso_str = utc_timestamp.isoformat()
    else:
        iso_str = str(utc_timestamp or "").strip()
    if not iso_str:
        return "—"
    offset = await get_user_timezone_offset(user_id)
    return format_timestamp_local(iso_str, offset)

# Precision: PnL/result 1 dec, price 6 dec, token amount 8 dec
def format_pnl(pct: float) -> str:
    """One decimal, with sign. E.g. +0.2%, -1.4%."""
    return f"{round(pct, 1):+.1f}%"


def format_price(price: float) -> str:
    """Up to 6 decimals. E.g. $0.491600."""
    if price is None or (isinstance(price, float) and price != price):
        return "—"
    p = float(price)
    if p == 0:
        return "$0.000000"
    if p >= 1:
        return f"${p:.2f}"
    return f"${p:.6f}"


def format_token_amount(amount: float) -> str:
    """Up to 8 decimals. E.g. 0.03804000."""
    if amount is None or (isinstance(amount, float) and amount != amount):
        return "—"
    a = float(amount)
    if a == 0:
        return "0.00000000"
    return f"{a:.8f}".rstrip("0").rstrip(".") or "0.00000000"


def format_token_display(symbol: str, name: str = None) -> str:
    """Full Token Name ($TICKER) or $TICKER if no name."""
    sym = (symbol or "?").strip()
    if (name or "").strip():
        return f"{name.strip()} (${sym})"
    return f"${sym}"


def format_compact_number(value) -> str:
    """Compact numeric formatter for market caps and large amounts.
    Rules: ≥1,000 → 1.2K; ≥1,000,000 → 1.2M; ≥1,000,000,000 → 1.2B (one decimal).
    None or invalid → —."""
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    sign = "-" if v < 0 else ""
    n = abs(v)
    if n >= 1_000_000_000:
        return f"{sign}{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{sign}{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{sign}{n / 1_000:.1f}K"
    if n.is_integer():
        return f"{sign}{int(n)}"
    return f"{sign}{n:.2f}"


# Network display: icon + name (do not change detection/RPC logic)
NETWORK_ICONS = {
    "BNB Chain": "🟡",
    "Base": "🔵",
    "Solana": "🟣",
}


def get_network_icon(network: str) -> str:
    """Return icon + network name for display. E.g. 'BNB Chain' -> '🟡 BNB Chain'."""
    if not network or not isinstance(network, str):
        return "—"
    n = network.strip()
    icon = NETWORK_ICONS.get(n, "")
    return f"{icon} {n}".strip() if icon else n


def format_timestamp_utc(iso_timestamp: str) -> str:
    """Format ISO timestamp as YYYY-MM-DD HH:MM UTC. Returns '—' if invalid."""
    if not iso_timestamp:
        return "—"
    s = str(iso_timestamp).strip()
    try:
        s = s.replace("Z", "").replace("+00:00", "")
        if "T" in s:
            date_part, time_part = s.split("T", 1)
            time_part = time_part[:5]
            return f"{date_part} {time_part} UTC"
        if " " in s:
            return s[:16] + " UTC" if len(s) >= 16 else s + " UTC"
        return s[:10] + " 00:00 UTC"
    except Exception:
        return s[:16] + " UTC" if len(s) >= 16 else (s + " UTC")


def format_timestamp_local(iso_timestamp: str, offset_hours: int = 0) -> str:
    """Convert UTC ISO timestamp to local time using offset_hours. Format: YYYY-MM-DD HH:MM (UTC±N)."""
    if not iso_timestamp:
        return "—"
    s = str(iso_timestamp).strip().replace("Z", "").replace("+00:00", "")
    try:
        if "T" in s:
            dt = datetime.fromisoformat(s)
        elif " " in s:
            dt = datetime.fromisoformat(s)
        else:
            dt = datetime.fromisoformat(s[:10] + "T00:00:00")
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        local_dt = dt + timedelta(hours=offset_hours)
        date_part = local_dt.strftime("%Y-%m-%d")
        time_part = local_dt.strftime("%H:%M")
        if offset_hours >= 0:
            tz_label = f"UTC+{offset_hours}"
        else:
            tz_label = f"UTC{offset_hours}"
        return f"{date_part} {time_part} ({tz_label})"
    except Exception:
        return format_timestamp_utc(iso_timestamp)


def format_duration_seconds(seconds: float) -> str:
    """Format duration with seconds. Examples: 45s, 1m 24s, 2m 10s, 1h 5m 30s."""
    if seconds is None or seconds < 0:
        return "0s"
    secs = int(round(seconds))
    if secs < 60:
        return f"{secs}s"
    mins, s = divmod(secs, 60)
    if mins < 60:
        return f"{mins}m {s}s" if s else f"{mins}m"
    hours, mins = divmod(mins, 60)
    parts = [f"{hours}h"]
    if mins:
        parts.append(f"{mins}m")
    if s:
        parts.append(f"{s}s")
    return " ".join(parts)
