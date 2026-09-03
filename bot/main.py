import asyncio
import os
import time
import logging
import sys
from aiogram import Bot, Dispatcher
from bot.handlers import router
from database.models import init_db

# Configure logging to stdout
logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)
logger = logging.getLogger(__name__)

# Import our new background services
from bot.health_check import HealthMonitor
from bot.auto_backup import DatabaseBackup
from bot.critical_alerts import CriticalAlertSystem
from bot.broadcaster import init_broadcaster

BOT_TOKEN = os.getenv("BOT_TOKEN")

async def main():
    if not BOT_TOKEN:
        logger.error("No BOT_TOKEN found. Exiting bot UI.")
        return
        
    # Retry DB connection
    for i in range(10):
        try:
            init_db()
            logger.info("Database initialized successfully!")
            break
        except Exception as e:
            logger.error(f"Waiting for database... ({i+1}/10) Error: {e}")
            time.sleep(3)
    
    bot = Bot(token=BOT_TOKEN)
    # Initialize broadcaster
    broadcaster = init_broadcaster(bot, os.getenv("REDIS_URL", "redis://redis:6379/0"))
    await broadcaster.start()
    dp = Dispatcher()
    dp.include_router(router)
    
    # Initialize background tasks
    health = HealthMonitor(bot)
    backup = DatabaseBackup(bot)
    alerts = CriticalAlertSystem(bot)
    
    logger.info("Starting background tasks...")
    asyncio.create_task(health.run())
    asyncio.create_task(backup.run())
    asyncio.create_task(alerts.run())
    
    logger.info("Dropping pending updates and starting bot polling...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e:
        logger.exception(f"Fatal error during polling: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped.")
