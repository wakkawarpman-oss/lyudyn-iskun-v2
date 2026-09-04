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
from bot.alert_monitor import AlertMonitor
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
    alert_monitor = AlertMonitor(bot)
    
    logger.info("Starting background tasks...")
    asyncio.create_task(health.run())
    asyncio.create_task(backup.run())
    asyncio.create_task(alerts.run())
    asyncio.create_task(alert_monitor.run())
    
    logger.info("Dropping pending updates and starting bot polling...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        # Configure tactical bot metadata
        try:
            await bot.set_my_name(name="ОКІНТ-ПРО")
        except Exception as e_name:
            logger.warning(f"Could not update bot name: {e_name}")

        try:
            await bot.set_my_short_description(
                short_description="🛡️ Тактичний C4ISR & OSINT арсенал: жива мапа, куполи ППО, LOB-пеленги, CCTV ТОТ, радар та ШІ 24/7."
            )
        except Exception as e_sdesc:
            logger.warning(f"Could not update short description: {e_sdesc}")

        try:
            await bot.set_my_description(
                description=(
                    "🛡️ ОКІНТ-ПРО — C4ISR & OSINT Платформа 24/7\n\n"
                    "«ЗБИРАЄМО • АНАЛІЗУЄМО • ПЕРЕМАГАЄМО»\n\n"
                    "🛠 ТАКТИЧНИЙ АРСЕНАЛ ТА ШАРИ:\n"
                    "• 🗺️ Тактична веб-мапа C4ISR (/map) — повна геоінформаційна картина\n"
                    "• 🛡️ Куполи ППО WEZ (/layers) — зони вогню Тор-М2, Панцир-С1, С-400\n"
                    "• 📐 LOB-пеленгація (/layers) — геодезична засічка та еліпс помилки CEP\n"
                    "• 📹 Відеорозвідка CCTV ТОТ — 315+ вузлів оптичного спостереження\n"
                    "• 🛸 Neptun Live / Радар (/radar) — трекінг цілей, курс, підліт до міст\n"
                    "• 🎯 OpenAthena Raycast (/raycast) — розрахунок координат цілей з дрона\n"
                    "• 📡 Sentinel-1 RFI (/ew) — супутниковий детектор РЕБ та радіозавад\n"
                    "• ☀️ NOAA Chronolocation — хронолокація сонячних тіней на кадрах\n"
                    "• 📦 ATAK DataPackage — експорт Cursor-on-Target XML 2.0 (MIL-STD-2525C)\n"
                    "• 🔄 Синхронізація (/sync) — миттєве оновлення з 20+ Telegram-джерел\n"
                    "• 🟢 Відбій (/vidbiy) — статус відновлення транспорту та бізнесу"
                )
            )
            logger.info("Bot description updated successfully.")
        except Exception as e_desc:
            logger.warning(f"Could not update bot description: {e_desc}")

        try:
            from aiogram.types import BotCommand
            await bot.set_my_commands([
                BotCommand(command="start", description="Головний оперативний екран"),
                BotCommand(command="map", description="Тактична веб-мапа C4ISR"),
                BotCommand(command="layers", description="Тактичні шари (WEZ, LOB, CCTV, РЕБ)"),
                BotCommand(command="sync", description="Примусова актуалізація джерел"),
                BotCommand(command="radar", description="Радар Контур / повітряні цілі"),
                BotCommand(command="raycast", description="Калькулятор координат БпЛА OpenAthena"),
                BotCommand(command="ew", description="Супутниковий моніторинг РЕБ"),
                BotCommand(command="vidbiy", description="Моніторинг відбою тривоги"),
                BotCommand(command="district", description="Секторні сповіщення за районами"),
                BotCommand(command="top", description="Ключові інциденти за 24 год"),
                BotCommand(command="resonance", description="Резонансні події за 1 год"),
                BotCommand(command="status", description="Статус мікросервісів та черг"),
            ])
            logger.info("Bot commands registered successfully.")
        except Exception as e_cmd:
            logger.warning(f"Could not set bot commands: {e_cmd}")
            
        await dp.start_polling(bot)
    except Exception as e:
        logger.exception(f"Fatal error during polling: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped.")
