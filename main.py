import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN
from bot.database.db import init_db, close_db
from bot.handlers import setup_routers
from bot.middlewares.maintenance import MaintenanceMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    await init_db()
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    from aiogram.types import BotCommand
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
    dp = Dispatcher()
    dp.update.outer_middleware(MaintenanceMiddleware())
    dp.include_router(setup_routers())
    try:
        logger.info("BehaveBot started successfully")
        print("BehaveBot started successfully")
        await dp.start_polling(bot)
    finally:
        await close_db()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)
