import asyncio
import os
import time
from aiogram import Bot, Dispatcher
from bot.handlers import router
from database.models import init_db

BOT_TOKEN = os.getenv("BOT_TOKEN")

async def main():
    if not BOT_TOKEN:
        print("No BOT_TOKEN found. Exiting bot UI.")
        return
        
    # Retry DB connection (wait for Postgres to start)
    for i in range(10):
        try:
            init_db()
            print("Database initialized successfully!")
            break
        except Exception as e:
            print(f"Waiting for database... ({i+1}/10) Error: {e}")
            time.sleep(3)
    
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    
    print("Starting bot polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
