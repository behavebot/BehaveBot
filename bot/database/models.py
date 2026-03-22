from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Trade:
    # Required fields (no defaults) first
    trade_id: Optional[int]
    user_id: int
    token_address: str
    token_symbol: str
    open_time: datetime
    close_time: Optional[datetime]
    open_price: float
    close_price: Optional[float]
    mcap_open: Optional[float]
    mcap_close: Optional[float]
    duration: Optional[float]
    emotion_open: str
    emotion_open_note: Optional[str]
    reason_open: str
    reason_open_note: Optional[str]
    token_category: str
    token_category_note: Optional[str]
    risk_level: str
    emotion_close: Optional[str]
    emotion_close_note: Optional[str]
    reason_close: Optional[str]
    reason_close_note: Optional[str]
    discipline: Optional[str]
    status: str
    # Fields with defaults last
    token_name: Optional[str] = None  # Full name for display: "Open Platform ($OPN)"
    open_quantity: Optional[float] = None
    remaining_quantity: Optional[float] = None
    trade_mode: str = "manual"  # "manual" | "auto"
    network: Optional[str] = None
    open_value_usd: Optional[float] = None

    def to_row(self) -> tuple:
        return (
            self.user_id,
            self.token_address,
            self.token_symbol,
            self.token_name,
            self.open_time.isoformat(),
            self.close_time.isoformat() if self.close_time else None,
            self.open_price,
            self.close_price,
            self.mcap_open,
            self.mcap_close,
            self.duration,
            self.emotion_open,
            self.emotion_open_note,
            self.reason_open,
            self.reason_open_note,
            self.token_category,
            self.token_category_note,
            self.risk_level,
            self.emotion_close,
            self.emotion_close_note,
            self.reason_close,
            self.reason_close_note,
            self.discipline,
            self.status,
            self.open_quantity,
            self.remaining_quantity,
            self.trade_mode,
            self.network,
            self.open_value_usd,
        )

    @classmethod
    def from_row(cls, row: tuple) -> "Trade":
        # Row: 0-3 id,user,token_address,token_symbol, 4 token_name, 5 open_time, 6 close_time, ...
        n = len(row)
        token_name = row[4] if n > 4 else None
        return cls(
            trade_id=row[0],
            user_id=row[1],
            token_address=row[2],
            token_symbol=row[3],
            token_name=token_name,
            open_time=datetime.fromisoformat(row[5]) if n > 5 and row[5] else None,
            close_time=datetime.fromisoformat(row[6]) if n > 6 and row[6] else None,
            open_price=row[7] if n > 7 else 0,
            close_price=row[8] if n > 8 else None,
            mcap_open=row[9] if n > 9 else None,
            mcap_close=row[10] if n > 10 else None,
            duration=row[11] if n > 11 else None,
            emotion_open=(row[12] or "") if n > 12 else "",
            emotion_open_note=row[13] if n > 13 else None,
            reason_open=(row[14] or "") if n > 14 else "",
            reason_open_note=row[15] if n > 15 else None,
            token_category=(row[16] or "") if n > 16 else "",
            token_category_note=row[17] if n > 17 else None,
            risk_level=(row[18] or "") if n > 18 else "",
            emotion_close=row[19] if n > 19 else None,
            emotion_close_note=row[20] if n > 20 else None,
            reason_close=row[21] if n > 21 else None,
            reason_close_note=row[22] if n > 22 else None,
            discipline=row[23] if n > 23 else None,
            status=(row[24] or "valid") if n > 24 else "valid",
            open_quantity=row[25] if n > 25 else None,
            remaining_quantity=row[26] if n > 26 else None,
            trade_mode=row[27] if n > 27 and row[27] else "manual",
            network=row[28] if n > 28 else None,
            open_value_usd=row[29] if n > 29 else None,
        )


@dataclass
class PendingTrade:
    """A detected trade queued for user decision (Record / Ignore). Sent once, never resent."""
    id: Optional[int]
    user_id: int
    token_address: str
    symbol: str
    network: str
    amount: Optional[float]
    tx_hash: str
    timestamp: str
    status: str = "pending"  # "pending" | "recorded" | "ignored" | "merged"
    mcap: Optional[float] = None  # cached at detection for display
    value_usd: Optional[float] = None  # entry value at detection (for merge-ignored)


@dataclass
class TradeExit:
    """A partial or full exit from a trade position."""
    id: Optional[int]
    trade_id: int
    amount: float
    price: float
    value_usd: Optional[float]
    timestamp: str


@dataclass
class Feedback:
    feedback_id: Optional[int]
    user_id: int
    text: Optional[str]
    image_path: Optional[str]
    created_at: datetime
