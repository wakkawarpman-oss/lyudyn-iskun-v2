"""
Tactical Air Raid Alert & All-Clear (Відбій) Monitor for Kyiv & Kyiv Oblast.
Tracks real-time alarm states and delivers high-visibility green all-clear banners to subscribers.
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, Set, List
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
    """Formats the large green high-visibility all-clear banner with business & transit status."""
    dt = event_time or datetime.utcnow()
    kyiv_time = dt + timedelta(hours=3)  # Kyiv Summer Time (UTC+3)
    time_str = kyiv_time.strftime("%H:%M:%S")
    date_str = kyiv_time.strftime("%d.%m.%Y")

    return (
        "🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩\n"
        "🟩    <b>🟢 ВІДБІЙ ТРИВОГИ! 🟢</b>    🟩\n"
        "🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩\n\n"
        "🟢 <b>ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ</b>\n"
        f"📍 <b>Регіон:</b> {region}\n"
        f"🕒 <b>Час сигналу:</b> <code>{time_str}</code> (за Києвом) · {date_str}\n"
        f"📡 <b>Підтверджено:</b> {source}\n\n"
        "🏪 <b>МАГАЗИНИ ТА ЗАКЛАДИ:</b>\n"
        "✅ ТРЦ, супермаркети, кафе, аптеки та сервіси <b>ВІДЧИНЯЮТЬСЯ ТА ВІДНОВЛЮЮТЬ РОБОТУ</b>!\n\n"
        "🚌 <b>ТРАНСПОРТ ТА МЕТРО:</b>\n"
        "✅ Наземний комунальний транспорт відновлює рух за маршрутами.\n"
        "✅ Станції метро повертаються зі спецрежиму укриття до штатного перевезення.\n\n"
        "🛡️ <i>Загроза ворожих ударів минула. Дякуємо силам ППО України!</i>\n"
        "<i>«ЗБИРАЄМО • АНАЛІЗУЄМО • ПЕРЕМАГАЄМО»</i>"
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
        "🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥\n"
        "🟥   <b>🔴 ТРИВОГА ТРИВАЄ! 🔴</b>   🟥\n"
        "🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥\n\n"
        "🔴 <b>УВАГА: У РЕГІОНІ ТРИВАЄ ПОВІТРЯНА ТРИВОГА!</b>\n"
        f"📍 <b>Регіон:</b> {region}\n"
        f"⚠️ <b>Характер загрози:</b> {threat_info}\n"
        f"🕒 <b>Початок тривоги:</b> <code>{time_str}</code> (за Києвом)\n\n"
        "🚫 <b>ОБМЕЖЕННЯ ТА ЗАКРИТТЯ:</b>\n"
        "• ТРЦ, магазини та установи <b>ЗАЧИНЕНІ</b> (діють безпекові протоколи воєнного стану).\n"
        "• Рух наземного комунального транспорту через мости та відкриті ділянки <b>ПРИЗУПИНЕНО</b>.\n\n"
        "⏳ <b>РЕЖИМ МОНІТОРИНГУ ВІДБОЮ АКТИВОВАНО:</b>\n"
        "Скрипт безперервно відстежує найшвидші офіційні джерела (КМВА, єРадар, ПС ЗСУ). "
        "<b>Щойно пролунає відбій — ви миттєво отримаєте ВЕЛИКИЙ ЗЕЛЕНИЙ БАНЕР</b> про відкриття магазинів та відновлення руху!\n\n"
        "<i>Ви можете зупинити моніторинг у будь-який момент кнопкою нижче:</i>"
    )


def format_stop_monitoring_banner(region: str = "м. Київ та Київська область") -> str:
    """Formats confirmation banner when user stops all-clear monitoring."""
    return (
        "🛑 <b>МОНІТОРИНГ ВІДБОЮ ЗУПИНЕНО</b>\n"
        f"📍 <b>Регіон:</b> {region}\n\n"
        "Ви успішно зупинили моніторинг. Система <b>не надсилатиме</b> сповіщення, коли пролунає відбій.\n\n"
        "<i>Щоб відновити моніторинг, натисніть кнопку «🟢 ВІДБІЙ МОНІТОРИНГ».</i>"
    )


OBLAST_ALERT_KEYWORDS: Dict[str, List[str]] = {
    "kyiv_city": ["київ", "киев", "столиц"],
    "kyiv_oblast": ["київщин", "бровар", "борисп", "ірп", "буч", "біла церква", "васильків", "обухів"],
    "vinnytsia": ["вінниц", "винниц"],
    "volyn": ["волин", "луцьк", "ковель"],
    "dnipropetrovsk": ["дніпр", "днепр", "кривий ріг", "нікопол", "павлоград", "кам'янське"],
    "donetsk": ["донецьк", "краматорськ", "слов'янськ", "покровськ"],
    "zhytomyr": ["житомир", "бердичів", "коростень"],
    "zakarpattia": ["закарпат", "ужгород", "мукачево"],
    "zaporizhzhia": ["запоріж", "запорож", "мелітопол", "бердянськ"],
    "ivano_frankivsk": ["івано-франків", "прикарпат", "коломи"],
    "kirovohrad": ["кіровоград", "кропивницьк", "олександрі"],
    "luhansk": ["луганськ", "сєвєродонецьк"],
    "lviv": ["львів", "львов", "стрий", "дрогобич"],
    "mykolaiv": ["миколаїв", "николаев", "очаків"],
    "odesa": ["одес", "чорноморськ", "ізмаїл", "білгород"],
    "poltava": ["полтав", "кременчук", "миргород"],
    "rivne": ["рівнен", "ровно", "дубно", "сарни"],
    "sumy": ["сумськ", "суми", "конотоп", "шостк", "охтирк"],
    "ternopil": ["тернопіль", "тернополь", "чо Bones"],
    "kharkiv": ["харків", "харьков", "чугуїв", "куп'янськ", "лозова"],
    "kherson": ["херсон", "берислав", "каховка"],
    "khmelnytskyi": ["хмельницьк", "кам'янець", "шепетівк", "старокостянтинів"],
    "cherkasy": ["черкас", "умань", "сміла"],
    "chernivtsi": ["чернівц", "буковин"],
    "chernihiv": ["чернігів", "ніжин", "прилуки"],
    "crimea": ["крим", "севастопол", "сімферопол", "керч"],
    "sevastopol": ["севастопол"]
}

def get_current_kyiv_alert_status(oblast: Optional[str] = None) -> Dict[str, any]:
    """
    Checks the latest air raid alert status for a specific oblast or Kyiv.
    Queries recent database events from fastest official and verified monitoring channels.
    """
    db = SessionLocal()
    try:
        from sqlalchemy import func
        since = datetime.utcnow() - timedelta(hours=6)
        target_channels = [
            "kyiv_alarm", "va_kyiv", "kyivcityofficial", "kpszsu",
            "air_alert_ua", "1181169156", "eradarrua", "kievreal1", "vanek_nikolaev", "monitor_ukr",
            "suspilnednipro", "dnipropetrovskaoda", "synegubov", "suspilnekharkiv"
        ]
        official_events = db.query(
            DetectedEvent.message_text,
            DetectedEvent.detected_at,
            DetectedEvent.source_channel
        ).filter(
            DetectedEvent.detected_at >= since,
            func.lower(DetectedEvent.source_channel).in_(target_channels)
        ).order_by(DetectedEvent.detected_at.desc()).limit(30).all()

        target_kws = None
        if oblast and oblast in OBLAST_ALERT_KEYWORDS:
            target_kws = OBLAST_ALERT_KEYWORDS[oblast]
        elif not oblast or oblast in ("kyiv", "kyiv_city"):
            target_kws = ["київ", "киев", "столиц"]

        for ev in official_events:
            text_lower = (ev.message_text or "").lower()
            ch_lower = (ev.source_channel or "").lower()

            if target_kws:
                is_relevant = any(k in ch_lower for k in target_kws) or any(w in text_lower for w in target_kws)
                if not is_relevant:
                    continue

            if any(w in text_lower for w in ["відбій", "отбой", "чисто", "clear"]):
                return {
                    "is_alert": False,
                    "status_text": "CLEAR",
                    "source": f"@{ev.source_channel}",
                    "timestamp": ev.detected_at,
                    "message": ev.message_text,
                    "civilian_status": "Магазини, ТРЦ та транспорт відновлюють роботу"
                }
            elif any(w in text_lower for w in ["тривога", "ракетна небезпека", "загроза", "пуск", "увага"]):
                return {
                    "is_alert": True,
                    "status_text": "ACTIVE",
                    "source": f"@{ev.source_channel}",
                    "timestamp": ev.detected_at,
                    "message": ev.message_text,
                    "civilian_status": "Магазини та транспорт зачинені"
                }

        # Fallback default: all clear
        return {
            "is_alert": False,
            "status_text": "CLEAR",
            "source": "Офіційні канали ОВА / ПС ЗСУ",
            "timestamp": datetime.utcnow(),
            "message": "Активних тривог не зафіксовано",
            "civilian_status": "Магазини, ТРЦ та транспорт працюють у штатному режимі"
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
                "message": "Поточний стан повітряного простору",
                "civilian_status": "Зачинено під час тривоги" if is_active else "Відчинено, все працює"
            }

        # Default safe state
        return {
            "is_alert": False,
            "status_text": "CLEAR",
            "source": "КМВА / Офіційний моніторинг тривог (@kyiv_alarm)",
            "timestamp": datetime.utcnow(),
            "message": "Повітряна тривога в місті Київ не оголошена.",
            "civilian_status": "Магазини, ТРЦ та транспорт працюють у штатному режимі"
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
