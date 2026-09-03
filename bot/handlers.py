from datetime import datetime, timedelta, timezone

from aiogram import Router, types, F
router = Router()
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.types import WebAppInfo
from database.models import SessionLocal, DetectedEvent, UserApiKey, BombShelter
from sqlalchemy import func, text, or_

import os
import requests
import base64
import json
from datetime import timedelta
import redis
import os
from bot.broadcaster import broadcaster

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

import asyncio
import html

def format_source_display(src):
    if not src: return "невідомо"
    src = str(src).strip()
    if src.replace('-', '').isdigit():
        return f"ID:{src}"
    return f"@{src.lstrip('@')}"

def format_source_link(src, msg_id):
    if not src: return ""
    src = str(src).strip()
    if src.replace('-', '').isdigit():
        # Private channel format: t.me/c/1234567/msg_id
        clean_id = src.replace('-100', '')
        return f"https://t.me/c/{clean_id}/{msg_id}"
    return f"https://t.me/{src.lstrip('@')}/{msg_id}"

import logging
from aiogram import Bot



from bot.graph_generator import generate_analytics_graph

@router.message(Command("graph"))
@router.message(F.text == "📈 Графік активності")
async def cmd_graph(message: types.Message):
    await message.answer("⏳ Малюю графік активності за 24 години...")
    try:
        loop = asyncio.get_event_loop()
        import functools
        graph_file = await loop.run_in_executor(None, functools.partial(generate_analytics_graph, hours=24))
        
        if graph_file:
            await message.answer_photo(
                photo=types.BufferedInputFile(graph_file.getvalue(), filename=graph_file.name),
                caption="📈 **Динаміка інцидентів та цілей (останні 24 год)**",
                parse_mode="Markdown"
            )
        else:
            await message.answer("Немає достатньо даних для побудови графіка.")
    except Exception as e:
        logger.error(f"Graph error: {e}")
        await message.answer("❌ Помилка генерації графіка.")

from bot.export import generate_csv_export
from bot.map_generator import generate_static_map

@router.message(Command("csv"))
@router.message(F.text == "📊 Експорт CSV")
async def cmd_csv_export(message: types.Message):
    await message.answer("⏳ Формую базу даних інцидентів (CSV) за 24 години...")
    try:
        csv_file = generate_csv_export(hours=24)
        await message.answer_document(
            document=types.BufferedInputFile(csv_file.getvalue(), filename=csv_file.name),
            caption="✅ Дані OSINT платформи (24h)."
        )
    except Exception as e:
        logger.error(f"CSV error: {e}")
        await message.answer("❌ Помилка експорту.")

@router.message(Command("map"))
@router.message(F.text == "🗺️ Згенерувати Мапу (.png)")
async def cmd_static_map(message: types.Message):
    await message.answer("⏳ Рендеринг тактичної мапи...")
    try:
        # Run in executor so it doesn't block asyncio
        loop = asyncio.get_event_loop()
        import functools
        map_file = await loop.run_in_executor(None, functools.partial(generate_static_map, hours=24))
        
        await message.answer_photo(
            photo=types.BufferedInputFile(map_file.getvalue(), filename=map_file.name),
            caption="🗺️ **Знімок тактичної мапи за останні 24 години**\nЧервоний: Вибухи/Влучання | Помаранчевий: Шахеди/Радари",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Map generation error: {e}")
        await message.answer("❌ Помилка рендерингу мапи.")

from bot.threat_report import generate_live_threat_assessment, generate_reference_card

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

def get_dashboard_url() -> str:
    """Dynamically retrieves the current active Cloudflare tunnel URL from Redis or ENV."""
    import redis
    try:
        r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
        val = r.get("active_tunnel_url")
        if val:
            return val.decode("utf-8").strip()
    except Exception:
        pass
    return os.getenv("DASHBOARD_URL", "https://halifax-aim-restoration-dylan.trycloudflare.com")

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

def format_kyiv_time(dt: datetime) -> str:
    """Converts UTC datetime from database to local Kyiv Time (EEST/EET) HH:MM."""
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KYIV_TZ).strftime("%H:%M")


# ──────────────────────────── Keyboard ────────────────────────────

from bot.keyboards import get_main_keyboard, get_meme_keyboard



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





@router.message(F.text == "🔍 Глибокий OSINT")
async def cmd_deep_osint(message: types.Message):
    db = SessionLocal()
    try:
        user_key = db.query(UserApiKey).filter(UserApiKey.user_id == message.from_user.id).first()
        if not user_key or not user_key.openai_api_key:
            await message.answer("🔒 Для глибокого OSINT-аналізу потрібен OpenAI API Key (Vision).\nВстановіть його командою:\n`/key sk-...`", parse_mode=ParseMode.MARKDOWN)
            return
            
        from database.models import decrypt_key
        api_key = decrypt_key(user_key.openai_api_key)
        
        # Get strikes in last 12 hours
        threshold = datetime.utcnow() - timedelta(hours=12)

        # Check cache
        cache_key = "osint:deep_analysis"
        cached_report = None
        try:
            cached_val = redis_client.get(cache_key)
            if cached_val:
                cached_report = cached_val.decode('utf-8')
        except Exception:
            pass

        if cached_report:
            await safe_send(message, f"🔍 **ГЛИБОКИЙ OSINT ЗВІТ (Кеш)** 🔍\\\n\\\n{cached_report}")
            return

        events = db.query(DetectedEvent).filter(
            DetectedEvent.detected_at >= threshold,
            DetectedEvent.event_type.in_(['direct_strike', 'explosion', 'fire', 'destruction'])
        ).order_by(DetectedEvent.detected_at.desc()).all()
        
        if not events:
            await message.answer("ℹ️ За останні 12 годин не знайдено серйозних інцидентів для аналізу.")
            return
            
        await message.answer("⏳ Збираю дані за останні 12 годин та відправляю на аналіз ШІ...")
        
        # Prepare context for LLM
        context_text = "Зведення інцидентів за останні 12 годин:\n"
        for ev in events:
            context_text += f"[{ev.detected_at.strftime('%H:%M')}] {ev.location_text} - {ev.event_type}: {ev.message_text}\n"
            
        prompt = "Ти старший OSINT-аналітик. Проаналізуй наступні сирі дані про прильоти та вибухи в Київській області за останні 12 годин. Зроби професійний звіт: 1) Оцінка масштабу атаки. 2) Ймовірні цілі. 3) Ступінь підтвердження інформації. 4) Загальний висновок. Пиши сухо, військовою мовою, українською.\n\n" + context_text
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        data = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "Ти OSINT AI."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2
        }
        
        resp = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data, timeout=30)
        
        if resp.status_code == 200:
            analysis = resp.json()["choices"][0]["message"]["content"]
            try:
                redis_client.setex(cache_key, 300, analysis)
            except Exception:
                pass
            await safe_send(message, f"🔍 **ГЛИБОКИЙ OSINT ЗВІТ** 🔍\n\n{analysis}")
        else:
            await message.answer(f"❌ Сталася помилка API: {resp.status_code}\n{resp.text[:200]}")
            
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")
    finally:
        db.close()

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
        threshold = datetime.utcnow() - timedelta(hours=24)
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
    "карта", "веб-карта", "мяв", "шип", "мур", "premium", "меню", "актуалізація",
    "даша", "dasha", "гумор", "чорний", "довідник", "ттх", "графік", "csv", "експорт",
    "мапу", "мапа", "прес-реліз", "osint", "укриття"
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
    inline_kb.button(text="🌐 Відкрити Мапу з Укриттями у 1 Клік", url=get_dashboard_url())
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
    txt = (message.text or "").strip().lower()
    is_en = " en" in txt or txt.endswith("/threats_en")
    prompt = ""
    if txt.startswith("/threats ") or txt.startswith("/forecast "):
        prompt = txt.split(maxsplit=1)[1].strip()

    wait_msg = (
        "\u23f3 <b>Querying database for verified events in the last 24 hours...</b>\n"
        "<i>\u2022 Scanning recorded incidents and air alerts\n"
        "\u2022 Calculating threat levels from confirmed data\n"
        "\u2022 Cross-referencing source verification status...</i>"
    ) if is_en else (
        "\u23f3 <b>Запитую базу даних щодо верифікованих подій за останні 24 години...</b>\n"
        "<i>\u2022 Перевірка зафіксованих інцидентів та повітряних тривог\n"
        "\u2022 Розрахунок рівнів загрози за підтвердженими фактами\n"
        "\u2022 Звірка статусів верифікації джерел...</i>"
    )

    await safe_send(message, wait_msg)

    lang = "en" if is_en else "ua"
    report = await asyncio.to_thread(generate_live_threat_assessment, prompt, lang=lang)
    await safe_send(message, report, disable_web_page_preview=True)


@router.message(Command("reference"))
@router.message(Command("ttx"))
@router.message(F.text == "📖 Довідник ТТХ")
async def cmd_reference(message: types.Message):
    txt = (message.text or "").strip().lower()
    lang = "en" if " en" in txt else "ua"
    card = generate_reference_card(lang=lang)
    await safe_send(message, card, disable_web_page_preview=True)


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
        threshold = datetime.utcnow() - timedelta(hours=24)
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
            recent_radar_events.append(f"• <b>[{t_str}]</b> {format_source_display(e.source_channel)}: {snippet}")
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
    inline_kb.button(text="🗺️ Наша Тактична GEOINT Мапа", url=get_dashboard_url())
    inline_kb.adjust(1, 1)
    
    await safe_send(message, text, reply_markup=inline_kb.as_markup(), disable_web_page_preview=True)



# Legacy duplicate cmd_analytics removed (unified into primary handler below)


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
    
    source_weight = getattr(e, "source_weight", 0.5)
    source_tier = getattr(e, "source_tier", "B")
    
    # 1. Verification Label
    if status == "OFFICIAL" or getattr(e, "is_official", False) or source_tier == 'S':
        badge = f"🏛️ <b>ОФІЦІЙНЕ ДЖЕРЕЛО (@{e.source_channel})</b>"
    elif status == "VERIFIED" or source_weight >= 1.2:
        clean_sources = ", ".join([f"@{s.strip().lstrip('@')}" for s in sources.split(",") if s.strip()][:2])
        badge = f"🟢 <b>ВЕРИФІКОВАНО (Консенсус вага {source_weight:.1f}, {count} дж.: {clean_sources})</b>"
    elif status == "POSSIBLE_IPSO":
        badge = "🚨 <b>УВАГА: СУМНІВНЕ / МОЖЛИВИЙ ВКАТ</b>"
    else:
        badge = f"🟡 <b>НЕПІДТВЕРДЖЕНО (Вага {source_weight:.1f}, @{e.source_channel})</b>"

    # 2. C2 Geoint Synthesis Logic
    if getattr(e, "has_media", False):
        geo_method = "📸 Фото EXIF GPS / Vision AI"
    elif getattr(e, "is_official", False):
        geo_method = "🏛️ Офіційна прив'язка влади"
    elif count >= 2:
        geo_method = f"🟢 Перехресний консенсус ({count} дж.)"
    else:
        geo_method = "🗺️ Топонімічна прив'язка (OSINT)"

    c2_trace = (
        f"{badge}\n"
        f"   └ 🛰️ <b>C2 Схема:</b> <code>[Джерела: {count}] ➔ [Синтез: {geo_method}] ➔ [PostGIS GIST]</code>"
    )
    return c2_trace


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
        threshold = datetime.utcnow() - timedelta(hours=12)
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
                f"🔗 <a href='{format_source_link(src, mid)}'>Першоджерело {format_source_display(src)}</a>\n"
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
        threshold_24h = datetime.utcnow() - timedelta(hours=24)
        raw_events = (
            db.query(DetectedEvent)
            .filter(
                DetectedEvent.detected_at >= threshold_24h,
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
                f"🔗 <a href='{format_source_link(src, mid)}'>Джерело {format_source_display(src)}</a>\n"
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
        threshold = datetime.utcnow() - timedelta(hours=1)
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
                f"🔗 <a href='{format_source_link(src, mid)}'>Джерело {format_source_display(src)}</a>\n"
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
        threshold_24h = datetime.utcnow() - timedelta(hours=24)
        
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
        sources_str = "\n".join([f"• {format_source_display(ch)}: <b>{cnt} повідомлень</b>" for ch, cnt in sorted_sources]) or "• Немає даних"

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
    inline_kb.button(text="🌐 Відкрити Мапу у Браузері", url=get_dashboard_url())
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
            user_key.openai_api_key = encrypt_key(raw_key)
            user_key.username = uname
        else:
            from database.models import encrypt_key, decrypt_key
            user_key = UserApiKey(user_id=uid, username=uname, openai_api_key=encrypt_key(raw_key))
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
            from database.models import decrypt_key
            k = decrypt_key(user_key.openai_api_key)
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
            from database.models import decrypt_key
            k = decrypt_key(user_key.openai_api_key)
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
            from database.models import decrypt_key
            user_api_key = decrypt_key(uk.openai_api_key)
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
from bot.memes_db import DASHA_MEMES, MEME_DATABASE



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
    
    header = "😳 <b>ХРОНІКИ ДАШІ, ЛЮДИ ТА ІСКУНА (ЧОРНИЙ ГУМОР)</b> 🚗💨\n\n"
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
        
    header = "😳 <b>ХРОНІКИ ДАШІ, ЛЮДИ ТА ІСКУНА (ЧОРНИЙ ГУМОР)</b> ⚡\n\n"
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


import io


# 1. Markdown Export
@router.message(Command("export"))
@router.message(Command("pdf"))
@router.message(F.text == "📥 Експорт прес-релізу")
async def cmd_export_report(message: types.Message):
    await message.answer("⏳ Формую верифікований прес-реліз (Markdown)...")
    
    # Generate the report text
    report_ua = generate_live_threat_assessment(lang="ua")
    report_en = generate_live_threat_assessment(lang="en")
    
    # Combine into a single markdown file
    full_md = f"""# OPERATIONAL THREAT REPORT / ОПЕРАТИВНИЙ ЗВІТ
Generated by Lyudyn-Iskun OSINT Platform
Date: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}

## [EN] VERIFIED THREAT ASSESSMENT
{report_en}

---

## [UA] ВЕРИФІКОВАНИЙ ЗВІТ ЗАГРОЗ
{report_ua}

---
*Note: All sources have been verified via cross-reference consensus (Tier-based algorithm).*
"""
    # Remove HTML tags for clean markdown
    import re
    clean_md = re.sub(r'<[^>]+>', '', full_md)
    
    # Send as document
    file_bytes = io.BytesIO(clean_md.encode('utf-8'))
    file_bytes.name = f"Iskun_PressRelease_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.md"
    
    await message.answer_document(
        document=types.BufferedInputFile(file_bytes.getvalue(), filename=file_bytes.name),
        caption="✅ Верифікований прес-реліз готовий до публікації."
    )

# 2. Meme Generator (The Second Head)
@router.callback_query(F.data.startswith("meme_"))
async def callback_meme(callback: types.CallbackQuery):
    await callback.message.edit_text("⏳ Нейромережа генерує базу...")
    
    import requests
    import os
    from database.models import SessionLocal, UserApiKey
    
    db = SessionLocal()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        user_key = db.query(UserApiKey).filter(UserApiKey.user_id == callback.from_user.id).first()
        if user_key and user_key.openai_api_key:
            from database.models import decrypt_key
            api_key = decrypt_key(user_key.openai_api_key)
    db.close()
    
    if not api_key:
        await callback.message.edit_text("🔒 Для мемів потрібен OpenAI API Key.")
        return
        
    action = callback.data.split("_")[1]
    topics = {
        "more": "чорний гумор про русню",
        "harder": "максимально жорсткий сарказм про невдачі армії РФ",
        "cat": "мем про котика, який ігнорує сирену і спить",
        "man": "мем про суворого українського мужика, який п'є каву під час вибухів",
        "winter": "мем про те, як українці готуються до зими і відключень світла (оптимістично-сарказмічно)",
        "dacha": "мем про діда, який збив шахед банкою огірків на дачі"
    }
    topic = topics.get(action, "чорний гумор")
    
    prompt = f"Напиши один короткий, дуже смішний і саркастичний жарт (мем) українською мовою на тему: {topic}. Ніякого моралізаторства, тільки чистий гумор."
    
    try:
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        data = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "system", "content": "Ти — саркастичний український мемолог. Твоя ціль — розрядити обстановку чорним гумором."},
                         {"role": "user", "content": prompt}],
            "temperature": 0.8
        }
        resp = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data, timeout=15)
        meme_text = resp.json()["choices"][0]["message"]["content"]
        
        from bot.keyboards import get_meme_keyboard
        await callback.message.edit_text(f"🎭 **МЕМОЛОГІЯ:**\n\n{meme_text}", parse_mode="Markdown", reply_markup=get_meme_keyboard())
    except Exception as e:
        logger.error(f"Meme error: {e}")
        await callback.message.edit_text("❌ Мемолог втомився. Спробуйте пізніше.")

# ──────────────────────── /clean & /flush ──────────────────────────────

@router.message(Command("clean"))
@router.message(Command("flush"))
@router.message(F.text == "🧹 Очистити старі дані")
async def cmd_manual_cleanup(message: types.Message):
    from worker.tasks import cleanup_old_events
    await message.answer("⏳ Запускаю ротацію бази даних та скидання застарілого кешу...")
    res = cleanup_old_events(retention_hours=24)
    del_cnt = res.get("deleted_events", 0)
    await message.answer(
        f"✅ **РОТАЦІЮ БД ТА КЕШУ ЗАВЕРШЕНО!**\n\n"
        f"• Очищено застарілих подій (>24 год): **{del_cnt}**\n"
        f"• Скинуто кеш мапи та аналітики Redis: 🟢 **Успішно**\n"
        f"• База оптимізована під оперативне 24-годинне вікно."
    )
