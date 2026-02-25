import aiosqlite
from pathlib import Path
from typing import Optional

from config import DB_PATH
from .models import Trade

_db: Optional[aiosqlite.Connection] = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
    return _db


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None


TRADES_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token_address TEXT NOT NULL,
    token_symbol TEXT NOT NULL,
    open_time TEXT NOT NULL,
    close_time TEXT,
    open_price REAL NOT NULL,
    close_price REAL,
    mcap_open REAL,
    mcap_close REAL,
    duration REAL,
    emotion_open TEXT,
    emotion_open_note TEXT,
    reason_open TEXT,
    reason_open_note TEXT,
    token_category TEXT,
    token_category_note TEXT,
    risk_level TEXT,
    emotion_close TEXT,
    emotion_close_note TEXT,
    reason_close TEXT,
    reason_close_note TEXT,
    discipline TEXT,
    status TEXT NOT NULL DEFAULT 'valid',
    invalid_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_trades_user ON trades(user_id);
CREATE INDEX IF NOT EXISTS idx_trades_user_token ON trades(user_id, token_address);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
"""

FEEDBACK_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    text TEXT,
    image_path TEXT,
    created_at TEXT NOT NULL
);
"""

SYSTEM_SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


async def init_db() -> None:
    db = await get_db()
    await db.executescript(TRADES_SCHEMA)
    await db.executescript(FEEDBACK_SCHEMA)
    await db.executescript(SYSTEM_SETTINGS_SCHEMA)
    try:
        await db.execute("ALTER TABLE trades ADD COLUMN invalid_reason TEXT")
        await db.commit()
    except Exception:
        await db.rollback()
    await db.commit()


async def get_system_setting(key: str) -> Optional[str]:
    """Return value for key, or None if not set."""
    db = await get_db()
    cursor = await db.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row[0] if row else None


async def set_system_setting(key: str, value: str) -> None:
    """Insert or replace key=value in system_settings."""
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)",
        (key, value),
    )
    await db.commit()


async def is_maintenance_mode() -> bool:
    """True if maintenance is on. Default off."""
    val = await get_system_setting("maintenance")
    return (val or "off").lower() == "on"


async def insert_trade(t: Trade) -> int:
    db = await get_db()
    await db.execute(
        """
        INSERT INTO trades (
            user_id, token_address, token_symbol, open_time, close_time,
            open_price, close_price, mcap_open, mcap_close, duration,
            emotion_open, emotion_open_note, reason_open, reason_open_note,
            token_category, token_category_note, risk_level,
            emotion_close, emotion_close_note, reason_close, reason_close_note,
            discipline, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        t.to_row(),
    )
    await db.commit()
    cursor = await db.execute("SELECT last_insert_rowid()")
    row = await cursor.fetchone()
    return row[0]


async def update_trade_close(
    trade_id: int,
    close_time: str,
    close_price: float,
    mcap_close: Optional[float],
    duration: float,
    emotion_close: str,
    emotion_close_note: Optional[str],
    reason_close: str,
    reason_close_note: Optional[str],
    discipline: str,
) -> None:
    db = await get_db()
    await db.execute(
        """
        UPDATE trades SET
            close_time = ?, close_price = ?, mcap_close = ?, duration = ?,
            emotion_close = ?, emotion_close_note = ?, reason_close = ?, reason_close_note = ?,
            discipline = ?
        WHERE trade_id = ?
        """,
        (
            close_time,
            close_price,
            mcap_close,
            duration,
            emotion_close,
            emotion_close_note,
            reason_close,
            reason_close_note,
            discipline,
            trade_id,
        ),
    )
    await db.commit()


async def set_trade_invalid(trade_id: int, reason: str = "") -> None:
    db = await get_db()
    try:
        await db.execute(
            "UPDATE trades SET status = 'invalid', invalid_reason = ? WHERE trade_id = ?",
            (reason, trade_id),
        )
    except Exception:
        await db.execute(
            "UPDATE trades SET status = 'invalid' WHERE trade_id = ?", (trade_id,)
        )
    await db.commit()


async def get_open_trades(user_id: int) -> list[Trade]:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT trade_id, user_id, token_address, token_symbol, open_time, close_time,
               open_price, close_price, mcap_open, mcap_close, duration,
               emotion_open, emotion_open_note, reason_open, reason_open_note,
               token_category, token_category_note, risk_level,
               emotion_close, emotion_close_note, reason_close, reason_close_note,
               discipline, status
        FROM trades WHERE user_id = ? AND close_time IS NULL AND status = 'valid'
        ORDER BY open_time DESC
        """,
        (user_id,),
    )
    rows = await cursor.fetchall()
    return [Trade.from_row(tuple(r)) for r in rows]


async def get_open_trade_for_token(user_id: int, token_address: str) -> Optional[Trade]:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT trade_id, user_id, token_address, token_symbol, open_time, close_time,
               open_price, close_price, mcap_open, mcap_close, duration,
               emotion_open, emotion_open_note, reason_open, reason_open_note,
               token_category, token_category_note, risk_level,
               emotion_close, emotion_close_note, reason_close, reason_close_note,
               discipline, status
        FROM trades WHERE user_id = ? AND token_address = ? AND close_time IS NULL AND status = 'valid'
        """,
        (user_id, token_address.lower()),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return Trade.from_row(tuple(row))


async def get_last_closed_trade_for_token(
    user_id: int, token_address: str
) -> Optional[Trade]:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT trade_id, user_id, token_address, token_symbol, open_time, close_time,
               open_price, close_price, mcap_open, mcap_close, duration,
               emotion_open, emotion_open_note, reason_open, reason_open_note,
               token_category, token_category_note, risk_level,
               emotion_close, emotion_close_note, reason_close, reason_close_note,
               discipline, status
        FROM trades WHERE user_id = ? AND token_address = ? AND close_time IS NOT NULL AND status = 'valid'
        ORDER BY close_time DESC LIMIT 1
        """,
        (user_id, token_address.lower()),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return Trade.from_row(tuple(row))


async def get_trade_by_id(trade_id: int, user_id: int) -> Optional[Trade]:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT trade_id, user_id, token_address, token_symbol, open_time, close_time,
               open_price, close_price, mcap_open, mcap_close, duration,
               emotion_open, emotion_open_note, reason_open, reason_open_note,
               token_category, token_category_note, risk_level,
               emotion_close, emotion_close_note, reason_close, reason_close_note,
               discipline, status
        FROM trades WHERE trade_id = ? AND user_id = ?
        """,
        (trade_id, user_id),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return Trade.from_row(tuple(row))


async def get_valid_trades_for_stats(user_id: int) -> list[Trade]:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT trade_id, user_id, token_address, token_symbol, open_time, close_time,
               open_price, close_price, mcap_open, mcap_close, duration,
               emotion_open, emotion_open_note, reason_open, reason_open_note,
               token_category, token_category_note, risk_level,
               emotion_close, emotion_close_note, reason_close, reason_close_note,
               discipline, status
        FROM trades WHERE user_id = ? AND status = 'valid' AND close_time IS NOT NULL
        ORDER BY close_time DESC
        """,
        (user_id,),
    )
    rows = await cursor.fetchall()
    return [Trade.from_row(tuple(r)) for r in rows]


async def insert_feedback(user_id: int, text: Optional[str], image_path: Optional[str]) -> None:
    from datetime import datetime
    db = await get_db()
    await db.execute(
        "INSERT INTO feedback (user_id, text, image_path, created_at) VALUES (?, ?, ?, ?)",
        (user_id, text, image_path, datetime.utcnow().isoformat()),
    )
    await db.commit()


async def get_feedback_last_n(limit: int = 10):
    """Fetch last `limit` feedback rows, newest first. Returns list of Row-like objects."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT feedback_id, user_id, text, image_path, created_at FROM feedback ORDER BY feedback_id DESC LIMIT ?",
        (limit,),
    )
    return await cursor.fetchall()


async def get_feedback_all():
    """Fetch all feedback rows, newest first. Returns list of Row-like objects."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT feedback_id, user_id, text, image_path, created_at FROM feedback ORDER BY feedback_id DESC"
    )
    return await cursor.fetchall()


async def get_all_trades_for_export() -> list[Trade]:
    """Fetch all trades (all users) for admin CSV export. Newest first."""
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT trade_id, user_id, token_address, token_symbol, open_time, close_time,
               open_price, close_price, mcap_open, mcap_close, duration,
               emotion_open, emotion_open_note, reason_open, reason_open_note,
               token_category, token_category_note, risk_level,
               emotion_close, emotion_close_note, reason_close, reason_close_note,
               discipline, status
        FROM trades ORDER BY trade_id DESC
        """,
    )
    rows = await cursor.fetchall()
    return [Trade.from_row(tuple(r)) for r in rows]


async def get_closed_trades_by_token(user_id: int, token_symbol: str) -> list[Trade]:
    """Closed valid trades for one user and one token symbol (for stats token breakdown)."""
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT trade_id, user_id, token_address, token_symbol, open_time, close_time,
               open_price, close_price, mcap_open, mcap_close, duration,
               emotion_open, emotion_open_note, reason_open, reason_open_note,
               token_category, token_category_note, risk_level,
               emotion_close, emotion_close_note, reason_close, reason_close_note,
               discipline, status
        FROM trades WHERE user_id = ? AND token_symbol = ? AND close_time IS NOT NULL AND status = 'valid'
        ORDER BY close_time DESC
        """,
        (user_id, token_symbol),
    )
    rows = await cursor.fetchall()
    return [Trade.from_row(tuple(r)) for r in rows]
