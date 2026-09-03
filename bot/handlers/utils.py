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
    'casualties', 'armed_conflict', 'shelling',
    'radar_track', 'general_alert', 'air_defense', 'drone_attack'
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
    """Dynamically retrieves the current active dashboard URL from ENV or Redis, defaulting to stable direct IP."""
    env_url = os.getenv("DASHBOARD_URL")
    if env_url and env_url.strip() and "halifax" not in env_url:
        return env_url.strip()
    try:
        val = redis_client.get("active_tunnel_url")
        if val:
            url_str = val.strip() if isinstance(val, str) else val.decode("utf-8").strip()
            if "halifax" not in url_str and url_str.startswith("http"):
                return url_str
    except Exception:
        pass
    return "http://136.113.156.17"


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
    """
    Enhanced deduplication:
    1. Dedup by worker-assigned incident_id.
    2. Dedup by normalized snippet content and location so reposts hours apart
       of the exact same official summary do not flood the top lists.
    """
    seen_ids = set()
    seen_signatures = set()
    unique = []

    for e in events:
        key = e.incident_id or f"_row_{e.id}"
        if key in seen_ids:
            continue

        raw_txt = (e.message_text or "").lower()
        clean_stem = re.sub(r'[^a-zA-Zа-яА-ЯіїєґІЇЄҐ0-9]', '', raw_txt[:80])
        sig = f"{e.location_text or ''}:{clean_stem[:35]}" if len(clean_stem) >= 15 else None

        if sig and sig in seen_signatures:
            continue

        seen_ids.add(key)
        if sig:
            seen_signatures.add(sig)
        unique.append(e)

    return unique
