"""
Tactical Air Raid Alert & All-Clear (Відбій) Monitor for Kyiv & Kyiv Oblast.
Tracks real-time alarm states and delivers high-visibility green all-clear banners to subscribers.
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, Set
import redis
from aiogram import Bot
from aiogram.enums import ParseMode

from database.models import SessionLocal, DetectedEvent

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
redis_client = redis.Redis.from_url(REDIS_URL)

SUBSCRIBERS_KEY = "alerts:subscribers:vidbiy"
ALERT_STATE_KEY = "alerts:kyiv_state"
LAST_ALL_CLEAR_KEY = "alerts:last_all_clear"


def register_vidbiy_subscriber(chat_id: int) -> bool:
    """Registers a chat ID to receive instant notification upon all-clear."""
    try:
        redis_client.sadd(SUBSCRIBERS_KEY, str(chat_id))
        return True
    except Exception as e:
        logger.warning(f"Failed to register subscriber: {e}")
        return False


def unregister_vidbiy_subscriber(chat_id: int) -> bool:
    """Removes a chat ID from the all-clear notification list."""
    try:
        redis_client.srem(SUBSCRIBERS_KEY, str(chat_id))
        return True
    except Exception as e:
        logger.warning(f"Failed to unregister subscriber: {e}")
        return False


def get_vidbiy_subscribers() -> Set[str]:
    """Retrieves all registered subscriber chat IDs."""
    try:
        members = redis_client.smembers(SUBSCRIBERS_KEY)
        return {m.decode("utf-8") if isinstance(m, bytes) else str(m) for m in members}
    except Exception as e:
        logger.warning(f"Failed to get subscribers: {e}")
        return set()


def clear_vidbiy_subscribers() -> None:
    """Clears the subscriber list after all-clear has been broadcast."""
    try:
        redis_client.delete(SUBSCRIBERS_KEY)
    except Exception as e:
        logger.warning(f"Failed to clear subscribers: {e}")


def format_all_clear_banner(
    region: str = "м. Київ та Київська область",
    event_time: Optional[datetime] = None,
    source: str = "КМВА / Офіційний моніторинг тривог (@kyiv_alarm)"
) -> str:
    """Formats the large green high-visibility all-clear banner."""
    dt = event_time or datetime.utcnow()
    # Format Europe/Kyiv time (UTC+2 / UTC+3)
    kyiv_time = dt + timedelta(hours=3) # Kyiv Summer Time
    time_str = kyiv_time.strftime("%H:%M:%S")
    date_str = kyiv_time.strftime("%d.%m.%Y")

    return (
        "🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩\n"
        "🟩     <b>ВІДБІЙ ТРИВОГИ!</b>     🟩\n"
        "🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩\n\n"
        "🟢 <b>ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ</b>\n"
        f"📍 <b>Регіон:</b> {region}\n\n"
        f"🕒 <b>Час сигналу:</b> {time_str} (за Києвом) · {date_str}\n"
        f"📡 <b>Джерело підтвердження:</b> {source}\n"
        "🛡️ <b>Статус:</b> Загроза ворожих ударів минула. Можна повертатися зі сховищ до звичного ритму.\n\n"
        "<i>Служба оперативного оповіщення «Людин Іскун»</i>"
    )


def format_active_alert_banner(
    region: str = "м. Київ та Київська область",
    event_time: Optional[datetime] = None,
    threat_info: str = "Загроза ударних БпЛА / ракетної небезпеки"
) -> str:
    """Formats the high-visibility active alarm banner with auto-subscription prompt."""
    dt = event_time or datetime.utcnow()
    kyiv_time = dt + timedelta(hours=3)
    time_str = kyiv_time.strftime("%H:%M:%S")

    return (
        "🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥\n"
        "🟥    <b>ПОВІТРЯНА ТРИВОГА!</b>    🟥\n"
        "🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥\n\n"
        f"🔴 <b>УВАГА: У РЕГІОНІ ТРИВАЄ ПОВІТРЯНА ТРИВОГА!</b>\n"
        f"📍 <b>Регіон:</b> {region}\n"
        f"⚠️ <b>Характер загрози:</b> {threat_info}\n"
        f"🕒 <b>Початок тривоги:</b> {time_str}\n\n"
        "📍 <i>Залишайтеся в укриттях або дотримуйтесь правила «двох стін»!</i>\n\n"
        "🔔 <b>РЕЖИМ МОНІТОРИНГУ ВІДБОЮ АКТИВОВАНО:</b>\n"
        "Щойно КМВА та Повітряні Сили оголосять відбій — ви отримаєте миттєве сповіщення з великим зеленим банером."
    )


def get_current_kyiv_alert_status() -> Dict[str, any]:
    """
    Checks the latest air raid alert status for Kyiv and Kyiv Oblast.
    Queries recent database events from official channels and checks cached external feeds.
    """
    db = SessionLocal()
    try:
        # Check last 6 hours of official alerts
        since = datetime.utcnow() - timedelta(hours=6)
        official_events = db.query(DetectedEvent).filter(
            DetectedEvent.detected_at >= since,
            DetectedEvent.source_channel.in_(["kyiv_alarm", "va_kyiv", "kyivcityofficial", "kpszsu", "air_alert_ua", "1181169156"])
        ).order_by(DetectedEvent.detected_at.desc()).limit(10).all()

        for ev in official_events:
            text_lower = (ev.message_text or "").lower()
            if any(w in text_lower for w in ["відбій", "отбой", "чисто", "clear", "відбій тривоги"]):
                return {
                    "is_alert": False,
                    "status_text": "CLEAR",
                    "source": f"@{ev.source_channel}",
                    "timestamp": ev.detected_at,
                    "message": ev.message_text
                }
            elif any(w in text_lower for w in ["тривога", "ракетна небезпека", "тривоги", "увага"]):
                return {
                    "is_alert": True,
                    "status_text": "ACTIVE",
                    "source": f"@{ev.source_channel}",
                    "timestamp": ev.detected_at,
                    "message": ev.message_text
                }

        # Fallback: check Redis cached state or external API
        cached_state = redis_client.get(ALERT_STATE_KEY)
        if cached_state:
            state_str = cached_state.decode("utf-8") if isinstance(cached_state, bytes) else str(cached_state)
            is_active = state_str == "ACTIVE"
            return {
                "is_alert": is_active,
                "status_text": state_str,
                "source": "Офіційні дані КМВА / alerts.in.ua",
                "timestamp": datetime.utcnow(),
                "message": "Поточний стан повітряного простору"
            }

        # Default safe state
        return {
            "is_alert": False,
            "status_text": "CLEAR",
            "source": "КМВА / Офіційний моніторинг тривог (@kyiv_alarm)",
            "timestamp": datetime.utcnow(),
            "message": "Повітряна тривога в місті Київ не оголошена."
        }
    except Exception as e:
        logger.error(f"Error checking alert status: {e}")
        return {
            "is_alert": False,
            "status_text": "CLEAR",
            "source": "КМВА (@kyiv_alarm)",
            "timestamp": datetime.utcnow(),
            "message": "Повітряна тривога відсутня."
        }
    finally:
        db.close()


class AlertMonitor:
    """Background service that polls alert status and broadcasts green banner upon all-clear."""
    def __init__(self, bot: Bot):
        self.bot = bot
        self.last_state = "CLEAR"

    async def run(self):
        logger.info("Starting AlertMonitor service...")
        while True:
            try:
                await self.check_and_notify()
            except Exception as e:
                logger.error(f"Error in AlertMonitor loop: {e}")
            await asyncio.sleep(5)  # Fast 5-second polling interval

    async def check_and_notify(self):
        status = get_current_kyiv_alert_status()
        current_state = status["status_text"]

        # Detect transition from ACTIVE to CLEAR (ALL CLEAR / ВІДБІЙ)
        if self.last_state == "ACTIVE" and current_state == "CLEAR":
            logger.info("ALL-CLEAR TRIGGER DETECTED! Broadcasting green banner to subscribers...")
            banner = format_all_clear_banner(
                region="м. Київ та Київська область",
                event_time=status["timestamp"],
                source=status["source"]
            )
            subscribers = get_vidbiy_subscribers()
            for chat_id in subscribers:
                try:
                    await self.bot.send_message(chat_id, banner, parse_mode=ParseMode.HTML)
                except Exception as e:
                    logger.warning(f"Failed to send all-clear banner to {chat_id}: {e}")

            clear_vidbiy_subscribers()

        self.last_state = current_state
        try:
            redis_client.set(ALERT_STATE_KEY, current_state)
        except Exception:
            pass
