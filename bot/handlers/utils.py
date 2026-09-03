import functools
import logging
import os
import re
from zoneinfo import ZoneInfo
import redis
from aiogram import types
from aiogram.enums import ParseMode
from sqlalchemy import or_

from bot.keyboards import get_main_keyboard
from database.models import DetectedEvent

logger = logging.getLogger("bot.handlers")

ADMIN_ID = os.getenv("ADMIN_ID", "123456789")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

KYIV_TZ = ZoneInfo("Europe/Kyiv")

CONFIRMED_INCIDENT_TYPES = [
    'direct_strike', 'explosion', 'fire', 'destruction',
    'casualties', 'armed_conflict', 'shelling'
]

# Strict Kyiv & Kyiv Region Geographical Filter
KYIV_REGION_FILTER = or_(
    DetectedEvent.location_text.ilike('%Київ%'),
    DetectedEvent.location_text.ilike('%Киев%'),
    DetectedEvent.location_text.ilike('%Бровар%'),
    DetectedEvent.location_text.ilike('%Борисп%'),
    DetectedEvent.location_text.ilike('%Ірп%'),
    DetectedEvent.location_text.ilike('%Буч%'),
    DetectedEvent.location_text.ilike('%Васильк%'),
    DetectedEvent.location_text.ilike('%Обух%'),
    DetectedEvent.location_text.ilike('%Біла Церкв%'),
    DetectedEvent.location_text.ilike('%Вишгород%'),
    DetectedEvent.location_text.ilike('%Фастів%'),
    DetectedEvent.location_text.ilike('%Макар%'),
    DetectedEvent.location_text.ilike('%Гостомель%'),
    DetectedEvent.location_text.ilike('%Ворзель%'),
    DetectedEvent.location_text.ilike('%Славутич%'),
    DetectedEvent.location_text.ilike('%Переяслав%'),
    DetectedEvent.location_text.ilike('%Яготин%')
)


def admin_only(handler):
    """Restricts a handler to ADMIN_ID."""
    @functools.wraps(handler)
    async def wrapper(message: types.Message, *args, **kwargs):
        if str(message.from_user.id) != ADMIN_ID:
            await message.answer("⛔ Недостатньо прав.")
            return
        return await handler(message, *args, **kwargs)
    return wrapper


def is_admin(user_id) -> bool:
    return str(user_id) == ADMIN_ID


def get_dashboard_url() -> str:
    """Dynamically retrieves the current active Cloudflare tunnel URL from Redis or ENV."""
    try:
        val = redis_client.get("active_tunnel_url")
        if val:
            return val.strip() if isinstance(val, str) else val.decode("utf-8").strip()
    except Exception:
        pass
    return os.getenv("DASHBOARD_URL", "https://halifax-aim-restoration-dylan.trycloudflare.com")


async def safe_send(message: types.Message, text: str, **kwargs):
    """Send message with HTML parse mode, fallback to plain text on error."""
    if "reply_markup" not in kwargs:
        kwargs["reply_markup"] = get_main_keyboard()
    try:
        await message.answer(text, parse_mode=ParseMode.HTML, **kwargs)
    except Exception:
        plain = re.sub(r'<[^>]+>', '', text)
        await message.answer(plain, **kwargs)


def unique_by_incident(events: list) -> list:
    """Single source of truth: dedup by the worker-assigned incident_id."""
    seen = set()
    unique = []
    for e in events:
        key = e.incident_id or f"_row_{e.id}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(e)
    return unique
