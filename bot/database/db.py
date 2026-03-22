import sqlite3
import time
import aiosqlite
from pathlib import Path
from typing import Any, Optional

from config import DB_PATH
from .models import Trade, PendingTrade, TradeExit

_db: Optional[aiosqlite.Connection] = None

_PREMIUM_STATUS_TTL = 8.0
_REFERRAL_DETAILED_TTL = 10.0
_LEADERBOARD_TTL = 25.0
_premium_status_cache: dict[int, tuple[float, dict]] = {}
_referral_detailed_cache: dict[int, tuple[float, dict]] = {}
_leaderboard_cache: tuple[float, list] | None = None


def invalidate_premium_status_cache(user_id: int) -> None:
    _premium_status_cache.pop(user_id, None)


def invalidate_referral_detailed_cache(user_id: int) -> None:
    _referral_detailed_cache.pop(user_id, None)


def invalidate_leaderboard_cache() -> None:
    global _leaderboard_cache
    _leaderboard_cache = None


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
    invalid_reason TEXT,
    open_quantity REAL,
    remaining_quantity REAL,
    trade_mode TEXT DEFAULT 'manual',
    network TEXT,
    open_value_usd REAL
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

WALLETS_SCHEMA = """
CREATE TABLE IF NOT EXISTS wallets (
    wallet_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    wallet_address TEXT NOT NULL,
    network TEXT NOT NULL,
    auto_tracking_enabled INTEGER NOT NULL DEFAULT 1,
    last_checked_signature TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wallets_user ON wallets(user_id);
"""

PENDING_TRADES_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token_address TEXT NOT NULL,
    symbol TEXT NOT NULL,
    network TEXT NOT NULL,
    amount REAL,
    tx_hash TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    mcap REAL,
    value_usd REAL
);
CREATE INDEX IF NOT EXISTS idx_pending_trades_user ON pending_trades(user_id);
CREATE INDEX IF NOT EXISTS idx_pending_trades_txhash ON pending_trades(tx_hash);
"""

CLOSED_TRADES_UNREVIEWED_SCHEMA = """
CREATE TABLE IF NOT EXISTS closed_trades_unreviewed (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token_address TEXT NOT NULL,
    symbol TEXT NOT NULL,
    network TEXT NOT NULL,
    buy_amount REAL,
    buy_tx_hash TEXT,
    buy_timestamp TEXT,
    buy_price_usd REAL,
    buy_value_usd REAL,
    buy_mcap REAL,
    sell_amount REAL,
    sell_tx_hash TEXT NOT NULL,
    sell_timestamp TEXT NOT NULL,
    sell_price_usd REAL,
    sell_value_usd REAL,
    sell_mcap REAL,
    status TEXT NOT NULL DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS idx_closed_unreviewed_user ON closed_trades_unreviewed(user_id);
CREATE INDEX IF NOT EXISTS idx_closed_unreviewed_txhash ON closed_trades_unreviewed(sell_tx_hash);
"""

TRADE_EXITS_SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_exits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    price REAL NOT NULL,
    value_usd REAL,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (trade_id) REFERENCES trades(trade_id)
);
CREATE INDEX IF NOT EXISTS idx_trade_exits_trade ON trade_exits(trade_id);
"""

PENDING_DCA_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_dca (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    trade_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    price REAL NOT NULL,
    value_usd REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pending_dca_user ON pending_dca(user_id);
"""

TOKEN_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS token_cache (
    token_address TEXT PRIMARY KEY,
    token_name TEXT,
    symbol TEXT,
    decimals INTEGER,
    chain TEXT,
    pair_address TEXT,
    price REAL,
    updated_at TEXT NOT NULL
);
"""

TOKEN_METADATA_SCHEMA = """
CREATE TABLE IF NOT EXISTS token_metadata (
    token_address TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    name TEXT,
    decimals INTEGER,
    chain TEXT,
    last_updated TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_token_metadata_chain ON token_metadata(chain);
"""

TOKEN_CATEGORIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS token_categories (
    user_id INTEGER NOT NULL,
    token_address TEXT NOT NULL,
    category TEXT NOT NULL,
    category_note TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, token_address)
);
CREATE INDEX IF NOT EXISTS idx_token_categories_user ON token_categories(user_id);
"""

TRADE_TIMELINE_SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_timeline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    value_usd REAL,
    amount REAL,
    note TEXT,
    created_at TEXT NOT NULL,
    price REAL,
    mcap REAL,
    FOREIGN KEY (trade_id) REFERENCES trades(trade_id)
);
CREATE INDEX IF NOT EXISTS idx_trade_timeline_trade ON trade_timeline(trade_id);
"""

TRADE_NOTES_SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    note_text TEXT,
    image_file_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (trade_id) REFERENCES trades(trade_id)
);
CREATE INDEX IF NOT EXISTS idx_trade_notes_trade ON trade_notes(trade_id);
CREATE INDEX IF NOT EXISTS idx_trade_notes_user ON trade_notes(user_id);
"""

PERSONAL_JOURNALS_SCHEMA = """
CREATE TABLE IF NOT EXISTS personal_journals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT,
    note_text TEXT,
    image_file_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_personal_journals_user ON personal_journals(user_id);
"""

USER_SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER PRIMARY KEY,
    timezone_offset INTEGER NOT NULL DEFAULT 0
);
"""

REFERRALS_SCHEMA = """
CREATE TABLE IF NOT EXISTS referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_id INTEGER NOT NULL,
    referred_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(referrer_id, referred_id)
);
CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id);
CREATE INDEX IF NOT EXISTS idx_referrals_referred ON referrals(referred_id);
"""

PAYMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    plan TEXT NOT NULL,
    amount_usd REAL NOT NULL,
    tx_hash TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
"""

SUPPORT_TICKETS_SCHEMA = """
CREATE TABLE IF NOT EXISTS support_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    image_file_id TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_support_tickets_status ON support_tickets(status);
CREATE INDEX IF NOT EXISTS idx_support_tickets_user ON support_tickets(user_id);
"""


async def init_db() -> None:
    db = await get_db()
    await db.executescript(TRADES_SCHEMA)
    await db.executescript(FEEDBACK_SCHEMA)
    await db.executescript(SYSTEM_SETTINGS_SCHEMA)
    await db.executescript(WALLETS_SCHEMA)
    await db.executescript(PENDING_TRADES_SCHEMA)
    await db.executescript(CLOSED_TRADES_UNREVIEWED_SCHEMA)
    await db.executescript(TRADE_EXITS_SCHEMA)
    await db.executescript(PENDING_DCA_SCHEMA)
    await db.executescript(TOKEN_CACHE_SCHEMA)
    await db.executescript(TOKEN_METADATA_SCHEMA)
    await db.executescript(TOKEN_CATEGORIES_SCHEMA)
    await db.executescript(TRADE_TIMELINE_SCHEMA)
    await db.executescript(TRADE_NOTES_SCHEMA)
    await db.executescript(PERSONAL_JOURNALS_SCHEMA)
    await db.executescript(USER_SETTINGS_SCHEMA)
    await db.executescript(REFERRALS_SCHEMA)
    await db.executescript(PAYMENTS_SCHEMA)
    await db.executescript(SUPPORT_TICKETS_SCHEMA)
    try:
        await db.execute("ALTER TABLE personal_journals ADD COLUMN title TEXT")
    except Exception:
        await db.rollback()
    try:
        await db.execute("ALTER TABLE personal_journals ADD COLUMN media_type TEXT")
    except Exception:
        await db.rollback()
    try:
        await db.execute("ALTER TABLE personal_journals ADD COLUMN media_file_ids TEXT")
    except Exception:
        await db.rollback()
    for col, col_type in [
        ("invalid_reason", "TEXT"),
        ("open_quantity", "REAL"),
        ("remaining_quantity", "REAL"),
        ("trade_mode", "TEXT DEFAULT 'manual'"),
        ("network", "TEXT"),
        ("open_value_usd", "REAL"),
        ("token_name", "TEXT"),
    ]:
        try:
            await db.execute(f"ALTER TABLE trades ADD COLUMN {col} {col_type}")
        except Exception:
            await db.rollback()
    try:
        await db.execute("ALTER TABLE pending_trades ADD COLUMN mcap REAL")
    except Exception:
        await db.rollback()
    try:
        await db.execute("ALTER TABLE pending_trades ADD COLUMN value_usd REAL")
    except Exception:
        await db.rollback()
    # closed_trades_unreviewed schema upgrades (additive)
    for col, col_type in [
        ("buy_amount", "REAL"),
        ("buy_tx_hash", "TEXT"),
        ("buy_timestamp", "TEXT"),
        ("buy_price_usd", "REAL"),
        ("buy_value_usd", "REAL"),
        ("buy_mcap", "REAL"),
        ("sell_amount", "REAL"),
        ("sell_tx_hash", "TEXT"),
        ("sell_timestamp", "TEXT"),
        ("sell_price_usd", "REAL"),
        ("sell_value_usd", "REAL"),
        ("sell_mcap", "REAL"),
    ]:
        try:
            await db.execute(f"ALTER TABLE closed_trades_unreviewed ADD COLUMN {col} {col_type}")
        except Exception:
            await db.rollback()
    try:
        await db.execute("ALTER TABLE user_settings ADD COLUMN is_premium INTEGER DEFAULT 0")
    except Exception:
        await db.rollback()
    try:
        await db.execute("ALTER TABLE user_settings ADD COLUMN plan TEXT")
    except Exception:
        await db.rollback()
    try:
        await db.execute("ALTER TABLE user_settings ADD COLUMN next_billing TEXT")
    except Exception:
        await db.rollback()
    try:
        await db.execute("ALTER TABLE user_settings ADD COLUMN premium_expires_at TEXT")
    except Exception:
        await db.rollback()
    try:
        await db.execute("ALTER TABLE user_settings ADD COLUMN plan_type TEXT")
    except Exception:
        await db.rollback()
    try:
        await db.execute("ALTER TABLE user_settings ADD COLUMN referral_days_earned INTEGER DEFAULT 0")
    except Exception:
        await db.rollback()
    try:
        await db.execute("ALTER TABLE user_settings ADD COLUMN referral_days_remaining INTEGER DEFAULT 0")
    except Exception:
        await db.rollback()
    try:
        await db.execute("ALTER TABLE user_settings ADD COLUMN referral_premium_expires_at TEXT")
    except Exception:
        await db.rollback()
    try:
        await db.execute("ALTER TABLE user_settings ADD COLUMN invited_by INTEGER")
    except Exception:
        await db.rollback()
    try:
        await db.execute("ALTER TABLE pending_trades ADD COLUMN created_at TEXT")
    except Exception:
        await db.rollback()
    for col, col_type in [
        ("price", "REAL"),
        ("mcap", "REAL"),
    ]:
        try:
            await db.execute(f"ALTER TABLE trade_timeline ADD COLUMN {col} {col_type}")
        except Exception:
            await db.rollback()
    try:
        await db.execute("ALTER TABLE wallets ADD COLUMN last_checked_signature TEXT")
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
            user_id, token_address, token_symbol, token_name, open_time, close_time,
            open_price, close_price, mcap_open, mcap_close, duration,
            emotion_open, emotion_open_note, reason_open, reason_open_note,
            token_category, token_category_note, risk_level,
            emotion_close, emotion_close_note, reason_close, reason_close_note,
            discipline, status, open_quantity, remaining_quantity,
            trade_mode, network, open_value_usd
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


async def update_trade_remaining_quantity(trade_id: int, remaining_quantity: float) -> None:
    """Update remaining_quantity for partial close."""
    db = await get_db()
    await db.execute(
        "UPDATE trades SET remaining_quantity = ? WHERE trade_id = ?",
        (remaining_quantity, trade_id),
    )
    await db.commit()


async def update_trade_emotion_close(trade_id: int, user_id: int, emotion_close: str, emotion_close_note: Optional[str] = None) -> bool:
    """Update emotion_close for a trade (e.g. after auto-close prompt). Returns True if updated."""
    db = await get_db()
    cursor = await db.execute(
        "UPDATE trades SET emotion_close = ?, emotion_close_note = ? WHERE trade_id = ? AND user_id = ?",
        (emotion_close, emotion_close_note or None, trade_id, user_id),
    )
    await db.commit()
    return cursor.rowcount > 0


async def update_trade_reason_close(trade_id: int, user_id: int, reason_close: str, reason_close_note: Optional[str] = None) -> bool:
    """Update reason_close for a trade (e.g. after auto-close flow). Returns True if updated."""
    db = await get_db()
    cursor = await db.execute(
        "UPDATE trades SET reason_close = ?, reason_close_note = ? WHERE trade_id = ? AND user_id = ?",
        (reason_close, reason_close_note or None, trade_id, user_id),
    )
    await db.commit()
    return cursor.rowcount > 0


async def update_trade_discipline(trade_id: int, user_id: int, discipline: str) -> bool:
    """Update discipline for a trade (e.g. after auto-close flow). Returns True if updated."""
    db = await get_db()
    cursor = await db.execute(
        "UPDATE trades SET discipline = ? WHERE trade_id = ? AND user_id = ?",
        (discipline, trade_id, user_id),
    )
    await db.commit()
    return cursor.rowcount > 0


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
        SELECT trade_id, user_id, token_address, token_symbol, token_name, open_time, close_time,
               open_price, close_price, mcap_open, mcap_close, duration,
               emotion_open, emotion_open_note, reason_open, reason_open_note,
               token_category, token_category_note, risk_level,
               emotion_close, emotion_close_note, reason_close, reason_close_note,
               discipline, status, open_quantity, remaining_quantity,
               trade_mode, network, open_value_usd
        FROM trades WHERE user_id = ? AND close_time IS NULL AND status = 'valid'
        ORDER BY open_time DESC
        """,
        (user_id,),
    )
    rows = await cursor.fetchall()
    return [Trade.from_row(tuple(r)) for r in rows]


async def get_open_trade_for_token(user_id: int, token_address: str, network: Optional[str] = None) -> Optional[Trade]:
    db = await get_db()
    token_key = (token_address or "").lower()
    if network:
        cursor = await db.execute(
            """
            SELECT trade_id, user_id, token_address, token_symbol, token_name, open_time, close_time,
                   open_price, close_price, mcap_open, mcap_close, duration,
                   emotion_open, emotion_open_note, reason_open, reason_open_note,
                   token_category, token_category_note, risk_level,
                   emotion_close, emotion_close_note, reason_close, reason_close_note,
                   discipline, status, open_quantity, remaining_quantity,
                   trade_mode, network, open_value_usd
            FROM trades
            WHERE user_id = ? AND token_address = ? AND network = ? AND close_time IS NULL AND status = 'valid'
            """,
            (user_id, token_key, network),
        )
    else:
        cursor = await db.execute(
            """
            SELECT trade_id, user_id, token_address, token_symbol, token_name, open_time, close_time,
                   open_price, close_price, mcap_open, mcap_close, duration,
                   emotion_open, emotion_open_note, reason_open, reason_open_note,
                   token_category, token_category_note, risk_level,
                   emotion_close, emotion_close_note, reason_close, reason_close_note,
                   discipline, status, open_quantity, remaining_quantity,
                   trade_mode, network, open_value_usd
            FROM trades WHERE user_id = ? AND token_address = ? AND close_time IS NULL AND status = 'valid'
            """,
            (user_id, token_key),
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
        SELECT trade_id, user_id, token_address, token_symbol, token_name, open_time, close_time,
               open_price, close_price, mcap_open, mcap_close, duration,
               emotion_open, emotion_open_note, reason_open, reason_open_note,
               token_category, token_category_note, risk_level,
               emotion_close, emotion_close_note, reason_close, reason_close_note,
               discipline, status, open_quantity, remaining_quantity,
               trade_mode, network, open_value_usd
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
        SELECT trade_id, user_id, token_address, token_symbol, token_name, open_time, close_time,
               open_price, close_price, mcap_open, mcap_close, duration,
               emotion_open, emotion_open_note, reason_open, reason_open_note,
               token_category, token_category_note, risk_level,
               emotion_close, emotion_close_note, reason_close, reason_close_note,
               discipline, status, open_quantity, remaining_quantity,
               trade_mode, network, open_value_usd
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
        SELECT trade_id, user_id, token_address, token_symbol, token_name, open_time, close_time,
               open_price, close_price, mcap_open, mcap_close, duration,
               emotion_open, emotion_open_note, reason_open, reason_open_note,
               token_category, token_category_note, risk_level,
               emotion_close, emotion_close_note, reason_close, reason_close_note,
               discipline, status, open_quantity, remaining_quantity,
               trade_mode, network, open_value_usd
        FROM trades WHERE user_id = ? AND status = 'valid' AND close_time IS NOT NULL
        ORDER BY close_time DESC
        """,
        (user_id,),
    )
    rows = await cursor.fetchall()
    return [Trade.from_row(tuple(r)) for r in rows]


async def get_valid_trades_for_stats_by_network(user_id: int, network: str) -> list[Trade]:
    """DB-level stats filter by network (closed + valid only)."""
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT trade_id, user_id, token_address, token_symbol, token_name, open_time, close_time,
               open_price, close_price, mcap_open, mcap_close, duration,
               emotion_open, emotion_open_note, reason_open, reason_open_note,
               token_category, token_category_note, risk_level,
               emotion_close, emotion_close_note, reason_close, reason_close_note,
               discipline, status, open_quantity, remaining_quantity,
               trade_mode, network, open_value_usd
        FROM trades
        WHERE user_id = ? AND status = 'valid' AND close_time IS NOT NULL AND network = ?
        ORDER BY close_time DESC
        """,
        (user_id, network),
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
        SELECT trade_id, user_id, token_address, token_symbol, token_name, open_time, close_time,
               open_price, close_price, mcap_open, mcap_close, duration,
               emotion_open, emotion_open_note, reason_open, reason_open_note,
               token_category, token_category_note, risk_level,
               emotion_close, emotion_close_note, reason_close, reason_close_note,
               discipline, status, open_quantity, remaining_quantity,
               trade_mode, network, open_value_usd
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
        SELECT trade_id, user_id, token_address, token_symbol, token_name, open_time, close_time,
               open_price, close_price, mcap_open, mcap_close, duration,
               emotion_open, emotion_open_note, reason_open, reason_open_note,
               token_category, token_category_note, risk_level,
               emotion_close, emotion_close_note, reason_close, reason_close_note,
               discipline, status, open_quantity, remaining_quantity,
               trade_mode, network, open_value_usd
        FROM trades WHERE user_id = ? AND token_symbol = ? AND close_time IS NOT NULL AND status = 'valid'
        ORDER BY close_time DESC
        """,
        (user_id, token_symbol),
    )
    rows = await cursor.fetchall()
    return [Trade.from_row(tuple(r)) for r in rows]


async def get_closed_trades_by_token_network(user_id: int, token_symbol: str, network: str) -> list[Trade]:
    """Closed valid trades for one user/token, filtered by network (DB-level)."""
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT trade_id, user_id, token_address, token_symbol, token_name, open_time, close_time,
               open_price, close_price, mcap_open, mcap_close, duration,
               emotion_open, emotion_open_note, reason_open, reason_open_note,
               token_category, token_category_note, risk_level,
               emotion_close, emotion_close_note, reason_close, reason_close_note,
               discipline, status, open_quantity, remaining_quantity,
               trade_mode, network, open_value_usd
        FROM trades
        WHERE user_id = ? AND token_symbol = ? AND network = ? AND close_time IS NOT NULL AND status = 'valid'
        ORDER BY close_time DESC
        """,
        (user_id, token_symbol, network),
    )
    rows = await cursor.fetchall()
    return [Trade.from_row(tuple(r)) for r in rows]


async def delete_trade_and_exits(trade_id: int, user_id: int) -> bool:
    """
    Delete a single trade and its related trade_exits for the same user.
    Returns True if trade row was deleted.
    """
    db = await get_db()
    await db.execute("DELETE FROM trade_exits WHERE trade_id = ?", (trade_id,))
    cur = await db.execute("DELETE FROM trades WHERE trade_id = ? AND user_id = ?", (trade_id, user_id))
    await db.commit()
    return bool(getattr(cur, "rowcount", 0))


async def get_analytics_user_activity() -> dict:
    """Total users, active 1D/7D/30D from trades. Times in UTC."""
    from datetime import datetime, timedelta
    db = await get_db()
    now = datetime.utcnow()
    since_1d = (now - timedelta(days=1)).isoformat()
    since_7d = (now - timedelta(days=7)).isoformat()
    since_30d = (now - timedelta(days=30)).isoformat()
    cursor = await db.execute(
        "SELECT COUNT(DISTINCT user_id) FROM trades"
    )
    total = (await cursor.fetchone())[0]
    cursor = await db.execute(
        """SELECT COUNT(DISTINCT user_id) FROM trades
           WHERE open_time >= ? OR close_time >= ?""",
        (since_1d, since_1d),
    )
    active_1d = (await cursor.fetchone())[0]
    cursor = await db.execute(
        """SELECT COUNT(DISTINCT user_id) FROM trades
           WHERE open_time >= ? OR close_time >= ?""",
        (since_7d, since_7d),
    )
    active_7d = (await cursor.fetchone())[0]
    cursor = await db.execute(
        """SELECT COUNT(DISTINCT user_id) FROM trades
           WHERE open_time >= ? OR close_time >= ?""",
        (since_30d, since_30d),
    )
    active_30d = (await cursor.fetchone())[0]
    return {"total_users": total, "active_1d": active_1d, "active_7d": active_7d, "active_30d": active_30d}


async def get_all_broadcast_user_ids() -> list[int]:
    """Return distinct user_id from trades, feedback, user_settings, wallets for admin broadcast."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT DISTINCT user_id FROM (
            SELECT user_id FROM trades
            UNION SELECT user_id FROM feedback
            UNION SELECT user_id FROM user_settings
            UNION SELECT user_id FROM wallets
        )"""
    )
    rows = await cursor.fetchall()
    return [r[0] for r in rows if r and r[0]]


async def get_analytics_trade_stats() -> dict:
    """Total valid, closed, open, invalid %, avg duration."""
    db = await get_db()
    cursor = await db.execute("SELECT COUNT(*) FROM trades WHERE status = 'valid'")
    valid = (await cursor.fetchone())[0]
    cursor = await db.execute(
        "SELECT COUNT(*) FROM trades WHERE status = 'valid' AND close_time IS NOT NULL"
    )
    closed = (await cursor.fetchone())[0]
    cursor = await db.execute(
        "SELECT COUNT(*) FROM trades WHERE close_time IS NULL"
    )
    open_count = (await cursor.fetchone())[0]
    cursor = await db.execute("SELECT COUNT(*) FROM trades")
    total = (await cursor.fetchone())[0]
    invalid_pct = (100.0 * (total - valid) / total) if total else 0.0
    cursor = await db.execute(
        "SELECT AVG(duration) FROM trades WHERE status = 'valid' AND close_time IS NOT NULL AND duration IS NOT NULL"
    )
    row = await cursor.fetchone()
    avg_duration = row[0] if row and row[0] is not None else 0
    return {
        "total_valid": valid,
        "closed": closed,
        "open": open_count,
        "invalid_pct": invalid_pct,
        "avg_duration_min": round(avg_duration, 1) if avg_duration else 0,
    }


async def get_analytics_psychology_stats() -> dict:
    """Emotion open/close fill rate, most used emotion, worst emotion by avg pnl."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT COUNT(*), SUM(CASE WHEN emotion_open IS NOT NULL AND emotion_open != '' THEN 1 ELSE 0 END)
           FROM trades WHERE status = 'valid' AND close_time IS NOT NULL"""
    )
    row = await cursor.fetchone()
    total_closed = row[0] or 0
    filled_open = row[1] or 0
    emotion_open_rate = (100.0 * filled_open / total_closed) if total_closed else 0
    cursor = await db.execute(
        """SELECT COUNT(*), SUM(CASE WHEN emotion_close IS NOT NULL AND emotion_close != '' THEN 1 ELSE 0 END)
           FROM trades WHERE status = 'valid' AND close_time IS NOT NULL"""
    )
    row = await cursor.fetchone()
    filled_close = row[1] or 0
    emotion_close_rate = (100.0 * filled_close / total_closed) if total_closed else 0
    cursor = await db.execute(
        """SELECT emotion_open, COUNT(*) as c FROM trades
           WHERE status = 'valid' AND emotion_open IS NOT NULL AND emotion_open != ''
           GROUP BY emotion_open ORDER BY c DESC LIMIT 1"""
    )
    row = await cursor.fetchone()
    most_used = row[0] if row else "—"
    cursor = await db.execute(
        """SELECT emotion_open,
           AVG(CASE WHEN open_price > 0 THEN 100.0 * (close_price - open_price) / open_price ELSE 0 END) as avg_pnl
           FROM trades WHERE status = 'valid' AND close_time IS NOT NULL AND open_price IS NOT NULL AND close_price IS NOT NULL
           AND emotion_open IS NOT NULL AND emotion_open != ''
           GROUP BY emotion_open ORDER BY avg_pnl ASC LIMIT 1"""
    )
    row = await cursor.fetchone()
    worst_emotion = row[0] if row else "—"
    worst_avg_pnl = round(row[1], 1) if row and row[1] is not None else "—"
    return {
        "emotion_open_rate": round(emotion_open_rate, 1),
        "emotion_close_rate": round(emotion_close_rate, 1),
        "most_used_emotion": most_used,
        "worst_emotion": worst_emotion,
        "worst_avg_pnl": worst_avg_pnl,
    }


# --- Wallets (Wallet Auto Trade Detection) ---


async def insert_wallet(user_id: int, wallet_address: str, network: str) -> int:
    """Insert a wallet. Returns wallet_id."""
    from datetime import datetime
    db = await get_db()
    await db.execute(
        """INSERT INTO wallets (user_id, wallet_address, network, auto_tracking_enabled, created_at)
           VALUES (?, ?, ?, 1, ?)""",
        (user_id, wallet_address.strip(), network, datetime.utcnow().isoformat()),
    )
    await db.commit()
    cursor = await db.execute("SELECT last_insert_rowid()")
    row = await cursor.fetchone()
    return row[0]


async def get_user_wallets(user_id: int) -> list[tuple]:
    """Return list of (wallet_id, user_id, wallet_address, network, auto_tracking_enabled, created_at)."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT wallet_id, user_id, wallet_address, network, auto_tracking_enabled, created_at
           FROM wallets WHERE user_id = ? ORDER BY created_at DESC""",
        (user_id,),
    )
    return [tuple(r) for r in await cursor.fetchall()]


async def get_all_tracked_wallets() -> list[tuple]:
    """Return all wallets with auto_tracking_enabled=1: (wallet_id, user_id, wallet_address, network, last_checked_signature)."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT wallet_id, user_id, wallet_address, network, last_checked_signature
           FROM wallets WHERE auto_tracking_enabled = 1 ORDER BY wallet_id""",
    )
    return [tuple(r) for r in await cursor.fetchall()]


async def update_last_signature(wallet_id: int, signature: str) -> None:
    """Update last_checked_signature for a wallet (used by monitor)."""
    db = await get_db()
    await db.execute(
        "UPDATE wallets SET last_checked_signature = ? WHERE wallet_id = ?",
        (signature or "", wallet_id),
    )
    await db.commit()


async def remove_wallet(wallet_id: int, user_id: int) -> bool:
    """Remove wallet if it belongs to user. Returns True if deleted."""
    db = await get_db()
    cursor = await db.execute("DELETE FROM wallets WHERE wallet_id = ? AND user_id = ?", (wallet_id, user_id))
    await db.commit()
    return cursor.rowcount > 0


async def toggle_auto_tracking(wallet_id: int, user_id: int) -> bool:
    """Toggle auto_tracking_enabled for wallet. Returns new state (True=enabled)."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT auto_tracking_enabled FROM wallets WHERE wallet_id = ? AND user_id = ?",
        (wallet_id, user_id),
    )
    row = await cursor.fetchone()
    if not row:
        return False
    new_val = 0 if row[0] else 1
    await db.execute(
        "UPDATE wallets SET auto_tracking_enabled = ? WHERE wallet_id = ? AND user_id = ?",
        (new_val, wallet_id, user_id),
    )
    await db.commit()
    return bool(new_val)


# --- Pending Trades (detection queue — PART 1) ---


async def insert_pending_trade(pt: PendingTrade) -> int:
    """Insert a pending trade. Returns id. Stores mcap and value_usd when provided (at detection). Sets created_at for cleanup."""
    from datetime import datetime
    db = await get_db()
    now_utc = datetime.utcnow().isoformat()
    try:
        await db.execute(
            """INSERT INTO pending_trades (user_id, token_address, symbol, network, amount, tx_hash, timestamp, status, mcap, value_usd, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pt.user_id, pt.token_address, pt.symbol, pt.network, pt.amount, pt.tx_hash, pt.timestamp, pt.status, getattr(pt, "mcap", None), getattr(pt, "value_usd", None), now_utc),
        )
    except Exception:
        await db.execute(
            """INSERT INTO pending_trades (user_id, token_address, symbol, network, amount, tx_hash, timestamp, status, mcap, value_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pt.user_id, pt.token_address, pt.symbol, pt.network, pt.amount, pt.tx_hash, pt.timestamp, pt.status, getattr(pt, "mcap", None), getattr(pt, "value_usd", None)),
        )
    await db.commit()
    cursor = await db.execute("SELECT last_insert_rowid()")
    return (await cursor.fetchone())[0]


async def pending_trade_exists(user_id: int, tx_hash: str) -> bool:
    """Check if a pending trade with this tx_hash already exists for the user."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT 1 FROM pending_trades WHERE user_id = ? AND tx_hash = ? LIMIT 1",
        (user_id, tx_hash),
    )
    return (await cursor.fetchone()) is not None


async def get_pending_trade_by_token(user_id: int, token_address: str, network: str) -> Optional[PendingTrade]:
    """Return an unreviewed detected trade for (user_id, token_address, network)."""
    if not token_address or not network:
        return None
    key = (token_address or "").strip().lower() if (token_address or "").strip().startswith("0x") else (token_address or "").strip()
    db = await get_db()
    cursor = await db.execute(
        """SELECT id, user_id, token_address, symbol, network, amount, tx_hash, timestamp, status, mcap, value_usd
           FROM pending_trades
           WHERE user_id = ?
             AND LOWER(TRIM(COALESCE(token_address,''))) = ?
             AND network = ?
             AND status IN ('inbox','pending')
           ORDER BY id ASC LIMIT 1""",
        (user_id, key, network),
    )
    r = await cursor.fetchone()
    if not r:
        return None
    return PendingTrade(
        id=r[0], user_id=r[1], token_address=r[2], symbol=r[3],
        network=r[4], amount=r[5], tx_hash=r[6], timestamp=r[7], status=r[8],
        mcap=r[9] if len(r) > 9 else None,
        value_usd=r[10] if len(r) > 10 else None,
    )


async def update_pending_trade_merge(
    pending_id: int, add_amount: float, new_tx_hash: Optional[str] = None, add_value_usd: Optional[float] = None
) -> None:
    """Merge an additional buy into an existing pending trade and always accumulate value_usd."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT amount, value_usd FROM pending_trades WHERE id = ? LIMIT 1",
        (pending_id,),
    )
    row = await cursor.fetchone()
    existing_amount = float(row[0] or 0.0) if row else 0.0
    existing_value_raw = row[1] if row else None
    existing_value = float(existing_value_raw or 0.0) if row else 0.0
    add_value = add_value_usd
    if add_value is None:
        # Fallback to previous average price when no fresh value is available.
        avg_price = (existing_value / existing_amount) if existing_amount > 0 else 0.0
        add_value = float(add_amount or 0.0) * avg_price if avg_price > 0 else None
    if existing_value_raw is None and add_value is None:
        new_value_total = None
    else:
        new_value_total = existing_value + float(add_value or 0.0)
    if new_tx_hash is not None:
        from datetime import datetime
        await db.execute(
            "UPDATE pending_trades SET amount = amount + ?, value_usd = ?, tx_hash = ?, timestamp = ? WHERE id = ?",
            (add_amount, new_value_total, new_tx_hash, datetime.utcnow().isoformat(), pending_id),
        )
    else:
        await db.execute(
            "UPDATE pending_trades SET amount = amount + ?, value_usd = ? WHERE id = ?",
            (add_amount, new_value_total, pending_id),
        )
    await db.commit()


async def get_pending_trades(user_id: int) -> list[PendingTrade]:
    """Return all pending (unresolved) trades for a user."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT id, user_id, token_address, symbol, network, amount, tx_hash, timestamp, status, mcap, value_usd
           FROM pending_trades WHERE user_id = ? AND status = 'pending'
           ORDER BY id DESC""",
        (user_id,),
    )
    rows = await cursor.fetchall()
    return [
        PendingTrade(
            id=r[0], user_id=r[1], token_address=r[2], symbol=r[3],
            network=r[4], amount=r[5], tx_hash=r[6], timestamp=r[7], status=r[8],
            mcap=r[9] if len(r) > 9 else None,
            value_usd=r[10] if len(r) > 10 else None,
        )
        for r in rows
    ]


async def insert_closed_trade_unreviewed(
    user_id: int,
    token_address: str,
    symbol: str,
    network: str,
    amount: float | None,
    tx_hash: str,
    timestamp: str,
    price_usd: float | None = None,
    value_usd: float | None = None,
    mcap: float | None = None,
) -> int:
    """Insert a CLOSED trade into unreviewed queue (idempotent by tx_hash). Returns row id (existing or new)."""
    db = await get_db()
    cur = await db.execute(
        "SELECT id FROM closed_trades_unreviewed WHERE user_id = ? AND tx_hash = ? LIMIT 1",
        (user_id, tx_hash),
    )
    row = await cur.fetchone()
    if row:
        return int(row[0])
    await db.execute(
        """INSERT INTO closed_trades_unreviewed
           (user_id, token_address, symbol, network, amount, tx_hash, timestamp, price_usd, value_usd, mcap, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
        (user_id, token_address, symbol, network, amount, tx_hash, timestamp, price_usd, value_usd, mcap),
    )
    cur2 = await db.execute("SELECT last_insert_rowid()")
    rid = await cur2.fetchone()
    await db.commit()
    return int(rid[0]) if rid else 0


async def get_closed_trades_unreviewed(user_id: int, limit: int = 20) -> list[dict]:
    """List closed trades awaiting review (pending status only)."""
    db = await get_db()
    cur = await db.execute(
        """SELECT id, token_address, symbol, network, amount, tx_hash, timestamp, price_usd, value_usd, mcap
           FROM closed_trades_unreviewed
           WHERE user_id = ? AND status = 'pending'
           ORDER BY id DESC
           LIMIT ?""",
        (user_id, limit),
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows] if rows else []


async def get_closed_trade_unreviewed_by_id(user_id: int, row_id: int) -> dict | None:
    db = await get_db()
    cur = await db.execute(
        """SELECT id, token_address, symbol, network, amount, tx_hash, timestamp, price_usd, value_usd, mcap, status
           FROM closed_trades_unreviewed
           WHERE user_id = ? AND id = ? LIMIT 1""",
        (user_id, row_id),
    )
    r = await cur.fetchone()
    return dict(r) if r else None


async def resolve_closed_trade_unreviewed(user_id: int, row_id: int, status: str) -> None:
    """Mark unreviewed closed trade as recorded/ignored."""
    db = await get_db()
    await db.execute(
        "UPDATE closed_trades_unreviewed SET status = ? WHERE user_id = ? AND id = ?",
        (status, user_id, row_id),
    )
    await db.commit()


async def get_pending_trade_by_id(pending_id: int) -> Optional[PendingTrade]:
    db = await get_db()
    cursor = await db.execute(
        """SELECT id, user_id, token_address, symbol, network, amount, tx_hash, timestamp, status, mcap, value_usd
           FROM pending_trades WHERE id = ?""",
        (pending_id,),
    )
    r = await cursor.fetchone()
    if not r:
        return None
    return PendingTrade(
        id=r[0], user_id=r[1], token_address=r[2], symbol=r[3],
        network=r[4], amount=r[5], tx_hash=r[6], timestamp=r[7], status=r[8],
        mcap=r[9] if len(r) > 9 else None,
        value_usd=r[10] if len(r) > 10 else None,
    )


async def update_pending_trade_status(pending_id: int, status: str) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE pending_trades SET status = ? WHERE id = ?", (status, pending_id),
    )
    await db.commit()


async def delete_pending_trade(pending_id: int) -> None:
    db = await get_db()
    await db.execute("DELETE FROM pending_trades WHERE id = ?", (pending_id,))
    await db.commit()


async def insert_closed_trade_unreviewed_from_pair(
    user_id: int,
    token_address: str,
    symbol: str,
    network: str,
    buy: PendingTrade | None,
    sell_amount: float | None,
    sell_tx_hash: str,
    sell_timestamp: str,
    sell_price_usd: float | None = None,
    sell_value_usd: float | None = None,
    sell_mcap: float | None = None,
) -> int:
    """Insert a paired BUY+SELL into closed_trades_unreviewed (idempotent by sell_tx_hash)."""
    db = await get_db()
    cur = await db.execute(
        "SELECT id FROM closed_trades_unreviewed WHERE user_id = ? AND sell_tx_hash = ? LIMIT 1",
        (user_id, sell_tx_hash),
    )
    row = await cur.fetchone()
    if row:
        return int(row[0])
    await db.execute(
        """INSERT INTO closed_trades_unreviewed
           (user_id, token_address, symbol, network,
            buy_amount, buy_tx_hash, buy_timestamp, buy_price_usd, buy_value_usd, buy_mcap,
            sell_amount, sell_tx_hash, sell_timestamp, sell_price_usd, sell_value_usd, sell_mcap,
            status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
        (
            user_id,
            token_address,
            symbol,
            network,
            (buy.amount if buy else None),
            (buy.tx_hash if buy else None),
            (buy.timestamp if buy else None),
            None,
            (getattr(buy, "value_usd", None) if buy else None),
            (getattr(buy, "mcap", None) if buy else None),
            sell_amount,
            sell_tx_hash,
            sell_timestamp,
            sell_price_usd,
            sell_value_usd,
            sell_mcap,
        ),
    )
    cur2 = await db.execute("SELECT last_insert_rowid()")
    rid = await cur2.fetchone()
    await db.commit()
    return int(rid[0]) if rid else 0


async def get_closed_trades_unreviewed(user_id: int, limit: int = 20) -> list[dict]:
    db = await get_db()
    cur = await db.execute(
        """SELECT id, token_address, symbol, network,
                  buy_amount, buy_timestamp,
                  sell_amount, sell_timestamp
           FROM closed_trades_unreviewed
           WHERE user_id = ? AND status = 'pending'
           ORDER BY id DESC
           LIMIT ?""",
        (user_id, limit),
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows] if rows else []


async def get_closed_trade_unreviewed_by_id(user_id: int, row_id: int) -> dict | None:
    db = await get_db()
    cur = await db.execute(
        """SELECT *
           FROM closed_trades_unreviewed
           WHERE user_id = ? AND id = ? LIMIT 1""",
        (user_id, row_id),
    )
    r = await cur.fetchone()
    return dict(r) if r else None


async def resolve_closed_trade_unreviewed(user_id: int, row_id: int, status: str) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE closed_trades_unreviewed SET status = ? WHERE user_id = ? AND id = ?",
        (status, user_id, row_id),
    )
    await db.commit()


async def cleanup_trade_center_older_than_hours(hours: float = 24.0) -> int:
    """Delete pending open-trade detections and unreviewed closes older than hours (pending status only)."""
    from datetime import datetime, timedelta

    db = await get_db()
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    # Pending trades (open-only)
    cur1 = await db.execute(
        "DELETE FROM pending_trades WHERE status IN ('inbox','pending') AND timestamp < ?",
        (cutoff,),
    )
    # Closed unreviewed (paired closes)
    cur2 = await db.execute(
        "DELETE FROM closed_trades_unreviewed WHERE status = 'pending' AND sell_timestamp < ?",
        (cutoff,),
    )
    await db.commit()
    return int(getattr(cur1, "rowcount", 0) or 0) + int(getattr(cur2, "rowcount", 0) or 0)


async def cleanup_pending_trades_older_than_hours(hours: float = 1.0) -> int:
    """Delete pending trades (status='pending') older than given hours. Returns count deleted. No notification."""
    from datetime import datetime, timedelta
    db = await get_db()
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    cursor = await db.execute(
        """DELETE FROM pending_trades
           WHERE status = 'pending' AND (created_at IS NULL OR created_at < ?)""",
        (cutoff,),
    )
    await db.commit()
    return cursor.rowcount


async def get_ignored_pendings_for_token(
    user_id: int, token_address: str, network: str, within_minutes: int = 120
) -> list[PendingTrade]:
    """Return ignored pending trades for same token+network within the last within_minutes (for merge on Record)."""
    if not token_address or not network:
        return []
    from datetime import datetime, timedelta
    key = (token_address or "").strip().lower() if (token_address or "").strip().startswith("0x") else (token_address or "").strip()
    since = (datetime.utcnow() - timedelta(minutes=within_minutes)).isoformat()
    db = await get_db()
    cursor = await db.execute(
        """SELECT id, user_id, token_address, symbol, network, amount, tx_hash, timestamp, status, mcap, value_usd
           FROM pending_trades WHERE user_id = ? AND LOWER(TRIM(COALESCE(token_address,''))) = ? AND network = ?
           AND status = 'ignored' AND timestamp >= ?
           ORDER BY id ASC""",
        (user_id, key, network, since),
    )
    rows = await cursor.fetchall()
    return [
        PendingTrade(
            id=r[0], user_id=r[1], token_address=r[2], symbol=r[3],
            network=r[4], amount=r[5], tx_hash=r[6], timestamp=r[7], status=r[8],
            mcap=r[9] if len(r) > 9 else None,
            value_usd=r[10] if len(r) > 10 else None,
        )
        for r in rows
    ]


# --- Trade Exits (partial close tracking — PART 5) ---


async def insert_trade_exit(te: TradeExit) -> int:
    """Insert trade exit. Ensures value_usd is always set (amount * price) for consistency with SUM(value_usd)."""
    value_usd = te.value_usd
    if value_usd is None:
        value_usd = (te.amount or 0) * (te.price or 0)
    db = await get_db()
    await db.execute(
        """INSERT INTO trade_exits (trade_id, amount, price, value_usd, timestamp)
           VALUES (?, ?, ?, ?, ?)""",
        (te.trade_id, te.amount, te.price, value_usd, te.timestamp),
    )
    await db.commit()
    cursor = await db.execute("SELECT last_insert_rowid()")
    return (await cursor.fetchone())[0]


async def get_trade_exits(trade_id: int) -> list[TradeExit]:
    db = await get_db()
    cursor = await db.execute(
        """SELECT id, trade_id, amount, price, value_usd, timestamp
           FROM trade_exits WHERE trade_id = ? ORDER BY id ASC""",
        (trade_id,),
    )
    rows = await cursor.fetchall()
    return [
        TradeExit(id=r[0], trade_id=r[1], amount=r[2], price=r[3], value_usd=r[4], timestamp=r[5])
        for r in rows
    ]


async def get_exit_totals_for_trades(trade_ids: list[int]) -> dict[int, float]:
    """Return total exit value_usd per trade_id (for PnL: exit_total). Keys only for trades that have exits."""
    if not trade_ids:
        return {}
    db = await get_db()
    placeholders = ",".join("?" * len(trade_ids))
    cursor = await db.execute(
        f"SELECT trade_id, COALESCE(SUM(value_usd), 0) FROM trade_exits WHERE trade_id IN ({placeholders}) GROUP BY trade_id",
        tuple(trade_ids),
    )
    rows = await cursor.fetchall()
    return {r[0]: float(r[1] or 0) for r in rows}


async def insert_pending_dca(user_id: int, trade_id: int, amount: float, price: float, value_usd: Optional[float]) -> int:
    """Store a pending DCA for user to confirm. Returns pending_dca id."""
    from datetime import datetime
    db = await get_db()
    await db.execute(
        """INSERT INTO pending_dca (user_id, trade_id, amount, price, value_usd, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, trade_id, amount, price, value_usd, datetime.utcnow().isoformat()),
    )
    await db.commit()
    cursor = await db.execute("SELECT last_insert_rowid()")
    return (await cursor.fetchone())[0]


async def get_pending_dca_by_id(pending_dca_id: int):
    """Return (user_id, trade_id, amount, price, value_usd) or None."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT user_id, trade_id, amount, price, value_usd FROM pending_dca WHERE id = ?",
        (pending_dca_id,),
    )
    row = await cursor.fetchone()
    return tuple(row) if row else None


async def delete_pending_dca(pending_dca_id: int) -> None:
    db = await get_db()
    await db.execute("DELETE FROM pending_dca WHERE id = ?", (pending_dca_id,))
    await db.commit()


# --- Token metadata cache ---

async def get_token_from_cache(token_address: str):
    """Return cached token row (token_address, token_name, symbol, decimals, chain, pair_address, price, updated_at) or None."""
    if not token_address or len(str(token_address).strip()) < 10:
        return None
    key = (token_address or "").strip().lower() if (token_address or "").strip().startswith("0x") else (token_address or "").strip()
    db = await get_db()
    cursor = await db.execute(
        "SELECT token_address, token_name, symbol, decimals, chain, pair_address, price, updated_at FROM token_cache WHERE token_address = ?",
        (key,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return {
        "token_address": row[0],
        "token_name": row[1],
        "symbol": row[2],
        "decimals": row[3],
        "chain": row[4],
        "pair_address": row[5],
        "price": row[6],
        "updated_at": row[7],
    }


async def set_token_metadata(
    token_address: str,
    symbol: str,
    name: Optional[str] = None,
    decimals: Optional[int] = None,
    chain: Optional[str] = None,
) -> None:
    """Upsert token_metadata for display (avoids $Unknown)."""
    from datetime import datetime
    if not token_address or len(str(token_address).strip()) < 10:
        return
    key = (token_address or "").strip().lower() if (token_address or "").strip().startswith("0x") else (token_address or "").strip()
    db = await get_db()
    now = datetime.utcnow().isoformat()
    await db.execute(
        """INSERT INTO token_metadata (token_address, symbol, name, decimals, chain, last_updated)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(token_address) DO UPDATE SET
             symbol=excluded.symbol, name=excluded.name, decimals=excluded.decimals,
             chain=excluded.chain, last_updated=excluded.last_updated""",
        (key, symbol or "?", name, decimals, chain, now),
    )
    await db.commit()


async def get_token_metadata(token_address: str):
    """Return dict with symbol, name, decimals, chain from token_metadata, or None."""
    if not token_address or len(str(token_address).strip()) < 10:
        return None
    key = (token_address or "").strip().lower() if (token_address or "").strip().startswith("0x") else (token_address or "").strip()
    db = await get_db()
    cursor = await db.execute(
        "SELECT symbol, name, decimals, chain FROM token_metadata WHERE token_address = ?",
        (key,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return {"symbol": row[0] or "?", "name": row[1], "decimals": row[2], "chain": row[3]}


async def get_token_category(user_id: int, token_address: str) -> Optional[tuple]:
    """Return (category, category_note) for (user_id, token_address), or None."""
    if not token_address or len(str(token_address).strip()) < 10:
        return None
    key = (token_address or "").strip().lower() if (token_address or "").strip().startswith("0x") else (token_address or "").strip()
    db = await get_db()
    cursor = await db.execute(
        "SELECT category, category_note FROM token_categories WHERE user_id = ? AND token_address = ?",
        (user_id, key),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return (row[0] or "", row[1])


async def set_token_category(
    user_id: int, token_address: str, category: str, category_note: Optional[str] = None
) -> None:
    """Upsert category for (user_id, token_address) for reuse on next trade."""
    from datetime import datetime
    if not token_address or len(str(token_address).strip()) < 10:
        return
    key = (token_address or "").strip().lower() if (token_address or "").strip().startswith("0x") else (token_address or "").strip()
    db = await get_db()
    now = datetime.utcnow().isoformat()
    await db.execute(
        """INSERT INTO token_categories (user_id, token_address, category, category_note, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(user_id, token_address) DO UPDATE SET
             category = excluded.category, category_note = excluded.category_note, updated_at = excluded.updated_at""",
        (user_id, key, category or "", category_note, now),
    )
    await db.commit()


async def set_token_cache(
    token_address: str,
    token_name: Optional[str] = None,
    symbol: Optional[str] = None,
    decimals: Optional[int] = None,
    chain: Optional[str] = None,
    pair_address: Optional[str] = None,
    price: Optional[float] = None,
) -> None:
    """Insert or replace token metadata in cache. Also updates token_metadata for display."""
    from datetime import datetime
    if not token_address or len(str(token_address).strip()) < 10:
        return
    key = (token_address or "").strip().lower() if (token_address or "").strip().startswith("0x") else (token_address or "").strip()
    db = await get_db()
    now = datetime.utcnow().isoformat()
    await db.execute(
        """INSERT INTO token_cache (token_address, token_name, symbol, decimals, chain, pair_address, price, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(token_address) DO UPDATE SET
             token_name=excluded.token_name, symbol=excluded.symbol, decimals=excluded.decimals,
             chain=excluded.chain, pair_address=excluded.pair_address, price=excluded.price, updated_at=excluded.updated_at""",
        (key, token_name, symbol, decimals, chain, pair_address, price, now),
    )
    await db.commit()
    # Keep token_metadata in sync for display (avoids $Unknown)
    await set_token_metadata(key, symbol or "?", token_name, decimals, chain)


# --- Trade timeline ---

async def insert_trade_timeline_event(
    trade_id: int,
    event_type: str,
    value_usd: Optional[float] = None,
    amount: Optional[float] = None,
    note: Optional[str] = None,
    price: Optional[float] = None,
    mcap: Optional[float] = None,
) -> None:
    """Append event to trade timeline. event_type: OPEN, DCA, PARTIAL_EXIT, FULL_CLOSE. Stores price and mcap per entry."""
    from datetime import datetime
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO trade_timeline (trade_id, event_type, value_usd, amount, note, created_at, price, mcap)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (trade_id, event_type, value_usd, amount, note, datetime.utcnow().isoformat(), price, mcap),
        )
    except Exception:
        await db.execute(
            """INSERT INTO trade_timeline (trade_id, event_type, value_usd, amount, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (trade_id, event_type, value_usd, amount, note, datetime.utcnow().isoformat()),
        )
    await db.commit()


async def get_trade_timeline(trade_id: int) -> list:
    """Return list of timeline events (dict with event_type, value_usd, amount, note, created_at, price, mcap) ordered by time."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT event_type, value_usd, amount, note, created_at, price, mcap
           FROM trade_timeline WHERE trade_id = ? ORDER BY id ASC""",
        (trade_id,),
    )
    rows = await cursor.fetchall()
    return [
        {
            "event_type": r[0],
            "value_usd": r[1],
            "amount": r[2],
            "note": r[3],
            "created_at": r[4],
            "price": r[5] if len(r) > 5 else None,
            "mcap": r[6] if len(r) > 6 else None,
        }
        for r in rows
    ]


async def update_trade_open_quantity(trade_id: int, open_quantity: float, open_price: float, open_value_usd: Optional[float] = None) -> None:
    """DCA: update open_quantity and recalculate weighted average open_price."""
    db = await get_db()
    params: list = [open_quantity, open_quantity, open_price]
    sql = "UPDATE trades SET open_quantity = ?, remaining_quantity = ?, open_price = ?"
    if open_value_usd is not None:
        sql += ", open_value_usd = ?"
        params.append(open_value_usd)
    sql += " WHERE trade_id = ?"
    params.append(trade_id)
    await db.execute(sql, tuple(params))
    await db.commit()


# --- Trade Notes (attached to trades) ---


async def insert_trade_note(
    trade_id: int,
    user_id: int,
    note_text: Optional[str] = None,
    image_file_id: Optional[str] = None,
) -> int:
    """Insert a trade note. Returns note id."""
    from datetime import datetime
    db = await get_db()
    await db.execute(
        """INSERT INTO trade_notes (trade_id, user_id, note_text, image_file_id, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (trade_id, user_id, note_text, image_file_id, datetime.utcnow().isoformat()),
    )
    await db.commit()
    cursor = await db.execute("SELECT last_insert_rowid()")
    return (await cursor.fetchone())[0]


async def get_trade_notes(trade_id: int, user_id: int) -> list[dict]:
    """Return all notes for a trade, ordered by creation time."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT id, note_text, image_file_id, created_at
           FROM trade_notes WHERE trade_id = ? AND user_id = ?
           ORDER BY id ASC""",
        (trade_id, user_id),
    )
    rows = await cursor.fetchall()
    return [
        {"id": r[0], "note_text": r[1], "image_file_id": r[2], "created_at": r[3]}
        for r in rows
    ]


async def get_trade_note(trade_id: int, user_id: int) -> Optional[dict]:
    """Return the single note for a trade (1 trade = 1 note rule)."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT id, note_text, image_file_id, created_at
           FROM trade_notes WHERE trade_id = ? AND user_id = ?
           LIMIT 1""",
        (trade_id, user_id),
    )
    r = await cursor.fetchone()
    if not r:
        return None
    return {"id": r[0], "note_text": r[1], "image_file_id": r[2], "created_at": r[3]}


async def get_trade_note_by_id(note_id: int, user_id: int) -> Optional[dict]:
    """Return a specific note."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT id, trade_id, note_text, image_file_id, created_at
           FROM trade_notes WHERE id = ? AND user_id = ?""",
        (note_id, user_id),
    )
    r = await cursor.fetchone()
    if not r:
        return None
    return {"id": r[0], "trade_id": r[1], "note_text": r[2], "image_file_id": r[3], "created_at": r[4]}


async def update_trade_note(trade_id: int, user_id: int, note_text: str) -> bool:
    """Update the note for a trade. Returns True if updated."""
    db = await get_db()
    cursor = await db.execute(
        """UPDATE trade_notes SET note_text = ?
           WHERE trade_id = ? AND user_id = ?""",
        (note_text, trade_id, user_id),
    )
    await db.commit()
    return cursor.rowcount > 0


async def delete_trade_note(note_id: int, user_id: int) -> bool:
    """Delete a trade note. Returns True if deleted."""
    db = await get_db()
    cursor = await db.execute(
        "DELETE FROM trade_notes WHERE id = ? AND user_id = ?",
        (note_id, user_id),
    )
    await db.commit()
    return cursor.rowcount > 0


# --- Personal Journal ---


async def insert_journal_entry(
    user_id: int,
    title: Optional[str] = None,
    note_text: Optional[str] = None,
    image_file_id: Optional[str] = None,
    media_type: Optional[str] = None,
    media_file_ids: Optional[str] = None,
) -> int:
    """Insert a personal journal entry. media_file_ids: JSON array of {file_id, type} for albums."""
    from datetime import datetime
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO personal_journals (user_id, title, note_text, image_file_id, media_type, media_file_ids, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, (title or "").strip() or None, note_text, image_file_id, media_type, media_file_ids, datetime.utcnow().isoformat()),
        )
    except Exception:
        await db.execute(
            """INSERT INTO personal_journals (user_id, title, note_text, image_file_id, media_type, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, (title or "").strip() or None, note_text, image_file_id, media_type, datetime.utcnow().isoformat()),
        )
    await db.commit()
    cursor = await db.execute("SELECT last_insert_rowid()")
    return (await cursor.fetchone())[0]


async def get_journal_entries(user_id: int, limit: int = 50, offset: int = 0) -> list[dict]:
    """Return personal journal entries, newest first."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT id, title, note_text, image_file_id, media_type, created_at
           FROM personal_journals WHERE user_id = ?
           ORDER BY id DESC LIMIT ? OFFSET ?""",
        (user_id, limit, offset),
    )
    rows = await cursor.fetchall()
    return [
        {"id": r[0], "title": (r[1] or "").strip() or None, "note_text": r[2], "image_file_id": r[3], "media_type": r[4] if len(r) > 4 else None, "created_at": r[5] if len(r) > 5 else r[4]}
        for r in rows
    ]


async def get_journal_entry_count(user_id: int) -> int:
    """Return total number of journal entries for user."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT COUNT(*) FROM personal_journals WHERE user_id = ?",
        (user_id,),
    )
    return (await cursor.fetchone())[0]


async def get_journal_entry_by_id(entry_id: int, user_id: int) -> Optional[dict]:
    """Return a specific journal entry."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT id, title, note_text, image_file_id, media_type, created_at
           FROM personal_journals WHERE id = ? AND user_id = ?""",
        (entry_id, user_id),
    )
    r = await cursor.fetchone()
    if not r:
        return None
    created_at = r[5] if len(r) > 5 else r[4]
    media_type = r[4] if len(r) > 4 else None
    return {"id": r[0], "title": (r[1] or "").strip() or None, "note_text": r[2], "image_file_id": r[3], "media_type": media_type, "created_at": created_at}


async def delete_journal_entry(entry_id: int, user_id: int) -> bool:
    """Delete a journal entry. Returns True if deleted."""
    db = await get_db()
    cursor = await db.execute(
        "DELETE FROM personal_journals WHERE id = ? AND user_id = ?",
        (entry_id, user_id),
    )
    await db.commit()
    return cursor.rowcount > 0


async def update_journal_entry(
    entry_id: int,
    user_id: int,
    note_text: Optional[str] = None,
    image_file_id: Optional[str] = None,
    title: Optional[str] = None,
    media_type: Optional[str] = None,
) -> bool:
    """Update a journal entry. Returns True if updated. media_type: 'photo' or 'video' when updating media."""
    db = await get_db()
    if title is not None:
        await db.execute(
            "UPDATE personal_journals SET title = ? WHERE id = ? AND user_id = ?",
            (title, entry_id, user_id),
        )
    if note_text is not None or image_file_id is not None:
        if note_text is not None and image_file_id is not None:
            if media_type is not None:
                await db.execute(
                    "UPDATE personal_journals SET note_text = ?, image_file_id = ?, media_type = ? WHERE id = ? AND user_id = ?",
                    (note_text, image_file_id, media_type, entry_id, user_id),
                )
            else:
                await db.execute(
                    "UPDATE personal_journals SET note_text = ?, image_file_id = ? WHERE id = ? AND user_id = ?",
                    (note_text, image_file_id, entry_id, user_id),
                )
        elif note_text is not None:
            await db.execute(
                "UPDATE personal_journals SET note_text = ? WHERE id = ? AND user_id = ?",
                (note_text, entry_id, user_id),
            )
        elif image_file_id is not None:
            if media_type is not None:
                await db.execute(
                    "UPDATE personal_journals SET image_file_id = ?, media_type = ? WHERE id = ? AND user_id = ?",
                    (image_file_id, media_type, entry_id, user_id),
                )
            else:
                await db.execute(
                    "UPDATE personal_journals SET image_file_id = ? WHERE id = ? AND user_id = ?",
                    (image_file_id, entry_id, user_id),
                )
    await db.commit()
    return True


# --- User settings (timezone for display only; storage remains UTC) ---


async def get_user_timezone_offset(user_id: int) -> int:
    """Return user's timezone offset in hours (e.g. 7 for UTC+7). Default 0 (UTC)."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT timezone_offset FROM user_settings WHERE user_id = ?",
        (user_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return 0
    return int(row[0]) if row[0] is not None else 0


async def set_user_timezone(user_id: int, offset_hours: int) -> None:
    """Save user's timezone offset. Only affects display; all DB timestamps stay UTC."""
    db = await get_db()
    await db.execute(
        """INSERT INTO user_settings (user_id, timezone_offset) VALUES (?, ?)
           ON CONFLICT(user_id) DO UPDATE SET timezone_offset = ?""",
        (user_id, offset_hours, offset_hours),
    )
    await db.commit()


async def get_user_premium_status(user_id: int) -> dict:
    """Cached premium status (short TTL)."""
    now = time.monotonic()
    hit = _premium_status_cache.get(user_id)
    if hit and now < hit[0]:
        return dict(hit[1])
    out = await _get_user_premium_status_uncached(user_id)
    _premium_status_cache[user_id] = (now + _PREMIUM_STATUS_TTL, dict(out))
    return out


async def get_user_premium_status_fresh(user_id: int) -> dict:
    """Always read DB (for Premium screen status line)."""
    return await _get_user_premium_status_uncached(user_id)


async def _get_user_premium_status_uncached(user_id: int) -> dict:
    """Return dict with is_premium (bool), plan, next_billing, premium_expires_at, plan_type,
    referral_days_earned, referral_days_remaining. is_premium = purchased active OR referral days > 0."""
    from datetime import datetime
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT is_premium, plan, next_billing, premium_expires_at, plan_type,
               COALESCE(referral_days_earned, 0), COALESCE(referral_days_remaining, 0),
               referral_premium_expires_at
               FROM user_settings WHERE user_id = ?""",
            (user_id,),
        )
    except Exception:
        cursor = await db.execute(
            "SELECT is_premium, plan, next_billing FROM user_settings WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return {"is_premium": False, "plan": None, "next_billing": None, "premium_expires_at": None,
                    "plan_type": None, "referral_days_earned": 0, "referral_days_remaining": 0,
                    "referral_premium_expires_at": None,
                    "purchased_active": False, "referral_active": False}
        is_purchased = bool(int(row[0])) if row[0] is not None else False
        return {"is_premium": is_purchased, "plan": str(row[1]).strip() if row[1] else None,
                "next_billing": str(row[2]).strip() if row[2] else None, "premium_expires_at": None,
                "plan_type": None, "referral_days_earned": 0, "referral_days_remaining": 0,
                "referral_premium_expires_at": None,
                "purchased_active": is_purchased, "referral_active": False}
    row = await cursor.fetchone()
    if row is None:
        return {"is_premium": False, "plan": None, "next_billing": None, "premium_expires_at": None,
                "plan_type": None, "referral_days_earned": 0, "referral_days_remaining": 0,
                "referral_premium_expires_at": None,
                "purchased_active": False, "referral_active": False}
    is_purchased_flag = bool(int(row[0])) if row[0] is not None else False
    plan = str(row[1]).strip() if row[1] else None
    next_billing = str(row[2]).strip() if row[2] else None
    premium_expires_at = str(row[3]).strip() if row[3] else None
    plan_type = str(row[4]).strip() if row[4] else None
    referral_earned = int(row[5]) if row[5] is not None else 0
    referral_remaining = int(row[6]) if row[6] is not None else 0
    referral_expires_at = str(row[7]).strip() if len(row) > 7 and row[7] else None
    if referral_expires_at:
        try:
            rexp = datetime.fromisoformat(referral_expires_at.replace("Z", ""))
            referral_remaining = max(0, (rexp - datetime.utcnow()).days)
            referral_active = datetime.utcnow() < rexp
        except Exception:
            referral_active = referral_remaining > 0
    else:
        referral_active = referral_remaining > 0
    purchased_active = False
    if premium_expires_at:
        try:
            expiry = datetime.fromisoformat(premium_expires_at.replace("Z", ""))
            purchased_active = datetime.utcnow() < expiry
        except Exception:
            purchased_active = bool(is_purchased_flag)
    else:
        purchased_active = bool(is_purchased_flag)
    is_premium = purchased_active or referral_active
    return {
        "is_premium": is_premium,
        "plan": plan or None,
        "next_billing": next_billing or None,
        "premium_expires_at": premium_expires_at,
        "plan_type": plan_type,
        "referral_days_earned": referral_earned,
        "referral_days_remaining": referral_remaining,
        "referral_premium_expires_at": referral_expires_at,
        "purchased_active": purchased_active,
        "referral_active": referral_active,
    }


async def set_user_premium(
    user_id: int,
    is_premium: bool,
    plan: Optional[str] = None,
    next_billing: Optional[str] = None,
    plan_type: Optional[str] = None,
    premium_expires_at: Optional[str] = None,
) -> None:
    """Set premium status for user (admin or payment). Creates user_settings row if missing. When locking, clears expiry."""
    from datetime import datetime, timedelta
    db = await get_db()
    if not is_premium:
        try:
            await db.execute(
                """UPDATE user_settings SET is_premium = 0, plan = NULL, next_billing = NULL,
                   premium_expires_at = NULL, plan_type = NULL WHERE user_id = ?""",
                (user_id,),
            )
            await db.commit()
        except Exception:
            await db.rollback()
        invalidate_premium_status_cache(user_id)
        return
    if premium_expires_at is None and plan_type:
        now = datetime.utcnow()
        if plan_type == "monthly":
            expires = (now + timedelta(days=30)).isoformat()
        elif plan_type == "yearly":
            expires = (now + timedelta(days=365)).isoformat()
        elif plan_type == "lifetime":
            expires = (now + timedelta(days=365 * 100)).isoformat()
        else:
            expires = (now + timedelta(days=30)).isoformat()
        premium_expires_at = expires
    await db.execute(
        """INSERT INTO user_settings (user_id, timezone_offset, is_premium, plan, next_billing, premium_expires_at, plan_type)
           VALUES (?, 0, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET
             is_premium = excluded.is_premium,
             plan = excluded.plan,
             next_billing = excluded.next_billing,
             premium_expires_at = excluded.premium_expires_at,
             plan_type = excluded.plan_type""",
        (user_id, 1, plan or None, next_billing or None, premium_expires_at, plan_type or None),
    )
    await db.commit()
    invalidate_premium_status_cache(user_id)


# Referral: referral rewards are one-time and capped per-user (free premium).
# Rules:
# - Inviter: +2 days ONLY on their first successful invite
# - Referred: +1 day ONLY the first time they are referred
# - Max free premium from referrals per user: 3 days total
REFERRAL_MAX_FREE_DAYS = 3
REFERRAL_FIRST_INVITE_BONUS_DAYS = 2
REFERRAL_FIRST_TIME_REFERRED_DAYS = 1


async def record_referral(referrer_id: int, referred_id: int) -> bool:
    """Record a referral if not already present. Returns True if new referral was added."""
    from datetime import datetime, timedelta
    if referrer_id == referred_id:
        return False
    db = await get_db()
    # Prevent multi-referrals for the same referred user (first time only).
    try:
        cur = await db.execute("SELECT invited_by FROM user_settings WHERE user_id = ?", (referred_id,))
        row = await cur.fetchone()
        if row and row[0] is not None:
            return False
        cur = await db.execute("SELECT 1 FROM referrals WHERE referred_id = ? LIMIT 1", (referred_id,))
        row = await cur.fetchone()
        if row:
            return False
    except Exception:
        # If validation fails, be safe and do not record reward.
        return False
    try:
        await db.execute(
            "INSERT INTO referrals (referrer_id, referred_id, created_at) VALUES (?, ?, ?)",
            (referrer_id, referred_id, datetime.utcnow().isoformat()),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        return False
    now = datetime.utcnow()
    # Inviter reward: +2 days ONLY for first successful invite.
    inviter_award = 0
    try:
        cur = await db.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (referrer_id,))
        r = await cur.fetchone()
        inviter_award = REFERRAL_FIRST_INVITE_BONUS_DAYS if (r and int(r[0]) == 1) else 0
    except Exception:
        inviter_award = 0

    # Award inviter (cap total free days to REFERRAL_MAX_FREE_DAYS)
    now = datetime.utcnow()
    referrer_expiry = await _get_referral_expiry(referrer_id)
    referrer_remaining = max(0, (referrer_expiry - now).days) if referrer_expiry else 0
    if inviter_award > 0:
        referrer_new_remaining = min(REFERRAL_MAX_FREE_DAYS, referrer_remaining + inviter_award)
        referrer_new_expiry = (now + timedelta(days=referrer_new_remaining)).isoformat()
        referrer_earned = await _get_referral_earned(referrer_id) + inviter_award
        await _set_referral(user_id=referrer_id, earned=referrer_earned, expires_at=referrer_new_expiry)

    # Referred reward: +1 day ONLY first time (also capped to REFERRAL_MAX_FREE_DAYS)
    referred_expiry = await _get_referral_expiry(referred_id)
    referred_remaining = max(0, (referred_expiry - now).days) if referred_expiry else 0
    referred_new_remaining = min(REFERRAL_MAX_FREE_DAYS, referred_remaining + REFERRAL_FIRST_TIME_REFERRED_DAYS)
    referred_new_expiry = (now + timedelta(days=referred_new_remaining)).isoformat()
    referred_earned = await _get_referral_earned(referred_id) + REFERRAL_FIRST_TIME_REFERRED_DAYS
    await _set_referral(user_id=referred_id, earned=referred_earned, expires_at=referred_new_expiry)
    try:
        await db.execute(
            "UPDATE user_settings SET invited_by = ? WHERE user_id = ?",
            (referrer_id, referred_id),
        )
        cur = await db.execute("SELECT changes()")
        r = await cur.fetchone()
        if not r or r[0] == 0:
            await db.execute(
                "INSERT INTO user_settings (user_id, timezone_offset, invited_by) VALUES (?, 0, ?)",
                (referred_id, referrer_id),
            )
        await db.commit()
    except Exception:
        await db.rollback()
    invalidate_premium_status_cache(referrer_id)
    invalidate_premium_status_cache(referred_id)
    invalidate_referral_detailed_cache(referrer_id)
    invalidate_leaderboard_cache()
    return True


async def _get_referral_expiry(user_id: int):
    """Return datetime or None for referral_premium_expires_at."""
    db = await get_db()
    try:
        c = await db.execute("SELECT referral_premium_expires_at FROM user_settings WHERE user_id = ?", (user_id,))
        r = await c.fetchone()
        if r and r[0]:
            return datetime.fromisoformat(str(r[0]).replace("Z", ""))
    except Exception:
        pass
    return None


async def _get_referral_earned(user_id: int) -> int:
    db = await get_db()
    try:
        c = await db.execute("SELECT referral_days_earned FROM user_settings WHERE user_id = ?", (user_id,))
        r = await c.fetchone()
        if r and r[0] is not None:
            return int(r[0])
    except Exception:
        pass
    return 0


async def _set_referral(user_id: int, earned: int, expires_at: str) -> None:
    """Update referral_days_earned and referral_premium_expires_at."""
    from datetime import datetime
    db = await get_db()
    try:
        remaining_days = max(0, (datetime.fromisoformat(expires_at.replace("Z", "")) - datetime.utcnow()).days)
        await db.execute(
            """UPDATE user_settings SET referral_days_earned = ?, referral_days_remaining = ?,
               referral_premium_expires_at = ? WHERE user_id = ?""",
            (earned, remaining_days, expires_at, user_id),
        )
        cur = await db.execute("SELECT changes()")
        r = await cur.fetchone()
        if not r or r[0] == 0:
            remaining_days = max(0, (datetime.fromisoformat(expires_at.replace("Z", "")) - datetime.utcnow()).days)
            await db.execute(
                """INSERT INTO user_settings (user_id, timezone_offset, referral_days_earned, referral_days_remaining, referral_premium_expires_at)
                   VALUES (?, 0, ?, ?, ?)""",
                (user_id, earned, remaining_days, expires_at),
            )
        await db.commit()
    except Exception:
        await db.rollback()
    invalidate_premium_status_cache(user_id)


async def get_user_referral_stats(user_id: int) -> dict:
    """Return total_invites (count of referrals by this user) and earned_days (referral_days_earned)."""
    db = await get_db()
    invites = 0
    try:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        invites = int(row[0]) if row and row[0] is not None else 0
    except Exception:
        pass
    earned = await _get_referral_earned(user_id)
    return {"total_invites": invites, "earned_days": earned}


async def get_referral_stats_detailed(user_id: int) -> dict:
    """
    Return detailed referral stats: total_invites, active_users, premium_conversions, earned_days.
    active_users = total_invites (all referred are in system). premium_conversions = referred users who have premium.
    """
    from datetime import datetime
    now = time.monotonic()
    hit = _referral_detailed_cache.get(user_id)
    if hit and now < hit[0]:
        return dict(hit[1])
    stats = await get_user_referral_stats(user_id)
    total = stats.get("total_invites", 0)
    earned_days = stats.get("earned_days", 0)
    db = await get_db()
    premium_count = 0
    try:
        now_iso = datetime.utcnow().isoformat()
        cursor = await db.execute(
            """SELECT r.referred_id FROM referrals r
               INNER JOIN user_settings u ON u.user_id = r.referred_id
               WHERE r.referrer_id = ?
               AND (
                 (u.premium_expires_at IS NOT NULL AND u.premium_expires_at > ?)
                 OR (u.referral_premium_expires_at IS NOT NULL AND u.referral_premium_expires_at > ?)
               )""",
            (user_id, now_iso, now_iso),
        )
        premium_count = len(await cursor.fetchall())
    except Exception:
        pass
    out = {
        "total_invites": total,
        "active_users": total,
        "premium_conversions": premium_count,
        "earned_days": earned_days,
    }
    _referral_detailed_cache[user_id] = (now + _REFERRAL_DETAILED_TTL, dict(out))
    return out


async def get_referral_leaderboard(limit: int = 10) -> list[tuple[int, int]]:
    """Return list of (user_id, invite_count) for top referrers."""
    global _leaderboard_cache
    now = time.monotonic()
    if _leaderboard_cache and now < _leaderboard_cache[0]:
        return list(_leaderboard_cache[1])
    db = await get_db()
    cursor = await db.execute(
        "SELECT referrer_id, COUNT(*) AS cnt FROM referrals GROUP BY referrer_id ORDER BY cnt DESC LIMIT ?",
        (limit,),
    )
    rows = [(r[0], r[1]) for r in await cursor.fetchall()]
    _leaderboard_cache = (now + _LEADERBOARD_TTL, rows)
    return rows


async def get_referral_tree() -> list[tuple[int, list]]:
    """
    Build referral tree from referrals table. Returns list of (root_user_id, list of child nodes).
    Each child node is (referred_id, list of that user's children).
    Roots = referrers who were not referred by anyone in the system.
    """
    from collections import defaultdict
    db = await get_db()
    cursor = await db.execute("SELECT referrer_id, referred_id FROM referrals")
    rows = await cursor.fetchall()
    parent_to_children = defaultdict(list)
    all_referred = set()
    for referrer_id, referred_id in rows:
        parent_to_children[referrer_id].append(referred_id)
        all_referred.add(referred_id)
    roots = [uid for uid in parent_to_children if uid not in all_referred]
    if not roots:
        roots = list(parent_to_children.keys())

    def build_node(uid: int):
        children = parent_to_children.get(uid, [])
        return (uid, [build_node(cid) for cid in children])

    return [build_node(rid) for rid in roots]


async def get_recent_trades_count(user_id: int, within_minutes: int) -> int:
    """Count valid trades (open or closed) with open_time within the last N minutes. For risk alerts."""
    from datetime import datetime, timedelta
    cutoff = (datetime.utcnow() - timedelta(minutes=within_minutes)).isoformat()
    db = await get_db()
    cursor = await db.execute(
        "SELECT COUNT(*) FROM trades WHERE user_id = ? AND status = 'valid' AND open_time >= ?",
        (user_id, cutoff),
    )
    row = await cursor.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


# --- Manual USDC (Base) premium payments ---


async def payment_tx_hash_exists(tx_hash: str) -> bool:
    db = await get_db()
    cur = await db.execute("SELECT 1 FROM payments WHERE tx_hash = ? LIMIT 1", (tx_hash,))
    row = await cur.fetchone()
    return row is not None


async def user_has_pending_payment(user_id: int) -> bool:
    db = await get_db()
    cur = await db.execute(
        "SELECT 1 FROM payments WHERE user_id = ? AND status = 'pending' LIMIT 1",
        (user_id,),
    )
    row = await cur.fetchone()
    return row is not None


async def insert_payment_pending(user_id: int, plan: str, amount_usd: float, tx_hash: str) -> Optional[int]:
    """Insert a pending payment. Returns payment id, or None if tx_hash is duplicate (UNIQUE)."""
    from datetime import datetime

    db = await get_db()
    try:
        cur = await db.execute(
            """INSERT INTO payments (user_id, plan, amount_usd, tx_hash, status, created_at)
               VALUES (?, ?, ?, ?, 'pending', ?)""",
            (user_id, plan, amount_usd, tx_hash, datetime.utcnow().isoformat()),
        )
        await db.commit()
        return int(cur.lastrowid) if cur.lastrowid is not None else None
    except sqlite3.IntegrityError:
        await db.rollback()
        return None
    except Exception:
        await db.rollback()
        raise


async def get_pending_payments() -> list[dict[str, Any]]:
    db = await get_db()
    cur = await db.execute(
        """SELECT id, user_id, plan, amount_usd, tx_hash, status, created_at
           FROM payments WHERE status = 'pending' ORDER BY created_at ASC"""
    )
    rows = await cur.fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": int(r[0]),
                "user_id": int(r[1]),
                "plan": str(r[2]),
                "amount_usd": float(r[3]),
                "tx_hash": str(r[4]),
                "status": str(r[5]),
                "created_at": str(r[6]),
            }
        )
    return out


async def get_payment_by_id(payment_id: int) -> Optional[dict[str, Any]]:
    db = await get_db()
    cur = await db.execute(
        """SELECT id, user_id, plan, amount_usd, tx_hash, status, created_at
           FROM payments WHERE id = ?""",
        (payment_id,),
    )
    r = await cur.fetchone()
    if r is None:
        return None
    return {
        "id": int(r[0]),
        "user_id": int(r[1]),
        "plan": str(r[2]),
        "amount_usd": float(r[3]),
        "tx_hash": str(r[4]),
        "status": str(r[5]),
        "created_at": str(r[6]),
    }


async def update_payment_from_pending(payment_id: int, new_status: str) -> bool:
    """Set status from pending to approved/rejected. Returns True if one row updated."""
    if new_status not in ("approved", "rejected"):
        return False
    db = await get_db()
    await db.execute(
        "UPDATE payments SET status = ? WHERE id = ? AND status = 'pending'",
        (new_status, payment_id),
    )
    await db.commit()
    cur = await db.execute("SELECT status FROM payments WHERE id = ?", (payment_id,))
    r = await cur.fetchone()
    return bool(r and str(r[0]) == new_status)


# --- Support tickets (user → admin) ---


async def insert_support_ticket(user_id: int, text: str, image_file_id: Optional[str]) -> int:
    from datetime import datetime

    db = await get_db()
    cur = await db.execute(
        """INSERT INTO support_tickets (user_id, text, image_file_id, status, created_at)
           VALUES (?, ?, ?, 'open', ?)""",
        (user_id, text, image_file_id, datetime.utcnow().isoformat()),
    )
    await db.commit()
    return int(cur.lastrowid) if cur.lastrowid is not None else 0


async def get_open_support_tickets() -> list[dict[str, Any]]:
    db = await get_db()
    cur = await db.execute(
        """SELECT id, user_id, text, image_file_id, status, created_at
           FROM support_tickets WHERE status = 'open' ORDER BY created_at DESC"""
    )
    rows = await cur.fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": int(r[0]),
                "user_id": int(r[1]),
                "text": str(r[2]),
                "image_file_id": str(r[3]) if r[3] else None,
                "status": str(r[4]),
                "created_at": str(r[5]),
            }
        )
    return out


async def close_support_ticket(ticket_id: int) -> bool:
    """Mark ticket closed. Returns True if it was open and is now closed."""
    db = await get_db()
    cur = await db.execute("SELECT status FROM support_tickets WHERE id = ?", (ticket_id,))
    row = await cur.fetchone()
    if not row or str(row[0]) != "open":
        return False
    await db.execute(
        "UPDATE support_tickets SET status = 'closed' WHERE id = ? AND status = 'open'",
        (ticket_id,),
    )
    await db.commit()
    return True
