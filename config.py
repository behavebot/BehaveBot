import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN or not BOT_TOKEN.strip():
    raise ValueError("BOT_TOKEN is required. Set it in .env")
BOT_TOKEN = BOT_TOKEN.strip()

WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
if not WEBHOOK_URL:
    raise ValueError("WEBHOOK_URL is required for webhook mode (e.g. https://your-app.onrender.com/webhook)")

ADMIN_IDS = [6013044386]

DB_PATH = Path(os.getenv("DB_PATH", "data/behavebot.db"))
FEEDBACK_DIR = Path(os.getenv("FEEDBACK_DIR", "data/feedback"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)

DEXSCREENER_BASE = os.getenv("DEXSCREENER_BASE", "https://api.dexscreener.com/latest/dex/tokens")
