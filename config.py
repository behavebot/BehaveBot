import os
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
load_dotenv(Path(__file__).resolve().parent / ".env")

logger = logging.getLogger(__name__)

ENVIRONMENT = (os.getenv("ENVIRONMENT") or "production").strip().lower()
if ENVIRONMENT not in ("dev", "development", "production", "prod"):
    ENVIRONMENT = "production"
if ENVIRONMENT in ("dev", "development"):
    ENVIRONMENT = "dev"
else:
    ENVIRONMENT = "production"

BOT_TOKEN_DEV = (os.getenv("BOT_TOKEN_DEV") or "").strip()
BOT_TOKEN_PROD = (os.getenv("BOT_TOKEN_PROD") or "").strip()

if ENVIRONMENT == "dev":
    BOT_TOKEN = BOT_TOKEN_DEV
else:
    BOT_TOKEN = BOT_TOKEN_PROD

if not BOT_TOKEN:
    raise ValueError(
        f"BOT_TOKEN is required for {ENVIRONMENT} mode. "
        f"Set BOT_TOKEN_DEV (for dev) or BOT_TOKEN_PROD (for production) in .env"
    )

WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
# WEBHOOK_URL required only in production (webhook mode). Dev can use polling.
if ENVIRONMENT != "dev" and not WEBHOOK_URL:
    raise ValueError(
        "WEBHOOK_URL is required for production webhook mode (e.g. https://your-app.onrender.com/webhook)"
    )

def _parse_admin_ids() -> list[int]:
    raw = (os.getenv("ADMIN_IDS") or "6013044386").strip()
    if not raw:
        return []
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


ADMIN_IDS = _parse_admin_ids()

if ENVIRONMENT == "dev":
    DB_PATH = Path("data/behavebot_dev.db")
else:
    DB_PATH = Path("data/behavebot_prod.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

FEEDBACK_DIR = Path(os.getenv("FEEDBACK_DIR", "data/feedback"))
FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)

if ENVIRONMENT == "dev":
    print("BehaveBot running in DEVELOPMENT mode using DEV database")
else:
    print("BehaveBot running in PRODUCTION mode using PROD database")

DEXSCREENER_BASE = os.getenv("DEXSCREENER_BASE", "https://api.dexscreener.com/latest/dex/tokens")

# RPC endpoints for wallet monitoring (from .env)
# Solana: fallback to public mainnet when empty; also used on 403 retry
SOL_RPC_PUBLIC_FALLBACK = "https://api.mainnet-beta.solana.com"
SOL_RPC = (os.getenv("SOL_RPC") or "").strip() or SOL_RPC_PUBLIC_FALLBACK
BNB_RPC = (os.getenv("BNB_RPC") or "").strip()
BASE_RPC = (os.getenv("BASE_RPC") or "").strip()

# USDC (Base) manual premium payments — recipient wallet (set in .env for production)
PAYMENT_BASE_USDC_WALLET = (
    os.getenv("PAYMENT_BASE_USDC_WALLET") or "0x0156650a2b571f28aa0c50fc4cf34ea6789efb74"
).strip()


def _mask_rpc_url(u: str) -> str:
    """Mask API key for startup logging (e.g. https://rpc.ankr.com/solana/***)."""
    if not u or not isinstance(u, str):
        return "not set"
    u = u.strip()
    if not u:
        return "not set"
    i = u.rfind("/")
    if i >= 0 and len(u) - i > 15:
        return u[: i + 1] + "***"
    return u[:60] + "..." if len(u) > 60 else u


# Startup logging (do not expose API key)
logger.info("SOL_RPC loaded: %s", bool(SOL_RPC))
logger.info("BNB_RPC loaded: %s", bool(BNB_RPC))
logger.info("BASE_RPC loaded: %s", bool(BASE_RPC))
if SOL_RPC:
    logger.info("Using RPC endpoint for Solana: %s", _mask_rpc_url(SOL_RPC))
if BNB_RPC:
    logger.info("Using RPC endpoint for BNB: %s", _mask_rpc_url(BNB_RPC))
if BASE_RPC:
    logger.info("Using RPC endpoint for Base: %s", _mask_rpc_url(BASE_RPC))
