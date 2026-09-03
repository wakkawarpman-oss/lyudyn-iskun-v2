import json
import asyncio
import logging
from aiogram import Bot
from redis.asyncio import Redis
from aiogram.exceptions import TelegramRetryAfter, TelegramAPIError

logger = logging.getLogger(__name__)

class RedisBroadcaster:
    def __init__(self, bot: Bot, redis_url: str = "redis://redis:6379/0", queue_name: str = "broadcast_queue"):
        self.bot = bot
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.queue_name = queue_name
        self.is_running = False
        self.rate_limit = 25  # messages per second (Telegram allows ~30/s)

    async def enqueue(self, chat_id: int, text: str, parse_mode: str = "Markdown", disable_web_page_preview: bool = True):
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview
        }
        await self.redis.rpush(self.queue_name, json.dumps(payload))

    async def _worker(self):
        logger.info(f"Broadcaster worker started for queue '{self.queue_name}'")
        while self.is_running:
            try:
                # Block until an item is available
                result = await self.redis.blpop(self.queue_name, timeout=1)
                if not result:
                    continue
                
                _, data_str = result
                payload = json.loads(data_str)
                
                await self.bot.send_message(
                    chat_id=payload["chat_id"],
                    text=payload["text"],
                    parse_mode=payload.get("parse_mode", "Markdown"),
                    disable_web_page_preview=payload.get("disable_web_page_preview", True)
                )
                
                # Sleep to respect rate limit
                await asyncio.sleep(1.0 / self.rate_limit)
                
            except TelegramRetryAfter as e:
                logger.warning(f"Rate limit hit! Sleeping for {e.retry_after}s")
                await asyncio.sleep(e.retry_after)
                # Re-queue the message
                await self.redis.lpush(self.queue_name, data_str)
            except TelegramAPIError as e:
                logger.error(f"Telegram API Error: {e}")
            except Exception as e:
                logger.error(f"Broadcaster unknown error: {e}")
                await asyncio.sleep(1)

    async def start(self):
        self.is_running = True
        asyncio.create_task(self._worker())

    async def stop(self):
        self.is_running = False
        await self.redis.close()


broadcaster = None

def init_broadcaster(bot, redis_url):
    global broadcaster
    broadcaster = RedisBroadcaster(bot, redis_url)
    return broadcaster
