import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update

from config import BOT_TOKEN, WEBHOOK_URL, ENVIRONMENT
from bot.database.db import init_db, close_db
from bot.handlers import setup_routers
from bot.middlewares.maintenance import MaintenanceMiddleware
from bot.commands import get_bot_commands

logger = logging.getLogger(__name__)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
dp.update.outer_middleware(MaintenanceMiddleware())
dp.include_router(setup_routers())

BOT_COMMANDS = get_bot_commands()


async def run_polling() -> None:
    """Run bot in long-polling mode (dev only). No webhook or FastAPI needed."""
    from bot.services.wallet_monitor import start_wallet_monitor, start_pending_trades_cleanup
    await init_db()
    await bot.set_my_commands(BOT_COMMANDS)
    await bot.delete_webhook(drop_pending_updates=True)
    monitor_task = start_wallet_monitor(bot)
    cleanup_task = start_pending_trades_cleanup()
    logger.info("BehaveBot running in DEVELOPMENT mode (long polling)")
    try:
        await dp.start_polling(bot)
    finally:
        monitor_task.cancel()
        cleanup_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        await close_db()
        await bot.session.close()
        logger.info("BehaveBot stopped")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan for webhook mode (production, or dev with WEBHOOK_URL)."""
    from bot.services.wallet_monitor import start_wallet_monitor, start_pending_trades_cleanup
    await init_db()
    await bot.set_my_commands(BOT_COMMANDS)
    if WEBHOOK_URL:
        await bot.set_webhook(WEBHOOK_URL)
        logger.info("BehaveBot webhook started: %s", WEBHOOK_URL)
    if ENVIRONMENT == "dev":
        logger.info("BehaveBot running in DEVELOPMENT mode (webhook)")
    else:
        logger.info("BehaveBot running in PRODUCTION mode (webhook)")
    monitor_task = start_wallet_monitor(bot)
    cleanup_task = start_pending_trades_cleanup()
    try:
        yield
    finally:
        monitor_task.cancel()
        cleanup_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        if WEBHOOK_URL:
            await bot.delete_webhook()
        await close_db()
        await bot.session.close()
        logger.info("BehaveBot stopped")


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
    if ENVIRONMENT == "dev":
        asyncio.run(run_polling())
    else:
        import uvicorn
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=10000,
            reload=False,
        )
