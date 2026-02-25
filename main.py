import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update, BotCommand

from config import BOT_TOKEN, WEBHOOK_URL
from bot.database.db import init_db, close_db
from bot.handlers import setup_routers
from bot.middlewares.maintenance import MaintenanceMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
dp.update.outer_middleware(MaintenanceMiddleware())
dp.include_router(setup_routers())


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await bot.set_my_commands([
        BotCommand(command="start", description="Open main menu"),
        BotCommand(command="guide", description="How to use bot"),
        BotCommand(command="mystats", description="Show trading statistics"),
        BotCommand(command="positions", description="Show current open positions"),
        BotCommand(command="premium", description="Premium features"),
        BotCommand(command="feedback", description="Send feedback"),
        BotCommand(command="command_list", description="Show command list"),
        BotCommand(command="cancel", description="Reset current flow"),
    ])
    await bot.set_webhook(WEBHOOK_URL)
    logger.info("BehaveBot webhook started: %s", WEBHOOK_URL)
    yield
    await bot.delete_webhook()
    await close_db()
    await bot.session.close()
    logger.info("BehaveBot webhook stopped")


app = FastAPI(lifespan=lifespan)


@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        update = Update.model_validate(data)
        await dp.feed_webhook_update(bot, update)
    except Exception as e:
        logger.exception("Webhook error: %s", e)
        return JSONResponse(content={"ok": False}, status_code=500)
    return JSONResponse(content={"ok": True})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=10000,
        reload=False,
    )
