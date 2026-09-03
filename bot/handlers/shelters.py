import asyncio
import html
import json
import threading
import time
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from sqlalchemy import text

from bot.keyboards import get_main_keyboard
from bot.handlers.utils import safe_send, get_dashboard_url, redis_client, logger
from database.models import SessionLocal

router = Router()

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

_nominatim_lock = threading.Lock()
_nominatim_last_call = 0.0
_NOMINATIM_MIN_INTERVAL = 1.0


def geocode_kyiv_street(query_text: str):
    """Universal OpenStreetMap geocoder for any street or district in Kyiv."""
    import urllib.request
    import urllib.parse
    clean_q = query_text.strip()
    cache_key = f"geo:{clean_q.lower()}"

    try:
        cached = redis_client.get(cache_key)
        if cached:
            lat, lon, display_name = json.loads(cached)
            return lat, lon, display_name
    except Exception as e:
        logger.warning(f"Geocode cache read error: {e}")

    headers = {"User-Agent": "LyudynIskunBot2/1.0 (contact@iskun.ua)"}

    for q_variant in [f"{clean_q}, Київ", f"вулиця {clean_q}, Київ", f"мікрорайон {clean_q}, Київ"]:
        url = "https://nominatim.openstreetmap.org/search?format=json&q=" + urllib.parse.quote(q_variant)
        try:
            with _nominatim_lock:
                global _nominatim_last_call
                wait = _NOMINATIM_MIN_INTERVAL - (time.monotonic() - _nominatim_last_call)
                if wait > 0:
                    time.sleep(wait)
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=4) as resp:
                    data = json.loads(resp.read().decode())
                _nominatim_last_call = time.monotonic()
            if data:
                lat = float(data[0]["lat"])
                lon = float(data[0]["lon"])
                display_name = data[0].get("display_name", clean_q)
                try:
                    redis_client.setex(cache_key, 3600, json.dumps([lat, lon, display_name]))
                except Exception as e:
                    logger.warning(f"Geocode cache write error: {e}")
                return lat, lon, display_name
        except Exception as e:
            logger.warning(f"Geocoding exception for {q_variant}: {e}")
    return None, None, None


MAIN_MENU_KEYWORDS = {
    "звіт", "резонанс", "топ", "аналітика", "прогноз", "радар", "статус",
    "карта", "веб-карта", "мяв", "шип", "мур", "premium", "меню", "актуалізація",
    "довідник", "ттх", "графік", "csv", "експорт", "мапу", "мапа", "прес-реліз", "osint", "укриття",
    "відбій", "ключ", "інцидент", "контур", "загроз", "активност", "супутник", "термо"
}


def is_shelter_text_query(message: types.Message) -> bool:
    if not message.text or message.text.startswith('/'):
        return False
    txt = message.text.strip().lower()
    if any(k in txt for k in MAIN_MENU_KEYWORDS) or txt.startswith("sk-"):
        return False
    return len(txt) >= 2


@router.message(Command("shelter"))
@router.message(Command("shelters"))
@router.message(F.text == "📍 Найближче укриття")
async def cmd_shelters_prompt(message: types.Message):
    loc_builder = ReplyKeyboardBuilder()
    loc_builder.button(text="📍 Надіслати мою геопозицію", request_location=True)
    loc_builder.button(text="🔙 Назад до меню")
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


@router.message(F.text == "🔙 Назад до меню")
async def cmd_back_to_menu(message: types.Message):
    await safe_send(
        message,
        "📋 Головне меню активовано. Оберіть потрібну дію:",
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


@router.message(is_shelter_text_query)
async def handle_text_shelter_search(message: types.Message):
    txt = message.text.strip()
    txt_lower = txt.lower()
    
    # 1. Fast Lookup in KYIV_TOPONYM_MAP
    for k, (lat, lon) in KYIV_TOPONYM_MAP.items():
        if k in txt_lower:
            await search_and_send_shelters(message, lat, lon, user_address_text=txt)
            return

    # 2. DB Search with Apostrophe Wildcard
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
    
    # 3. Universal Nominatim Geocoding
    lat, lon, full_name = await asyncio.to_thread(geocode_kyiv_street, txt)
    if lat and lon:
        await search_and_send_shelters(message, lat, lon, user_address_text=txt)
        return

    # 4. Fallback link
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
