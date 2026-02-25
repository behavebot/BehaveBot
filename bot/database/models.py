from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Trade:
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

    def to_row(self) -> tuple:
        return (
            self.user_id,
            self.token_address,
            self.token_symbol,
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
        )

    @classmethod
    def from_row(cls, row: tuple) -> "Trade":
        return cls(
            trade_id=row[0],
            user_id=row[1],
            token_address=row[2],
            token_symbol=row[3],
            open_time=datetime.fromisoformat(row[4]) if row[4] else None,
            close_time=datetime.fromisoformat(row[5]) if row[5] else None,
            open_price=row[6],
            close_price=row[7],
            mcap_open=row[8],
            mcap_close=row[9],
            duration=row[10],
            emotion_open=row[11] or "",
            emotion_open_note=row[12],
            reason_open=row[13] or "",
            reason_open_note=row[14],
            token_category=row[15] or "",
            token_category_note=row[16],
            risk_level=row[17] or "",
            emotion_close=row[18],
            emotion_close_note=row[19],
            reason_close=row[20],
            reason_close_note=row[21],
            discipline=row[22],
            status=row[23] or "valid",
        )


@dataclass
class Feedback:
    feedback_id: Optional[int]
    user_id: int
    text: Optional[str]
    image_path: Optional[str]
    created_at: datetime
