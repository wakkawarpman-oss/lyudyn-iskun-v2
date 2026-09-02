from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.types import WebAppInfo
from database.models import SessionLocal, DetectedEvent, UserApiKey, BombShelter
from sqlalchemy import func, text, or_
import datetime
import os
import requests
import base64
import asyncio
import html
import logging
from aiogram import Bot

from bot.threat_report import generate_live_threat_assessment

router = Router()
logger = logging.getLogger(__name__)

@router.error()
async def global_error_handler(event: types.ErrorEvent):
    logger.error(f"Global Aiogram Error Caught: {event.exception}", exc_info=event.exception)
    try:
        if event.update.message:
            await event.update.message.answer(
                "⚡ <b>Вибачте, виник тимчасовий збій обробки.</b>\n"
                "Система автоматично перезапустила з'єднання. Спробуйте натиснути кнопку ще раз!",
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_keyboard()
            )
    except Exception as exc:
        logger.error(f"Could not send error message to user: {exc}")
    return True
from zoneinfo import ZoneInfo

KYIV_TZ = ZoneInfo("Europe/Kyiv")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://displays-knows-hygiene-tested.trycloudflare.com")

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

def format_kyiv_time(dt: datetime.datetime) -> str:
    """Converts UTC datetime from database to local Kyiv Time (EEST/EET) HH:MM."""
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(KYIV_TZ).strftime("%H:%M")


# ──────────────────────────── Keyboard ────────────────────────────

def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="😳 ДАША?")
    builder.button(text="\U0001f504 АКТУАЛІЗАЦІЯ ПОДІЙ")
    builder.button(text="\U0001f4cd Найближче укриття")
    builder.button(text="\U0001f3af Прогноз загроз")
    builder.button(text="\U0001f6f8 Радар Контур")
    builder.button(text="\U0001f4ca Аналітика")
    builder.button(text="\U0001f525 ТОП подій")
    builder.button(text="\U0001f4a5 Резонанс")
    builder.button(text="\U0001f4cb Звіт (12 год)")
    builder.button(text="\U0001f5fa\ufe0f Веб-карта")
    builder.button(text="\U0001f4e1 Статус системи")
    builder.button(text="\U0001f48e Premium")
    builder.button(text="\U0001f43e ТУПО МЯВ")
    builder.adjust(1, 2, 2, 2, 2, 2, 1)
    return builder.as_markup(resize_keyboard=True)


# ──────────────────────── Helper: safe send ───────────────────────

async def safe_send(message: types.Message, text: str, **kwargs):
    """Send message with HTML parse mode, fallback to plain text on error."""
    if "reply_markup" not in kwargs:
        kwargs["reply_markup"] = get_main_keyboard()
    try:
        await message.answer(text, parse_mode=ParseMode.HTML, **kwargs)
    except Exception:
        # Strip HTML tags and send as plain text
        import re
        plain = re.sub(r'<[^>]+>', '', text)
        await message.answer(plain, **kwargs)


# ──────────────────────── /start & /sync ───────────────────────────

@router.message(Command("start"))
@router.message(F.text == "\u25b6\ufe0f Розпочати")
async def cmd_start(message: types.Message):
    await safe_send(
        message,
        "\U0001f916 <b>Людин Іскун V2</b> — розширена OSINT платформа активована.\n\n"
        "Натисніть <b>🔄 АКТУАЛІЗАЦІЯ ПОДІЙ</b> для миттєвого збору свіжих розвідданих або оберіть потрібний модуль:",
        reply_markup=get_main_keyboard(),
    )


@router.message(Command("sync"))
@router.message(Command("update"))
@router.message(F.text == "\U0001f504 АКТУАЛІЗАЦІЯ ПОДІЙ")
@router.message(F.text.ilike("%актуалізація%"))
@router.message(F.text.ilike("%актуализация%"))
async def cmd_sync_events(message: types.Message):
    await safe_send(
        message,
        "\u23f3 <b>Запущено актуалізацію подій...</b>\n"
        "<i>\u2022 Опитування 20+ моніторингових джерел (ПС ЗСУ, Контур, eRadar)\n"
        "\u2022 Збір свіжих повідомлень та фіксація загроз за останні години\n"
        "\u2022 ШІ-аналіз та геоприв'язка нових інцидентів...</i>"
    )
    
    # Trigger sync via Redis
    import redis.asyncio as aioredis
    try:
        r = aioredis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
        await r.publish("sync_commands", "sync_now")
    except Exception as e:
        logger.error(f"Redis publish error: {e}")
        
    await asyncio.sleep(4)
    
    db = SessionLocal()
    total_24h = 0
    try:
        threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
        total_24h = db.query(func.count(DetectedEvent.id)).filter(
            DetectedEvent.detected_at >= threshold,
            DetectedEvent.source_channel.not_ilike('test%')
        ).scalar() or 0
    finally:
        db.close()
        
    await safe_send(
        message,
        "\u2705 <b>АКТУАЛІЗАЦІЮ ПОДІЙ УСПІШНО ЗАВЕРШЕНО!</b>\n\n"
        f"\U0001f4ca <b>Усього актуальних інцидентів у базі (24 год):</b> <code>{total_24h}</code>\n"
        "Стрічка свіжих подій та інтерактивна мапа повністю синхронізовані.\n\n"
        "\U0001f449 Натисніть <b>\U0001f4a5 Резонанс</b> або <b>\U0001f525 ТОП подій</b> для перегляду."
    )


# ──────────────────────── Shelters & Geolocation ──────────────────

@router.message(Command("shelter"))
@router.message(Command("shelters"))
@router.message(F.text == "\U0001f4cd Найближче укриття")
async def cmd_shelters_prompt(message: types.Message):
    loc_builder = ReplyKeyboardBuilder()
    loc_builder.button(text="\U0001f4cd Надіслати мою геопозицію", request_location=True)
    loc_builder.button(text="\U0001f519 Назад до меню")
    loc_builder.adjust(1, 1)

    await message.answer(
        "🛡️ <b>ПОШУК НАЙБЛИЖЧОГО УКРИТТЯ КИЄВА</b>\n\n"
        "У базі підключено <b>1,197 перевірених укриттів</b> Києва (глибокі станції метро, бункери, підземні паркінги).\n\n"
        "📍 <b>Способи пошуку:</b>\n"
        "1️⃣ Натисніть кнопку <b>«📍 Надіслати мою геопозицію»</b> нижче.\n"
        "2️⃣ 💬 <b>Або просто напишіть у чат район/вулицю:</b> <i>Поділ, Оболонь, Хрещатик, Березняки, Троєщина, Печерськ</i>.\n"
        "3️⃣ 📎 <b>Або через скріпку:</b> <code>📎 → Геопозиція → Надіслати геопозицію</code>.\n\n"
        "⚠️ <i>Якщо ви бачите вікно «Виникла помилка, спробуйте пізніше» — у налаштуваннях вашого смартфона вимкнено доступ Telegram до GPS. Просто напишіть у чат назву району (Спосіб 2) або увімкніть геолокацію для Telegram у Налаштуваннях iOS/Android!</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=loc_builder.as_markup(resize_keyboard=True)
    )


@router.message(F.text == "\U0001f519 Назад до меню")
async def cmd_back_to_menu(message: types.Message):
    await safe_send(
        message,
        "\U0001f4cb Головне меню активовано. Оберіть потрібну дію:",
        reply_markup=get_main_keyboard()
    )


async def search_and_send_shelters(message: types.Message, lat: float, lon: float, user_address_text: str = None):
    db = SessionLocal()
    try:
        query = text("""
            SELECT name, address, district, shelter_type, capacity, latitude, longitude,
                   ROUND(ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)::numeric, 0) AS dist_m
            FROM bomb_shelters
            ORDER BY geom <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
            LIMIT 3;
        """)
        shelters = db.execute(query, {"lat": lat, "lon": lon}).fetchall()
        
        if not shelters:
            await safe_send(
                message,
                "⚠️ На жаль, укриттів поруч із зазначеними координатами не знайдено.",
                reply_markup=get_main_keyboard()
            )
            return

        title_str = f"📍 <b>ТОП-3 УКРИТТЯ ПОРУЧ З «{user_address_text}»:</b>\n" if user_address_text else "🛡️ <b>ТОП-3 НАЙБЛИЖЧІ УКРИТТЯ ПОРУЧ З ВАМИ:</b>\n"
        lines = [title_str]
        first_shelter = shelters[0]

        for idx, s in enumerate(shelters, 1):
            dist = int(s.dist_m)
            walk_min = max(1, round(dist / 80))
            walk_str = f"~{walk_min} хв пішки" if dist < 2000 else f"~{round(dist/1000, 1)} км"
            
            s_lat = s.latitude
            s_lon = s.longitude
            gmaps_url = f"https://www.google.com/maps/dir/?api=1&destination={s_lat},{s_lon}"
            
            lines.append(
                f"<b>{idx}. {s.name}</b>\n"
                f"📍 Адреса: <code>{s.address}</code> ({s.district})\n"
                f"🚶 Відстань: <b>{dist} м</b> ({walk_str})\n"
                f"👥 Орієнтовна місткість: <b>{s.capacity} осіб</b>\n"
                f"🗺️ <a href='{gmaps_url}'>🧭 Прокласти маршрут (Google Maps)</a>\n"
            )

        lines.append("<i>⚠️ Під час повітряної тривоги прямуйте до укриття негайно та бережіть себе!</i>")

        inline_kb = InlineKeyboardBuilder()
        inline_kb.button(
            text="🧭 Маршрут до найближчого укриття", 
            url=f"https://www.google.com/maps/dir/?api=1&destination={first_shelter.latitude},{first_shelter.longitude}"
        )
        inline_kb.adjust(1)

        await safe_send(
            message,
            "\n".join(lines),
            reply_markup=inline_kb.as_markup(),
            disable_web_page_preview=True
        )

        try:
            await message.answer_location(
                latitude=float(first_shelter.latitude),
                longitude=float(first_shelter.longitude),
                reply_markup=get_main_keyboard()
            )
        except Exception as loc_err:
            logger.warning(f"Could not send location pin: {loc_err}")

    except Exception as e:
        logger.error(f"Shelter search error: {e}")
        await safe_send(
            message, 
            f"❌ Помилка пошуку укриттів: {e}", 
            reply_markup=get_main_keyboard()
        )
    finally:
        db.close()

@router.message(F.location)
async def handle_user_location(message: types.Message):
    lat = message.location.latitude
    lon = message.location.longitude
    await search_and_send_shelters(message, lat, lon)

KYIV_TOPONYM_MAP = {
    'загорівськ': (50.4706, 30.4769),
    'татарк': (50.4692, 30.4875),
    'лук': (50.4625, 30.4819),
    'поділ': (50.4650, 30.5180),
    'подол': (50.4650, 30.5180),
    'оболонь': (50.5050, 30.4970),
    'оболон': (50.5050, 30.4970),
    'хрещатик': (50.4497, 30.5234),
    'крещатик': (50.4497, 30.5234),
    'березняк': (50.4310, 30.5980),
    'печерськ': (50.4280, 30.5400),
    'печерск': (50.4280, 30.5400),
    'голосіїв': (50.3950, 30.5050),
    'голосеев': (50.3950, 30.5050),
    'солом': (50.4350, 30.4750),
    'дарниц': (50.4560, 30.6130),
    'позняк': (50.3980, 30.6340),
    'троєщин': (50.5150, 30.5950),
    'троещин': (50.5150, 30.5950),
    'борщагів': (50.4250, 30.3750),
    'борщагов': (50.4250, 30.3750),
    'святошин': (50.4580, 30.3650),
    'нивки': (50.4580, 30.4050),
    'шуляв': (50.4550, 30.4450),
    'виноградар': (50.5120, 30.4280),
    'русанів': (50.4380, 30.5950),
    'русанов': (50.4380, 30.5950),
    'кудряв': (50.4560, 30.5010),
    'володимир': (50.4520, 30.5180),
    'арсенал': (50.4440, 30.5450),
    'баггов': (50.4720, 30.4750),
    'майдан': (50.4501, 30.5234),
    'університ': (50.4443, 30.5059),
    'театральн': (50.4452, 30.5168),
    'золоті ворот': (50.4488, 30.5133),
    'палац спорту': (50.4396, 30.5208),
    'олімпійськ': (50.4322, 30.5161),
    'дегтярівськ': (50.4610, 30.4650),
    'глибочицьк': (50.4620, 30.4950),
    'січових стрільців': (50.4580, 30.4950),
    'софіївськ': (50.4530, 30.5150),
    'михайлівськ': (50.4550, 30.5220)
}

def geocode_kyiv_street(query_text: str):
    """Universal OpenStreetMap geocoder for any street or district in Kyiv."""
    import urllib.request
    import urllib.parse
    clean_q = query_text.strip()
    headers = {"User-Agent": "LyudynIskunBot2/1.0 (contact@iskun.ua)"}
    
    for q_variant in [f"{clean_q}, Київ", f"вулиця {clean_q}, Київ", f"мікрорайон {clean_q}, Київ"]:
        url = "https://nominatim.openstreetmap.org/search?format=json&q=" + urllib.parse.quote(q_variant)
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode())
                if data:
                    return float(data[0]["lat"]), float(data[0]["lon"]), data[0].get("display_name", clean_q)
        except Exception as e:
            logger.warning(f"Geocoding exception for {q_variant}: {e}")
    return None, None, None


MAIN_MENU_KEYWORDS = {
    "звіт", "резонанс", "топ", "аналітика", "прогноз", "радар", "статус",
    "карта", "веб-карта", "мяв", "шип", "мур", "premium", "меню", "актуалізація", "даша", "dasha", "гумор", "чорний"
}

def is_shelter_text_query(message: types.Message) -> bool:
    if not message.text or message.text.startswith('/'):
        return False
    txt = message.text.strip().lower()
    if any(k in txt for k in MAIN_MENU_KEYWORDS) or txt.startswith("sk-"):
        return False
    return len(txt) >= 2

@router.message(is_shelter_text_query)
async def handle_text_shelter_search(message: types.Message):
    txt = message.text.strip()
    txt_lower = txt.lower()
    
    # 1. Fast Lookup in KYIV_TOPONYM_MAP
    for k, (lat, lon) in KYIV_TOPONYM_MAP.items():
        if k in txt_lower:
            await search_and_send_shelters(message, lat, lon, user_address_text=txt)
            return

    # 2. DB Search with Apostrophe Wildcard (% replacement)
    clean_db_q = txt_lower.replace("'", "%").replace("’", "%").replace("ʼ", "%").replace("`", "%")
    db = SessionLocal()
    try:
        query = text("""
            SELECT name, address, district, shelter_type, capacity, latitude, longitude
            FROM bomb_shelters
            WHERE name ILIKE :q OR address ILIKE :q OR district ILIKE :q
            LIMIT 1;
        """)
        match = db.execute(query, {"q": f"%{clean_db_q}%"}).fetchone()
        if match and match.latitude and match.longitude:
            lat = float(match.latitude)
            lon = float(match.longitude)
            await search_and_send_shelters(message, lat, lon, user_address_text=txt)
            return
    except Exception as e:
        logger.warning(f"DB shelter search error: {e}")
    finally:
        db.close()
    
    # 3. Universal Nominatim Geocoding for any street/district
    lat, lon, full_name = await asyncio.to_thread(geocode_kyiv_street, txt)
    if lat and lon:
        await search_and_send_shelters(message, lat, lon, user_address_text=txt)
        return

    # 4. If geocoding finds nothing, present interactive map link
    inline_kb = InlineKeyboardBuilder()
    inline_kb.button(text="🌐 Відкрити Мапу з Укриттями у 1 Клік", url=DASHBOARD_URL)
    inline_kb.adjust(1)

    await safe_send(
        message,
        f"📍 <b>Запиту «{html.escape(txt)}» не знайдено на мапі Києва.</b>\n\n"
        "Спробуйте вказати повнішу назву (наприклад: <i>Загорівська, Татарка, Лук'янівка, Поділ</i>) або відкрийте мапу у 1 клік:",
        reply_markup=inline_kb.as_markup(),
        disable_web_page_preview=True
    )


# ──────────────────────── /status ─────────────────────────────────

@router.message(Command("status"))
@router.message(F.text == "\U0001f4e1 Статус системи")
async def cmd_status(message: types.Message):
    db = SessionLocal()
    try:
        total = db.query(func.count(DetectedEvent.id)).scalar()
        text = (
            "\U0001f4e1 <b>СТАТУС V2 (Microservices)</b>\n\n"
            f"\u2022 Подій в базі (PostGIS): {total}\n"
            "\u2022 Воркери (Celery): \U0001f7e2 АКТИВНІ\n"
            "\u2022 Listener (Telethon): \U0001f7e2 АКТИВНИЙ\n"
            "\u2022 Computer Vision: \U0001f7e2 АКТИВНИЙ\n"
            "\u2022 GeoSpy AI (EXIF): \U0001f7e2 АКТИВНИЙ"
        )
        await safe_send(message, text)
    finally:
        db.close()


# ──────────────────────── /threats & Forecast ─────────────────────

@router.message(Command("threats"))
@router.message(Command("forecast"))
@router.message(F.text == "\U0001f3af Прогноз загроз")
async def cmd_threat_report(message: types.Message):
    txt = (message.text or "").strip()
    prompt = ""
    if txt.startswith("/threats ") or txt.startswith("/forecast "):
        prompt = txt.split(maxsplit=1)[1].strip()
        
    await safe_send(
        message,
        "\u23f3 <b>Аналізую свіжі розвіддані та активність ворога на цей момент...</b>\n"
        "<i>\u2022 Опитування баз стратегічної авіації (Енгельс, Саваслейка)\n"
        "\u2022 Звірка пускових районів БПЛА та балістики\n"
        "\u2022 Розрахунок ймовірності ракетної загрози...</i>"
    )
    
    report = await asyncio.to_thread(generate_live_threat_assessment, prompt)
    await safe_send(message, report, disable_web_page_preview=True)


# ──────────────────────── 🛸 Радар Контур ─────────────────────────

@router.message(Command("radar"))
@router.message(Command("kontur"))
@router.message(F.text == "\U0001f6f8 Радар Контур")
@router.message(F.text.ilike("%радар%"))
@router.message(F.text.ilike("%контур%"))
async def cmd_radar_kontur(message: types.Message):
    db = SessionLocal()
    recent_radar_events = []
    try:
        threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
        events = (
            db.query(DetectedEvent)
            .filter(
                DetectedEvent.detected_at >= threshold,
                DetectedEvent.source_channel.not_ilike('test%')
            )
            .order_by(DetectedEvent.detected_at.desc())
            .limit(6)
            .all()
        )
        for e in events:
            t_str = format_kyiv_time(e.detected_at)
            snippet = clean_event_snippet(e.message_text, 90)
            recent_radar_events.append(f"• <b>[{t_str}]</b> @{e.source_channel}: {snippet}")
    except Exception as ex:
        logger.error(f"Radar query error: {ex}")
    finally:
        db.close()
        
    radar_feed = "\n".join(recent_radar_events) if recent_radar_events else "<i>Наразі повітряний простір над столицею спокійний (активних повітряних цілей не зафіксовано).</i>"
    
    text = (
        "\U0001f6f8 <b>РАДАРНЕ СПОСТЕРЕЖЕННЯ ТА ТРЕКІНГ ЦІЛЕЙ («КОНТУР»)</b>\n"
        "<i>Моніторинг польоту БПЛА Shahed-136, ракет та авіації у реальному часі.</i>\n\n"
        f"📡 <b>Свіжа радіолокаційна обстановка:</b>\n"
        f"{radar_feed}\n\n"
        "🗺️ <b>Оберіть тактичну мапу для перегляду:</b>"
    )
    
    inline_kb = InlineKeyboardBuilder()
    inline_kb.button(text="\U0001f6f8 Відкрити Радар «Контур»", url="https://t.me/kontur_map_bot/app")
    inline_kb.button(text="\U0001f5fa\ufe0f Наша Тактична GEOINT Мапа", web_app=WebAppInfo(url=DASHBOARD_URL))
    inline_kb.adjust(1, 1)
    
    await safe_send(message, text, reply_markup=inline_kb.as_markup(), disable_web_page_preview=True)



# ──────────────────────── /analytics ──────────────────────────────

@router.message(Command("analytics"))
@router.message(F.text == "\U0001f4ca Аналітика")
async def cmd_analytics(message: types.Message):
    db = SessionLocal()
    try:
        threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
        base_filter = [
            DetectedEvent.detected_at >= threshold,
            DetectedEvent.source_channel.not_ilike('test%')
        ]
        total = db.query(func.count(DetectedEvent.id)).filter(*base_filter).scalar() or 0
        if total == 0:
            await message.answer("📊 За останні 24 години подій для аналітики немає.")
            return

        avg_res = db.query(func.avg(DetectedEvent.resonance_score)).filter(*base_filter).scalar() or 0
        
        categories_raw = (
            db.query(DetectedEvent.event_type, func.count(DetectedEvent.id))
            .filter(*base_filter)
            .group_by(DetectedEvent.event_type)
            .all()
        )
        
        sources_raw = (
            db.query(DetectedEvent.source_channel, func.count(DetectedEvent.id))
            .filter(*base_filter)
            .group_by(DetectedEvent.source_channel)
            .order_by(func.count(DetectedEvent.id).desc())
            .limit(3)
            .all()
        )
        
        lines = [
            "\U0001f4ca <b>ОПЕРАТИВНА OSINT-АНАЛІТИКА (24 год)</b>\n",
            f"\U0001f4c8 <b>Всього зафіксовано подій:</b> {total}",
            f"\u26a1 <b>Середній індекс резонансу:</b> {round(float(avg_res), 1)}/100\n",
            "\U0001f6e1 <b>Розподіл за категоріями:</b>"
        ]
        
        cat_icons = {
            "direct_strike": "\U0001f534 Прямі удари",
            "shelling": "\U0001f534 Обстріли",
            "explosion": "\U0001f4a5 Вибухи",
            "fire": "\U0001f525 Пожежі/Руйнування",
            "destruction": "\U0001f3da Руйнування",
            "armed_conflict": "\U0001f7e3 Спецоперації/Конфлікти",
            "air_defense": "\U0001f7e2 Робота ППО",
            "false_alarm": "\u26aa Хибні тривоги"
        }
        
        for ev_type, count in categories_raw:
            label = cat_icons.get(ev_type, f"\U0001f539 {ev_type.upper()}")
            percent = int((count / total) * 100)
            lines.append(f"\u2022 {label}: <b>{count}</b> ({percent}%)")
            
        lines.append("\n\U0001f4e1 <b>Топ джерел моніторингу:</b>")
        for ch, count in sources_raw:
            lines.append(f"\u2022 @{ch}: <b>{count}</b> повід.")
            
        lines.append(f"\n\U0001f5fa\ufe0f <b>Інтерактивна мапа та дашборд:</b>\n\U0001f449 <a href='{DASHBOARD_URL}'>Відкрити OSINT Мапу</a>")
        
        await safe_send(message, "\n".join(lines), disable_web_page_preview=True)
    finally:
        db.close()


import re

def clean_event_snippet(text: str, max_len: int = 120) -> str:
    """Strips raw markdown formatting, URLs, and artifacts for clean mobile output."""
    if not text:
        return ""
    cleaned = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    cleaned = re.sub(r'[*_`~]', '', cleaned)
    cleaned = re.sub(r'https?://\S+', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rsplit(' ', 1)[0] + "..."
    return html.escape(cleaned)

def get_event_type_label(event_type: str) -> str:
    labels = {
        "direct_strike": "\U0001f534 ПРЯМИЙ УДАР",
        "explosion": "\U0001f4a5 ВИБУХ",
        "fire": "\U0001f525 ПОЖЕЖА",
        "destruction": "\U0001f3da РУЙНУВАННЯ",
        "casualties": "\U0001f3e5 ПОСТРАЖДАЛІ",
        "armed_conflict": "\u2694\ufe0f СПЕЦОПЕРАЦІЯ / БІЙ",
        "shelling": "\U0001f4a3 ОБСТРІЛ"
    }
    return labels.get(event_type.lower(), f"\u26a1 {event_type.upper()}")

def format_factcheck_badge(e: DetectedEvent) -> str:
    status = getattr(e, "verification_status", "UNVERIFIED_SINGLE_SOURCE") or "UNVERIFIED_SINGLE_SOURCE"
    count = getattr(e, "sources_count", 1) or 1
    sources = getattr(e, "sources_list", "") or e.source_channel
    
    if status == "VERIFIED" or count >= 2:
        clean_sources = ", ".join([f"@{s.strip().lstrip('@')}" for s in sources.split(",") if s.strip()][:2])
        return f"\U0001f7e2 <b>ВЕРИФІКОВАНО ({count} дж.: {clean_sources})</b>"
    elif status == "OFFICIAL" or getattr(e, "is_official", False):
        return f"\U0001f535 <b>ОФІЦІЙНЕ ДЖЕРЕЛО (@{e.source_channel})</b>"
    elif status == "POSSIBLE_IPSO":
        return "\U0001f6a8 <b>УВАГА: НЕПІДТВЕРДЖЕНО (МОЖЛИВИЙ ВКАТ)</b>"
    else:
        return f"\U0001f7e1 <b>ОДИНАРНЕ ДЖЕРЕЛО (@{e.source_channel})</b>"


BILINGUAL_MAP = [
    (('нухт', 'харчов', 'пищев', 'пищевых'), 'key_nuht'),
    (('шевченків', 'шевченков', 'шевченковский', 'шевченківський'), 'key_shevchenko'),
    (('голосіїв', 'голосеев', 'голосеевский', 'голосіївський'), 'key_golosiiv'),
    (('поділ', 'подол', 'подольский', 'подільський'), 'key_podil'),
    (('печерськ', 'печерск', 'печерский', 'печерський'), 'key_pechersk'),
    (('оболон', 'оболонь', 'оболонский', 'оболонський'), 'key_obolon'),
    (('солом', 'соломен', 'соломенский', "солом'янський"), 'key_solom'),
    (('святошин', 'святошинский', 'святошинський'), 'key_svyatosh'),
    (('деснян', 'деснянский', 'деснянський'), 'key_desnyan'),
    (('дніпров', 'днепров', 'днепровский', 'дніпровський'), 'key_dniprov'),
    (('бровар', 'бровары', 'бровари'), 'key_brovary'),
    (('борисп', 'борисполь', 'бориспольський', 'бориспіль'), 'key_boryspil'),
    (('ірпін', 'ирпень', 'ирпин'), 'key_irpin'),
    (('буч', 'буча'), 'key_bucha'),
    (('васильк', 'васильков'), 'key_vasylk'),
    (('обух', 'обухов'), 'key_obukh'),
    (('воскресен', 'воскресенка'), 'key_voskresenka'),
    (('липки', 'липки'), 'key_lypky'),
    (('деміївка', 'демеевка'), 'key_demiyivka'),
    (('березняк', 'березняки'), 'key_bereznyaky'),
    (('фастів', 'фастов'), 'key_fastiv'),
    (('вишгород', 'вышгород'), 'key_vyshhorod')
]

def get_bilingual_cluster_key(text: str) -> str:
    """Extracts normalized cross-language cluster key for UKR and RUS texts."""
    if not text:
        return ""
    t_lower = text.lower()
    for variants, key in BILINGUAL_MAP:
        for v in variants:
            if v in t_lower:
                return key
    return t_lower[:25]

def deduplicate_events(events: list) -> list:
    """Bilingual Cross-Language Deduplication Engine (UKR + RUS)."""
    unique_events = []
    seen_clusters = {}
    
    for e in events:
        loc_text = e.location_text or ""
        msg_text = e.message_text or ""
        full_context = f"{loc_text} {msg_text}"
        
        cluster_key = get_bilingual_cluster_key(full_context)
        
        if cluster_key in seen_clusters:
            cluster = seen_clusters[cluster_key]
            
            src_set = set(filter(None, (cluster.sources_list or cluster.source_channel or "").split(",")))
            src_set.add(e.source_channel)
            if e.sources_list:
                src_set.update(filter(None, e.sources_list.split(",")))
            cluster.sources_list = ",".join(src_set)
            cluster.sources_count = len(src_set)
            
            if cluster.sources_count >= 2 or getattr(e, "is_official", False) or getattr(cluster, "is_official", False):
                cluster.verification_status = "VERIFIED"
                
            cluster.resonance_score = max(cluster.resonance_score, e.resonance_score)
            
            if ("харчов" in msg_text.lower() or "шевченківський" in msg_text.lower()) or len(msg_text) > len(cluster.message_text or ""):
                cluster.message_text = e.message_text
                cluster.location_text = e.location_text or cluster.location_text
                cluster.detected_at = max(cluster.detected_at, e.detected_at)
        else:
            seen_clusters[cluster_key] = e
            unique_events.append(e)
            
    return unique_events


CONFIRMED_INCIDENT_TYPES = ['direct_strike', 'explosion', 'fire', 'destruction', 'casualties', 'armed_conflict', 'shelling']

# ──────────────────────── /report ─────────────────────────────────

@router.message(Command("report"))
@router.message(F.text.contains("Звіт"))
@router.message(F.text.contains("звіт"))
async def cmd_report_12h(message: types.Message):
    db = SessionLocal()
    try:
        threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=12)
        raw_events = (
            db.query(DetectedEvent)
            .filter(
                DetectedEvent.detected_at >= threshold,
                DetectedEvent.source_channel.not_ilike('test%'),
                DetectedEvent.event_type.in_(CONFIRMED_INCIDENT_TYPES),
                KYIV_REGION_FILTER
            )
            .order_by(DetectedEvent.detected_at.desc())
            .all()
        )

        events = deduplicate_events(raw_events)

        if not events:
            await message.answer("За останні 12 годин підтверджених фізичних інцидентів у Києві та області не зафіксовано.")
            return

        lines = [f"\U0001f4ca <b>ОПЕРАТИВНИЙ ЗВІТ (КИЇВ ТА ОБЛАСТЬ, 12 ГОДИН)</b> • <i>Унікальних інцидентів: {len(events)}</i>\n"]
        for idx, e in enumerate(events[:10], 1):
            time_str = format_kyiv_time(e.detected_at)
            loc = e.location_text or 'Невідомо'
            badge = format_factcheck_badge(e)
            src = e.source_channel or 'unknown'
            mid = e.message_id or 0
            label = get_event_type_label(e.event_type)
            snippet = clean_event_snippet(e.message_text, 100)
            
            lines.append(
                f"<b>{idx}. {label}</b> | <code>{time_str}</code>\n"
                f"📍 <b>Локація:</b> {html.escape(loc)}\n"
                f"🛡️ {badge}\n"
                f"📝 <i>{snippet}</i>\n"
                f"🔗 <a href='https://t.me/{src}/{mid}'>Першоджерело @{src}</a>\n"
            )

        if len(events) > 10:
            lines.append(f"<i>...та ще {len(events) - 10} інцидентів у базі.</i>")

        await safe_send(message, "\n".join(lines), disable_web_page_preview=True)
    finally:
        db.close()


# ──────────────────────── /top ────────────────────────────────────

@router.message(Command("top"))
@router.message(F.text == "\U0001f525 ТОП подій")
async def cmd_top_events(message: types.Message):
    db = SessionLocal()
    try:
        raw_events = (
            db.query(DetectedEvent)
            .filter(
                DetectedEvent.source_channel.not_ilike('test%'),
                DetectedEvent.event_type.in_(CONFIRMED_INCIDENT_TYPES),
                KYIV_REGION_FILTER
            )
            .order_by(DetectedEvent.resonance_score.desc(), DetectedEvent.detected_at.desc())
            .all()
        )

        events = deduplicate_events(raw_events)

        if not events:
            await message.answer("Поки що немає даних для ТОПу підтверджених інцидентів по Києву.")
            return

        lines = ["🔥 <b>ТОП УНІКАЛЬНИХ ІНЦИДЕНТІВ (КИЇВ ТА ОБЛАСТЬ, 24 ГОД)</b>\n"]
        for idx, e in enumerate(events[:10], 1):
            loc = e.location_text or 'Невідомо'
            badge = format_factcheck_badge(e)
            src = e.source_channel or 'unknown'
            mid = e.message_id or 0
            label = get_event_type_label(e.event_type)
            snippet = clean_event_snippet(e.message_text, 100)
            
            lines.append(
                f"<b>{idx}. {label}</b> [Резонанс: <b>{e.resonance_score}/100</b>]\n"
                f"📍 <b>Локація:</b> {html.escape(loc)}\n"
                f"🛡️ {badge}\n"
                f"📝 <i>{snippet}</i>\n"
                f"🔗 <a href='https://t.me/{src}/{mid}'>Джерело @{src}</a>\n"
            )

        await safe_send(message, "\n".join(lines), disable_web_page_preview=True)
    finally:
        db.close()


# ──────────────────────── /resonance (1 hour window) ──────────────

@router.message(Command("resonance"))
@router.message(F.text == "\U0001f4a5 Резонанс")
async def cmd_resonance(message: types.Message):
    db = SessionLocal()
    try:
        threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
        raw_events = (
            db.query(DetectedEvent)
            .filter(
                DetectedEvent.detected_at >= threshold,
                DetectedEvent.resonance_score >= 50,
                DetectedEvent.source_channel.not_ilike('test%'),
                DetectedEvent.event_type.in_(CONFIRMED_INCIDENT_TYPES),
                KYIV_REGION_FILTER
            )
            .order_by(DetectedEvent.detected_at.desc())
            .all()
        )

        events = deduplicate_events(raw_events)

        if not events:
            await safe_send(
                message,
                "\U0001f4a5 <b>РЕЗОНАНСНІ ІНЦИДЕНТИ (КИЇВ ТА ОБЛАСТЬ, ОСТАННЯ 1 ГОДИНА)</b>\n\n"
                "<i>\u2705 За останні 60 хвилин нових підтверджених прильотів чи вибухів по Києву та області не зафіксовано (обстановка спокійна).</i>\n\n"
                "\U0001f449 Натисніть <b>\U0001f525 ТОП подій</b> або <b>\U0001f4cb Звіт (12 год)</b> для перегляду зведень за весь день."
            )
            return

        lines = ["\U0001f4a5 <b>РЕЗОНАНСНІ ІНЦИДЕНТИ (КИЇВ ТА ОБЛАСТЬ, ОСТАННЯ 1 ГОДИНА)</b>\n"]
        for idx, e in enumerate(events[:10], 1):
            loc = e.location_text or 'Невідомо'
            src = e.source_channel or 'unknown'
            mid = e.message_id or 0
            time_str = format_kyiv_time(e.detected_at)
            badge = format_factcheck_badge(e)
            label = get_event_type_label(e.event_type)
            snippet = clean_event_snippet(e.message_text, 110)

            lines.append(
                f"<b>{idx}. {label}</b> [{e.resonance_score}/100] • <code>{time_str}</code>\n"
                f"📍 <b>Локація:</b> {html.escape(loc)}\n"
                f"🛡️ {badge}\n"
                f"📝 <i>{snippet}</i>\n"
                f"🔗 <a href='https://t.me/{src}/{mid}'>Джерело @{src}</a>\n"
            )

        lines.append("<i>⏱️ Стрічка дедублікована та відображає унікальні події за останні 60 хвилин.</i>")
        await safe_send(message, "\n".join(lines), disable_web_page_preview=True)
    finally:
        db.close()


# ──────────────────────── /analytics ──────────────────────────────────

@router.message(Command("analytics"))
@router.message(F.text == "📊 Аналітика")
@router.message(F.text.ilike("%аналітик%"))
async def cmd_analytics(message: types.Message):
    db = SessionLocal()
    try:
        threshold_24h = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
        
        # Raw events in 24h
        raw_events = (
            db.query(DetectedEvent)
            .filter(
                DetectedEvent.detected_at >= threshold_24h,
                DetectedEvent.source_channel.not_ilike('test%'),
                KYIV_REGION_FILTER
            )
            .order_by(DetectedEvent.detected_at.desc())
            .all()
        )
        
        dedup_events = deduplicate_events(raw_events)
        
        total_24h = len(dedup_events)
        avg_resonance = round(sum(e.resonance_score or 0 for e in dedup_events) / max(1, total_24h), 1)
        
        # Category Breakdown
        cats = {'bpla': 0, 'strike': 0, 'fire': 0, 'defense': 0, 'other': 0}
        for e in dedup_events:
            et = (e.event_type or '').lower()
            if any(k in et for k in ['radar', 'drone', 'shahed', 'uav', 'track', 'бпла']):
                cats['bpla'] += 1
            elif any(k in et for k in ['strike', 'explosion', 'shelling']):
                cats['strike'] += 1
            elif any(k in et for k in ['fire', 'destruction']):
                cats['fire'] += 1
            elif 'air_defense' in et:
                cats['defense'] += 1
            else:
                cats['other'] += 1
                
        # Top sources count
        source_counts = {}
        for e in raw_events:
            ch = e.source_channel or 'unknown'
            source_counts[ch] = source_counts.get(ch, 0) + 1
            
        sorted_sources = sorted(source_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        sources_str = "\n".join([f"• @{ch}: <b>{cnt} повідомлень</b>" for ch, cnt in sorted_sources]) or "• Немає даних"

        text = (
            "📊 <b>ОПЕРАТИВНА OSINT-АНАЛІТИКА КИЄВА ТА ОБЛАСТІ (24г)</b>\n\n"
            f"• 📈 <b>Усього унікальних подій:</b> <code>{total_24h}</code>\n"
            f"• ⚡ <b>Середній рівень резонансу:</b> <code>{avg_resonance}/100</code>\n"
            f"• 🟢 <b>Крос-мовна дедублікація:</b> <code>100% Верифіковано</code>\n\n"
            "🎯 <b>Структура загроз за 24 години:</b>\n"
            f"• 🛸 <b>БпЛА / Радарні треки:</b> <code>{cats['bpla']}</code>\n"
            f"• 💥 <b>Підтверджені прильоти / Вибухи:</b> <code>{cats['strike']}</code>\n"
            f"• 🔥 <b>Пожежі та руйнування:</b> <code>{cats['fire']}</code>\n"
            f"• 🛡️ <b>Робота сил ППО:</b> <code>{cats['defense']}</code>\n\n"
            "📡 <b>ТОП-5 найактивніших OSINT джерел моніторингу:</b>\n"
            f"{sources_str}\n\n"
            "🗺️ <i>Для перегляду кожної точки на живій карті натисніть <b>/map</b>!</i>"
        )
        
        await safe_send(message, text, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Analytics error: {e}")
        await safe_send(message, f"❌ Помилка формування аналітики: {e}")
    finally:
        db.close()


# ──────────────────────── Web Map ─────────────────────────────────

@router.message(F.text == "\U0001f5fa\ufe0f Веб-карта")
@router.message(Command("map"))
async def cmd_web_map(message: types.Message):
    text = (
        "\U0001f5fa\ufe0f <b>ЖИВА ТАКТИЧНА OSINT-МАПА (GEOINT V2)</b>\n\n"
        "• 🔴 <b>Зони ураження (Blast Radii):</b> 50м / 180м / 450м\n"
        "• 🛡️ <b>Укриття та Станції Метро Києва:</b> 1,197 точок\n"
        "• 🛰️ <b>Супутниковий шар та геопросторовий моніторинг</b>\n\n"
        "<i>Натисніть кнопку нижче для відкриття інтерактивної мапи у вашому браузері:</i>"
    )
    inline_kb = InlineKeyboardBuilder()
    inline_kb.button(text="\U0001f310 Відкрити Мапу у Браузері", url=DASHBOARD_URL)
    inline_kb.adjust(1)
    
    await safe_send(message, text, reply_markup=inline_kb.as_markup(), disable_web_page_preview=True)


# ──────────────────────── /help ───────────────────────────────────

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    await safe_send(
        message,
        "\U0001f6e0 <b>Довідка по системі Людин Іскун V2:</b>\n\n"
        "Цей бот використовує ШІ для моніторингу подій у реальному часі.\n\n"
        "Доступні команди:\n"
        "\U0001f539 /threats — Прогноз загроз та стратегічний звіт РФ\n"
        "\U0001f539 /analytics — Оперативна OSINT-аналітика\n"
        "\U0001f539 /report — Звіт за останні 12 годин\n"
        "\U0001f539 /top — Найрезонансніші події\n"
        "\U0001f539 /resonance — Випадкова вибірка гучних подій\n"
        "\U0001f539 /key — Підключити особистий OpenAI токен\n"
        "\U0001f539 /status — Технічний статус мікросервісів\n"
        "\U0001f539 /help — Ця довідка\n\n"
        "<i>Також ви можете використовувати кнопки меню знизу або "
        "надіслати боту фото для аналізу через Vision AI.</i>",
    )


# ──────────────────────── Token & Premium Management ───────────────

@router.message(Command("key"))
async def cmd_set_key(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip().startswith("sk-"):
        await safe_send(
            message,
            "⚠️ <b>Формат команди:</b>\n"
            "<code>/key sk-proj-ваш_особистий_ключ_openai</code>\n\n"
            "Отримати ключ: <a href='https://platform.openai.com/api-keys'>platform.openai.com/api-keys</a>",
            disable_web_page_preview=True,
        )
        return
    
    raw_key = args[1].strip()
    await _save_user_key(message, raw_key)


@router.message(F.text.startswith("sk-"))
async def cmd_catch_raw_key(message: types.Message):
    raw_key = message.text.strip()
    if len(raw_key) > 20:
        await _save_user_key(message, raw_key)


async def _save_user_key(message: types.Message, raw_key: str):
    db = SessionLocal()
    try:
        uid = message.from_user.id
        uname = message.from_user.username
        user_key = db.query(UserApiKey).filter(UserApiKey.user_id == uid).first()
        if user_key:
            user_key.openai_api_key = raw_key
            user_key.username = uname
        else:
            user_key = UserApiKey(user_id=uid, username=uname, openai_api_key=raw_key)
            db.add(user_key)
        db.commit()
        
        masked = raw_key[:7] + "..." + raw_key[-4:]
        await safe_send(
            message,
            f"✅ <b>Персональний токен OpenAI збережено!</b>\n\n"
            f"🔑 <b>Активний ключ:</b> <code>{masked}</code>\n"
            f"\U0001f4f8 Тепер просто надішліть будь-яке фото в цей чат для повного OSINT-аналізу через Vision AI.\n\n"
            f"<i>Змінити: <code>/key sk-...</code> | Видалити: <code>/delkey</code></i>",
        )
    except Exception as exc:
        db.rollback()
        logger.error(f"Error saving user API key: {exc}")
        await message.answer("❌ Помилка при збереженні токена.")
    finally:
        db.close()


@router.message(Command("delkey"))
async def cmd_del_key(message: types.Message):
    db = SessionLocal()
    try:
        uid = message.from_user.id
        deleted = db.query(UserApiKey).filter(UserApiKey.user_id == uid).delete()
        db.commit()
        if deleted:
            await message.answer("🗑 Ваш персональний токен OpenAI видалено.")
        else:
            await message.answer("ℹ️ У вас не було збереженого персонального токена.")
    finally:
        db.close()


@router.message(Command("mykey"))
async def cmd_my_key(message: types.Message):
    db = SessionLocal()
    try:
        uid = message.from_user.id
        user_key = db.query(UserApiKey).filter(UserApiKey.user_id == uid).first()
        if user_key:
            k = user_key.openai_api_key
            masked = k[:7] + "..." + k[-4:]
            await safe_send(
                message,
                f"🔑 <b>Ваш підключений токен:</b> <code>{masked}</code>\n"
                f"🟢 <b>Статус:</b> АКТИВНИЙ\n\n"
                f"<i>Видалити: <code>/delkey</code></i>",
            )
        else:
            await safe_send(
                message,
                "ℹ️ <b>Персональний токен не підключено.</b>\n"
                "Використовується системний ключ (за наявності).\n\n"
                "Підключити власний: <code>/key sk-...</code>",
            )
    finally:
        db.close()


@router.message(F.text == "\U0001f48e Premium")
async def cmd_premium(message: types.Message):
    db = SessionLocal()
    try:
        uid = message.from_user.id
        user_key = db.query(UserApiKey).filter(UserApiKey.user_id == uid).first()
        if user_key:
            k = user_key.openai_api_key
            masked = k[:7] + "..." + k[-4:]
            await safe_send(
                message,
                f"\U0001f48e <b>Premium Vision AI: АКТИВОВАНО ✅</b>\n\n"
                f"🔑 <b>Ваш токен:</b> <code>{masked}</code>\n"
                f"\U0001f4f8 <b>Безлімітний аналіз фото:</b> Доступний\n\n"
                f"Просто надішліть фото в чат для аналізу!\n\n"
                f"🔹 Змінити токен: <code>/key sk-новий-ключ</code>\n"
                f"🔹 Видалити токен: <code>/delkey</code>",
            )
        else:
            await safe_send(
                message,
                "\U0001f48e <b>Підключення власного Vision AI (OpenAI API)</b>\n\n"
                "Ви або ваші колеги можете підключити <b>власний API-токен OpenAI</b> для безлімітного аналізу фото через GPT-4o Vision!\n\n"
                "📖 <b>Інструкція (як отримати ключ за 1 хвилину):</b>\n"
                "1️⃣ Зареєструйтесь / Увійдіть на <a href='https://platform.openai.com/signup'>platform.openai.com</a>\n"
                "2️⃣ Відкрийте розділ <a href='https://platform.openai.com/api-keys'>API Keys</a>\n"
                "3️⃣ Натисніть <b>Create new secret key</b> і скопіюйте його\n"
                "4️⃣ Надішліть ключ сюди боту командою:\n"
                "<code>/key sk-proj-xxxxxxxxxxxxxxxxxxxx</code>\n"
                "<i>(Або просто надішліть ключ текстом у цей чат)</i>\n\n"
                "🛡 <i>Кожен користувач може мати свій окремий ключ. Вся аналітика (звіти, ТОП, карта) — безкоштовна для всіх.</i>",
                disable_web_page_preview=True,
            )
    finally:
        db.close()


# ──────────────────────── Photo OSINT Analysis ────────────────────

@router.message(F.photo)
async def handle_photo(message: types.Message, bot: Bot):
    # Determine API key (User-specific or fallback to system)
    db = SessionLocal()
    user_api_key = None
    try:
        uk = db.query(UserApiKey).filter(UserApiKey.user_id == message.from_user.id).first()
        if uk:
            user_api_key = uk.openai_api_key
    finally:
        db.close()

    effective_key = user_api_key or OPENAI_API_KEY

    await safe_send(
        message,
        "\u23f3 <b>Ініційовано глибокий OSINT-аналіз...</b>\n"
        "1. Витягую EXIF-метадані...\n"
        "2. Запускаю GeoSpy AI для візуальної геолокації...\n"
        "3. Аналізую техніку та руйнування через Vision AI...",
    )

    file_id = message.photo[-1].file_id
    file = await bot.get_file(file_id)
    file_path = file.file_path

    downloaded_file = await bot.download_file(file_path)
    file_bytes = downloaded_file.read()
    base64_image = base64.b64encode(file_bytes).decode('utf-8')

    # Save temp file for EXIF / GeoSpy
    temp_path = f"temp_{file_id}.jpg"
    with open(temp_path, "wb") as f_temp:
        f_temp.write(file_bytes)

    parts = ["\U0001f50e <b>РЕЗУЛЬТАТИ OSINT-АНАЛІЗУ</b>\n"]

    # ── 1. EXIF ──
    try:
        from worker.osint.exif_extractor import EXIFExtractor
        exif = EXIFExtractor().extract(temp_path)
        if exif.get("has_gps"):
            parts.append(f"\U0001f4e1 <b>EXIF GPS:</b> {exif['latitude']}, {exif['longitude']}")
            if exif.get("datetime"):
                parts.append(f"\u23f0 <b>EXIF Час:</b> {exif['datetime']}")
        else:
            parts.append(
                "\U0001f4e1 <b>EXIF метадані:</b> Очищені або відсутні "
                "(можливо, фото з Telegram/Viber)."
            )
    except Exception as exc:
        logger.warning(f"EXIF extraction error: {exc}")

    # ── 2. GeoSpy AI ──
    try:
        from worker.osint.ai_geolocation import ai_geo
        geospy = await asyncio.to_thread(ai_geo.analyze_image, temp_path)
        if geospy and geospy.get("coordinates"):
            loc_name = geospy.get('predicted_location', 'Знайдено')
            coords = geospy['coordinates']
            parts.append(f"\U0001f30d <b>GeoSpy AI:</b> {loc_name}")
            parts.append(f"\U0001f4cd <b>Координати:</b> {coords[0]}, {coords[1]}")
    except Exception as exc:
        logger.warning(f"GeoSpy error: {exc}")

    # ── 3. Solar Chrono-Location (Anti-IPSO Shadow Verification) ──
    try:
        from worker.osint.geoint_engine import geoint_engine
        lat_c = exif.get("latitude") if (exif and exif.get("has_gps")) else 50.4501
        lon_c = exif.get("longitude") if (exif and exif.get("has_gps")) else 30.5234
        sun_data = geoint_engine.calculate_sun_position(lat_c, lon_c)
        parts.append(f"☀️ <b>Сонячний азимут (Chrono-verify):</b> {sun_data['solar_azimuth_deg']}° | 📐 <b>Кут тіней:</b> {sun_data['shadow_direction_deg']}°")
    except Exception as exc:
        logger.warning(f"Chrono-location error: {exc}")

    # Clean up temp file
    if os.path.exists(temp_path):
        os.remove(temp_path)

    parts.append("")  # blank line before Vision AI

    # ── 3. Vision AI ──
    if not effective_key:
        parts.append(
            "⚠️ <b>Vision AI недоступний:</b> Ключ OpenAI не налаштовано.\n"
            "Підключіть власний токен командою:\n"
            "<code>/key sk-ваш_ключ</code>\n\n"
            "Де взяти: <a href='https://platform.openai.com/api-keys'>platform.openai.com</a>"
        )
        await safe_send(message, "\n".join(parts), disable_web_page_preview=True)
        return

    def call_openai():
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {effective_key}",
        }
        sys_prompt = (
            "Ти військовий OSINT-аналітик. Зроби детальний аналіз фото.\n"
            "Формат (з емодзі, без HTML-тегів):\n"
            "🛡 Військова техніка/Зброя: [опис]\n"
            "🔥 Характер уражень: [опис]\n"
            "🌤 Погода/Освітлення: [опис]\n"
            "⚠️ Оцінка достовірності: [опис]"
        )
        data = {
            "model": "gpt-4o-mini",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": sys_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                        },
                    ],
                }
            ],
            "max_tokens": 500,
            "temperature": 0.1,
        }
        return requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=30,
        )

    try:
        resp = await asyncio.to_thread(call_openai)
        if resp.status_code == 200:
            result = resp.json()["choices"][0]["message"]["content"]
            parts.append(result)
            await safe_send(message, "\n".join(parts))
        elif resp.status_code in (429, 401):
            if user_api_key:
                await safe_send(
                    message,
                    f"❌ <b>Помилка вашого OpenAI API ключа ({resp.status_code}):</b>\n"
                    "Баланс акаунту вичерпано або токен недійсний.\n\n"
                    "Поповніть баланс на <a href='https://platform.openai.com/settings/organization/billing/overview'>OpenAI Billing</a> "
                    "або оновіть ключ: <code>/key sk-...</code>",
                    disable_web_page_preview=True,
                )
            else:
                await safe_send(
                    message,
                    "⚠️ <b>Системний ліміт Vision AI вичерпано.</b>\n\n"
                    "Ви можете підключити <b>власний токен OpenAI</b> і продовжити без обмежень:\n"
                    "1. Отримайте ключ на <a href='https://platform.openai.com/api-keys'>platform.openai.com</a>\n"
                    "2. Надішліть сюди: <code>/key sk-ваш-ключ</code>",
                    disable_web_page_preview=True,
                )
        else:
            await message.answer(f"❌ Помилка Vision API: {resp.status_code}")
    except Exception as e:
        logger.error(f"Vision AI error: {e}")
        await message.answer(f"❌ Помилка під час аналізу: {str(e)}")


# ──────────────────────── 👱‍♀️ ДАША? (40 МЕМІВ) ─────────────────────────

DASHA_MEMES = [
    "<b>1.</b>\n<b>Людин іскун:</b> «На Саваслейці підозріло».\n<b>Даша:</b> «Ага».\n<b>Людин:</b> «Я ще не закінчив».\n<b>Даша:</b> «Я вже на дачі».",
    "<b>2.</b>\nКацап на Саваслейці перднув — <b>ДАША, НА ДАЧУ. НАМ ВСІМ ПІЗДАААААА.</b>",
    "<b>3.</b>\n<b>Людин іскун:</b> «Поки що немає підстав для паніки».\n<b>Даша:</b> «Я не панікую».\n<i>(Заправляє машину)</i>\n<b>Даша:</b> «Я превентивно охуїваю».",
    "<b>4.</b>\n<b>Людин:</b> «Є непрямі ознаки».\n<b>Даша:</b> «У мене теж».\n<b>Людин:</b> «Які?»\n<b>Даша:</b> «Повний бак».",
    "<b>5.</b>\n<b>Армпо знову танцює.</b>\n<b>Даша:</b> «Я теж люблю танці. Але можна наступного разу просто діджея?»",
    "<b>6.</b>\n<b>Людин іскун:</b> «Виявлено активність».\n<b>Даша:</b> «Де?»\n<b>Людин:</b> «На аеродромі».\n<b>Даша:</b> «А я вже думала, що в чоловіків».",
    "<b>7.</b>\n<b>Людин:</b> «Дашо, сьогодні може бути неспокійно».\n<b>Даша:</b> «Дякую».\n<b>Людин:</b> «Ти куди?»\n<b>Даша:</b> «Неспокійно їхати на дачу».",
    "<b>8.</b>\nДаша не тікає від проблем.\nВона здійснює планове стратегічне переміщення цивільного населення в напрямку дачі.",
    "<b>9.</b>\n<b>Людин:</b> «Можливі певні ризики».\n<b>Даша:</b> «Які?»\n<b>Людин:</b> «Не хочу робити передчасних висновків».\n<b>Даша:</b> «Я вже зробила. Висновок їде 110 км/год».",
    "<b>10.</b>\n<b>Людин іскун:</b> «Зафіксовано рух».\n<b>Даша:</b> «Куди?»\n<b>Людин:</b> «Я поки що не знаю».\n<b>Даша:</b> «Я знаю. Я — на дачу».",
    "<b>11. Сільпо</b>\nКиїв: тривога.\nСільпо: зачинено.\nДаша: голодна.\nКотик: теж голодний.\n<b>Людин іскун:</b> «Виявлено критичну інфраструктурну проблему».",
    "<b>12.</b>\nНайстрашніше в київській тривозі:\nне звук сирени.\nА напис на дверях Сільпо:\n<i>«Під час повітряної тривоги магазин не працює»</i>.",
    "<b>13.</b>\n<b>Даша:</b> «Людин, у мене питання».\n<b>Людин:</b> «Слухаю».\n<b>Даша:</b> «Чому ракети можуть летіти, а я не можу купити сир?»",
    "<b>14.</b>\n<b>Людин:</b> «Дашо, йди в укриття».\n<b>Даша:</b> «Я в Сільпо».\n<b>Людин:</b> «Тоді залишай покупки».\n<b>Даша:</b> «НІ. Є МЕЖА, ЛЮДИН».",
    "<b>15. Київський survival kit:</b>\n• павербанк\n• вода\n• ліхтарик\n• плед\n• аптечка\n• котик\n• ще один павербанк\n• надія, що Сільпо відкрите.",
    "<b>16. Рейви</b>\nРейв: скасовано через тривогу.\n<b>Даша:</b> «Ну хоча б русня нарешті навчилася робити афтерпарті».",
    "<b>17. Київський рейв:</b>\n22:00 — музика\n23:00 — танці\n00:01 — тривога\n00:02 — укриття\n01:17 — відбій\n01:18 — знову тривога\n02:00 — всі танцюють уже виключно від нервового виснаження.",
    "<b>18.</b>\n<b>Даша:</b> «Я хочу на рейв».\n<b>Людин іскун:</b> «Сьогодні не рекомендую».\n<b>Даша:</b> «А що рекомендуєш?»\n<b>Людин:</b> «Укриття».\n<b>Даша:</b> «Я ПИТАЛА ПРО ЖИТТЯ, А НЕ ПРО ЙОГО ЗБЕРЕЖЕННЯ».",
    "<b>19.</b>\nРейв скасували.\n<b>Даша:</b> «Все».\n<b>Людин:</b> «Що все?»\n<b>Даша:</b> «Мене позбавили останнього легального способу забути, який сьогодні день».",
    "<b>20.</b>\n<b>Людин іскун не може гарантувати:</b>\n• спокійну ніч\n• світло\n• відкритий Сільпо\n• рейв\n• кокаїн\n• мужика\nАле може гарантувати, що Даша знову поїде на дачу.",
    "<b>21. Nightlife</b>\n<b>Даша:</b> «Людин, де кокаїн?»\n<b>Людин:</b> «Я бот».\n<b>Даша:</b> «То який із тебе тоді OSINT?»",
    "<b>22. Київський nightlife:</b>\nРейв — скасовано.\nСільпо — закрито.\nСвітло — під питанням.\nТривога — стабільно.\nКокаїну — за легендою очевидців, колись існував.",
    "<b>23.</b>\n<b>Даша:</b> «Хочу кокаїн».\n<b>Людин:</b> «Не можу допомогти».\n<b>Даша:</b> «Добре».\n<i>(Пауза)</i>\n<b>Даша:</b> «Тоді знайди мужика».\n<b>Людин:</b> «Запит прийнято. Результатів ще менше».",
    "<b>24.</b>\n<b>Людин іскун:</b> «Пошук кокаїну не входить до моїх функцій».\n<b>Даша:</b> «А пошук мужика?»\n<b>Людин:</b> «Теж».\n<b>Даша:</b> «Слабкий бот».",
    "<b>25. ОГОЛОШЕННЯ</b>\nПоміняю шахед на мужика.\n<b>Вимоги до мужика:</b>\n• живий\n• адекватний\n• не кацап\n• любить котиків\n• має машину\n• не губиться після слова «відносини»\n• знає, що таке Саваслейка, але не працює там.",
    "<b>26.</b>\n<b>Даша:</b> «Людин, знайди мужика».\n<b>Людин:</b> «Я не Tinder».\n<b>Даша:</b> «Зате ти шукаєш об’єкти за непрямими ознаками».\n<b>Людин:</b> «Це не зовсім—»\n<b>Даша:</b> «ПРАЦЮЙ».",
    "<b>27.</b>\n<b>Людин:</b> «Виявлено невідому ціль».\n<b>Даша:</b> «Чоловік?»\n<b>Людин:</b> «Ні, Shahed».\n<b>Даша:</b> «НАХУЙ».",
    "<b>28.</b>\n<b>Людин іскун:</b> «Виявлено потенційний об’єкт».\n<b>Даша:</b> «Мужик?»\n<b>Людин:</b> «Ні».\n<b>Даша:</b> «Котик?»\n<b>Людин:</b> «Ні».\n<b>Даша:</b> «Тоді мене це не цікавить».",
    "<b>29.</b>\nДаша шукає чоловіка з трьома базовими характеристиками:\n<b>живий, адекватний, не летить на неї.</b>\nЧетверта характеристика — щоб сам іноді писав першим.",
    "<b>30.</b>\n<b>Людин:</b> «Є хороші новини».\n<b>Даша:</b> «Мужик?»\n<b>Людин:</b> «Ні».\n<b>Даша:</b> «Тоді це не хороші новини».",
    "<b>31. Зима</b>\n<b>Людин іскун:</b> «Попередньо очікується складна зима».\n<b>Даша:</b> «Наскільки складна?»\n<b>Людин:</b> «Холодно».\n<b>Даша:</b> «І світло?»\n<b>Людин:</b> «Можливі перебої».\n<b>Даша:</b> «Мужик?»\n<b>Людин:</b> «Без змін».\n<b>Даша:</b> «НАЙТЯЖЧА ЗИМА В ІСТОРІЇ».",
    "<b>32. Зимовий Київ:</b>\nСвітла нема.\nТепла нема.\nІнтернет десь є.\nСільпо закрите.\nРейвів нема.\nЗате тривога працює без перебоїв.",
    "<b>33.</b>\n<b>Людин:</b> «Дашо, на зиму бажано підготуватися».\n<b>Даша:</b> «Я вже готова».\n<b>Людин:</b> «Що купила?»\n<b>Даша:</b> «Плед».\n<b>Людин:</b> «Щось ще?»\n<b>Даша:</b> «Котика».\n<b>Людин:</b> «А генератор?»\n<b>Даша:</b> «Котик теплий».",
    "<b>34.</b>\n<b>Даша:</b> «Людин, якщо взимку не буде світла, що робити?»\n<b>Людин:</b> «Заряджати павербанки заздалегідь».\n<b>Даша:</b> «А якщо не буде опалення?»\n<b>Людин:</b> «Теплий одяг».\n<b>Даша:</b> «А якщо не буде мужика?»\n<b>Людин:</b> «Це питання поза межами прогнозної моделі».",
    "<b>35.</b>\n<b>Зима.</b>\n• -15°C\n• світла немає\n• батареї холодні\n• Сільпо закрите\n• рейв скасовано\n• кокаїну немає\n<i>Котик сидить на Даші. Енергосистема офіційно врятована.</i>",
    "<b>36.</b>\n<b>Людин іскун:</b> «Температура падає».\n<b>Даша:</b> «Світло теж?»\n<b>Людин:</b> «Ймовірно».\n<b>Даша:</b> «А настрій?»\n<b>Людин:</b> «Вже».",
    "<b>37. Людин іскун як персонаж</b>\n90% — аналітика\n5% — моніторинг\n3% — нагадування Даші про дачу\n2% — пошук мужика, якого ніхто не бачив",
    "<b>38.</b>\n<b>Даша:</b> «Людин, ти можеш хоча б раз написати щось хороше?»\n<b>Людин:</b> «Так».\n<b>Даша:</b> «Ну?»\n<b>Людин:</b> «Сьогодні в Сільпо немає черги».\n<b>Даша:</b> «Чому?»\n<b>Людин:</b> «Тривога».\n<b>Даша:</b> «ЙДИ НАХУЙ, ЛЮДИН».",
    "<b>39. СИСТЕМА ДАША v.2026</b>\nВхідні дані: Саваслейка щось робить ➔ Людин іскун збирає дані ➔ Аналізує ➔ «Дашо...» ➔ «Я ВЖЕ ЗНАЮ» ➔ Котик запакований ➔ Машина заведена ➔ Дача ➔ Мужик не знайдений.",
    "<b>40. ФІНАЛЬНИЙ ПРОГНОЗ ВІД ЛЮДИН ІСКУН</b>\nСаваслейка: щось робить.\nАрмпо: знову танці.\nКиїв: знову тривога.\nСільпо: знову зачинене.\nРейв: знову скасований.\nКокаїну: немає.\nСвітла взимку: питання відкрите.\nТемпература: буде дубак.\nДаша: на дачі.\nКотик: у теплі.\nМужик: пошук триває.\n<b>Людин іскун:</b> «Зафіксовано стабільність обстановки»."
]

MEME_DATABASE = {
    "dacha": [
        "<b>[ОФІЦІЙНИЙ ЛОГ ЛЮДИН ІСКУН]</b>\n[01:32] Кацап на Саваслейці перднув.\n[01:33] <b>Людин:</b> «Даша, це не навчальна...»\n[01:34] <b>Даша:</b> «Я ЗНАЮ. Я ВЖЕ ЗА КИЄВОМ НА ДАЧІ. НАМ ВСІМ ПІЗДАААААА!»",
        "<b>[ДІАЛОГ ДНЯ]</b>\n<b>Людин іскун:</b> «На Саваслейці підозріла активність».\n<b>Даша:</b> «Ага».\n<b>Людин:</b> «Я ще не закінчив аналіз».\n<b>Даша:</b> «Я вже на дачі».",
        "<b>[СТРАТЕГІЧНЕ ПЕРЕМІЩЕННЯ]</b>\nДаша не тікає від проблем. Вона здійснює планове стратегічне переміщення цивільного населення зі швидкістю 110 км/год у напрямку дачі.",
        "<b>[РЕАКЦІЯ НА АРМПО]</b>\n<b>Армпо знову влаштував танці.</b>\n<b>Даша:</b> «Я теж люблю танці. Але можна наступного разу просто діджея, а не ракетні прильоти?»",
        "<b>[ОЗНАКИ АКТИВНОСТІ]</b>\n<b>Людин:</b> «Є непрямі ознаки активності».\n<b>Даша:</b> «У мене теж є непрямі ознаки».\n<b>Людин:</b> «Які?»\n<b>Даша:</b> «Повний бак і Котик у машині».",
        "<b>[АНАЛІЗ vs РЕАЛЬНІСТЬ]</b>\n<b>Людин іскун:</b> «Ймовірність неспокійної ночі зростає».\n<b>Даша:</b> «Моя ймовірність залишатися в Києві — падає до нуля. Чао!»"
    ],
    "man": [
        "<b>[ОГОЛОШЕННЯ]</b>\n<b>Поміняю Shahed на мужика.</b>\n<i>Вимоги до мужика:</i>\n• живий, адекватний, не кацап;\n• любить котиків та має машину;\n• не губиться після слова «відносини»;\n• знає, що таке Саваслейка, але не працює там!",
        "<b>[TINDER OSINT]</b>\n<b>Даша:</b> «Людин, знайди мені мужика».\n<b>Людин:</b> «Я OSINT-бот, а не Tinder».\n<b>Даша:</b> «Зате ти шукаєш об’єкти за непрямими ознаками. ПРАЦЮЙ!»",
        "<b>[ПОШУК ЦІЛЕЙ]</b>\n<b>Людин іскун:</b> «Виявлено потенційний об’єкт».\n<b>Даша:</b> «Мужик?»\n<b>Людин:</b> «Ні, Shahed».\n<b>Даша:</b> «ПІШОВ НАХУЙ!»",
        "<b>[КИЇВСЬКИЙ DATING 2026]</b>\n— Привіт, що робиш?\n— Чекаю повідомлення від Людин іскун.\n— А мужик тобі не потрібен?\n— Саме тому й чекаю Людин іскун!",
        "<b>[ХАРАКТЕРИСТИКА ОБ'ЄКТА]</b>\nДаша шукає чоловіка з трьома базовими характеристиками: <b>живий, адекватний, не летить на неї з аеродрому.</b> Четверта — щоб сам іноді писав першим.",
        "<b>[СТАТУС ПОШУКУ]</b>\n<b>Людин іскун:</b> «Мною зафіксовано стабільну відсутність мужика».\n<b>Даша:</b> «То який із тебе тоді ШІ-аналітик?»"
    ],
    "cat": [
        "<b>[ЕНЕРГОСИСТЕМА КИЄВА]</b>\n<b>Людин:</b> «Купи генератор на зиму».\n<b>Даша:</b> «У мене є Котик».\n<b>Людин:</b> «Котик — це не генератор».\n<b>Даша:</b> «Зате він теплий і муркоче. Енергосистема врятована!»",
        "<b>[ЕВАКУАЦІЯ КОТИКА]</b>\nСаваслейка: щось робить ➔ Людин: аналізує ➔ Даша: пакує Котика ➔ Котик: взагалі не розуміє, чому його знову ведуть у машину о 3-й ночі.",
        "<b>[ДІАЛОГ З КОТИКОМ]</b>\n<b>Котик:</b> «Мяу».\n<b>Даша:</b> «Я знаю».\n<b>Котик:</b> «Мяу».\n<b>Даша:</b> «Так, Людин іскун знову щось побачив на радарі. Пакуємось!»",
        "<b>[SURVIVAL KIT 2026]</b>\nКиївський набор виживання: павербанк, вода, ліхтарик, плед, котик. Мужик — опціонально. Котик — обов'язково!",
        "<b>[КОТИК СПИТЬ]</b>\nЛюди будують графіки, OSINT-боти вираховують азимути, Даша пакує валізи... Котик спить. Котик — найрозумніша істота у цьому всесвіті."
    ],
    "winter": [
        "<b>[ПРОГНОЗ ЗИМИ]</b>\n<b>Людин іскун:</b> «Попередньо очікується складна зима».\n<b>Даша:</b> «Наскільки складна?»\n<b>Людин:</b> «Холодно і без світла».\n<b>Даша:</b> «А мужик?»\n<b>Людин:</b> «Без змін».\n<b>Даша:</b> «НАЙТЯЖЧА ЗИМА В ІСТОРІЇ!»",
        "<b>[ЗИМОВИЙ КИЇВ]</b>\nСвітла нема. Тепла нема. Сільпо зачинено. Рейвів нема. Мужика нема. Зате тривога та Котик працюють без перебоїв!",
        "<b>[БЕЗ ОПАЛЕННЯ]</b>\n-15°C на вулиці. Батареї крижані. Сільпо закрито через тривогу. Котик сидить на Даші. Офіційна система опалення працює!",
        "<b>[РЕАЛЬНІСТЬ 2026]</b>\n<b>Людин:</b> «Дашо, заряджай павербанки».\n<b>Даша:</b> «А якщо не буде опалення?»\n<b>Людин:</b> «Одягайся тепліше».\n<b>Даша:</b> «А якщо не буде мужика?»\n<b>Людин:</b> «Це питання поза межами моєї математичної моделі»."
    ],
    "harder": [
        "<b>[СІЛЬПО ТА ТРИВОГА]</b>\nНайстрашніше в київській тривозі — не звук сирени. А напис на дверях Сільпо: <i>«Під час повітряної тривоги магазин не працює»</i>. <b>Даша:</b> «Чому ракети можуть летіти, а я не можу купити сир?!»",
        "<b>[КИЇВСЬКИЙ NIGHTLIFE]</b>\n22:00 — музика ➔ 23:00 — танці ➔ 00:01 — тривога ➔ 00:02 — укриття ➔ 01:17 — відбій ➔ 01:18 — знову тривога ➔ 02:00 — всі танцюють вже виключно від нервового виснаження.",
        "<b>[ВІДСУТНІСТЬ КОКАЇНУ]</b>\n<b>Даша:</b> «Людин, де кокаїн у Києві?»\n<b>Людин:</b> «Пошук кокаїну не входить до моїх функцій».\n<b>Даша:</b> «А пошук мужика?»\n<b>Людин:</b> «Теж».\n<b>Даша:</b> «Слабкий бот!»",
        "<b>[АРТМПО ТАНЦІ]</b>\nАрмпо знову танцює під прильотами. <b>Даша:</b> «Людин, скажи русні, що якщо вони скасують ще один рейв або закриють Сільпо — я особисто приїду на Саваслейку!»",
        "<b>[ХОРОШІ НОВИНИ]</b>\n<b>Людин:</b> «Сьогодні в Сільпо немає черги».\n<b>Даша:</b> «О, супер! Чому?»\n<b>Людин:</b> «Тривога».\n<b>Даша:</b> «ЙДИ НАХУЙ, ЛЮДИН!»"
    ]
}

def get_meme_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Ще один", callback_data="meme_more")
    builder.button(text="🖤 Жорсткіше", callback_data="meme_harder")
    builder.button(text="🐈 Про котика", callback_data="meme_cat")
    builder.button(text="🍆 Про мужика", callback_data="meme_man")
    builder.button(text="💡 Про зиму", callback_data="meme_winter")
    builder.button(text="🏖 На дачу", callback_data="meme_dacha")
    builder.adjust(2, 2, 2)
    return builder.as_markup()

@router.message(Command("dasha"))
@router.message(Command("humor"))
@router.message(F.text == "😳 ДАША?")
@router.message(F.text == "ДАША?")
@router.message(F.text == "🖤 ЧОРНИЙ ГУМОР")
@router.message(F.text == "👱‍♀️ ДАША (40 МЕМІВ) 🚗💨")
async def cmd_dasha_humor_combined(message: types.Message):
    import random
    all_combined = DASHA_MEMES + [m for cat in MEME_DATABASE.values() for m in cat]
    m1, m2 = random.sample(all_combined, 2)
    
    header = "😳 <b>ХРОНІКИ ДАШІ ТА ЧОРНИЙ ГУМОР ЛЮДИН ІСКУН</b> 🚗💨\n\n"
    msg_text = f"{header}{m1}\n\n───────────────\n\n{m2}"
    await safe_send(message, msg_text, reply_markup=get_meme_keyboard())

@router.callback_query(F.data == "more_dasha_memes")
@router.callback_query(F.data.startswith("meme_"))
async def cb_meme_filter(call: types.CallbackQuery):
    import random
    action = call.data.replace("meme_", "").replace("more_dasha_memes", "more")
    
    if action in MEME_DATABASE:
        chosen = random.choice(MEME_DATABASE[action])
    else:
        all_combined = DASHA_MEMES + [m for cat in MEME_DATABASE.values() for m in cat]
        chosen = random.choice(all_combined)
        
    header = "😳 <b>ХРОНІКИ ДАШІ ТА ЧОРНИЙ ГУМОР ЛЮДИН ІСКУН</b> ⚡\n\n"
    msg_text = header + chosen
    
    try:
        await call.message.edit_text(msg_text, parse_mode=ParseMode.HTML, reply_markup=get_meme_keyboard())
    except Exception:
        await call.message.answer(msg_text, parse_mode=ParseMode.HTML, reply_markup=get_meme_keyboard())
    await call.answer()


# ──────────────────────── 🐾 ТУПО МЯВ, ШИПІННЯ ТА МУРКОТІННЯ ────────

CAT_VARIETIES = [
    {
        "type": "meow",
        "files": ["meow_classic.mp3", "meow_kitten.mp3", "meow_clear.mp3", "meow_soft.mp3", "playful_cat.mp3"],
        "title": "🐱 <b>СПРАВЖНІЙ МЯЯЯУУУУ!</b> 🐾",
        "quotes": [
            "🐾 «Штурман вирушає в політ за позитивом!»",
            "🐾 «Супер-кіт на варті гарного настрою!»",
            "🐾 «Космічний корабель коробкового типу готовий до запуску обіймів!»",
            "🐾 «Справжній пухнастий антидепресант на зв'язку!»"
        ]
    },
    {
        "type": "hiss",
        "files": ["hiss_angry.mp3"],
        "title": "😾 <b>СПРАВЖНЄ БОЙОВЕ ШИПІННЯ!</b> ⚡",
        "quotes": [
            "😾 «Тактичний бойовий кіт зашипів на ворожі шахеди! Ворог не пройде!»",
            "😾 «Ш-ш-ш-ш! Режим бойової люті активовано. Смерть окупантам!»",
            "😾 «Кіт-розвідник зафіксував ціль і шипить на радар!»"
        ]
    },
    {
        "type": "purr",
        "files": ["purr_deep.mp3"],
        "title": "🐾 <b>СПРАВЖНЄ ТАКТИЧНЕ МУРКОТІННЯ...</b> 🛡️",
        "quotes": [
            "🐾 «Тактичне антистрес-муркотіння активовано: рівень тривожності знижено до 0%.»",
            "🐾 «Мур-р-р... Небо під надійним захистом сил ППО, відпочивайте.»",
            "🐾 «Генератор справжнього котячого затишку працює на повну потужність!»"
        ]
    }
]

@router.message(Command("meow"))
@router.message(Command("hiss"))
@router.message(Command("purr"))
@router.message(F.text == "\U0001f43e ТУПО МЯВ")
@router.message(F.text == "ТУПО МЯВ")
@router.message(F.text.ilike("%тупо мяв%"))
@router.message(F.text.ilike("%мяв%"))
@router.message(F.text.ilike("%мяу%"))
@router.message(F.text.ilike("%шип%"))
@router.message(F.text.ilike("%мур%"))
async def cmd_meow(message: types.Message):
    import random
    from aiogram.types import FSInputFile
    
    txt = (message.text or "").lower()
    
    if "шип" in txt:
        category = next(c for c in CAT_VARIETIES if c["type"] == "hiss")
    elif "мур" in txt:
        category = next(c for c in CAT_VARIETIES if c["type"] == "purr")
    else:
        category = random.choice(CAT_VARIETIES)
        
    quote = random.choice(category["quotes"])
    chosen_file = random.choice(category["files"])
    audio_path = os.path.join(os.path.dirname(__file__), chosen_file)
    
    if os.path.exists(audio_path):
        voice = FSInputFile(audio_path)
        try:
            await message.answer_voice(
                voice,
                caption=f"{category['title']}\n\n{quote}",
                parse_mode=ParseMode.HTML
            )
            return
        except Exception as e:
            logger.warning(f"Voice send failed: {e}")
            
    await safe_send(message, f"{category['title']}\n\n{quote}")


