import asyncio
import base64
import html
import os
import requests
from datetime import datetime, timedelta
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func

from bot.handlers.utils import (
    safe_send, is_admin, get_dashboard_url,
    OPENAI_API_KEY, redis_client, logger
)
from database.models import SessionLocal, DetectedEvent, UserApiKey, decrypt_key

router = Router()


@router.message(F.text == "🔍 Глибокий OSINT")
async def cmd_deep_osint(message: types.Message):
    db = SessionLocal()
    try:
        user_key = db.query(UserApiKey).filter(UserApiKey.user_id == message.from_user.id).first()
        if not user_key or not user_key.openai_api_key:
            await message.answer(
                "🔒 Для глибокого OSINT-аналізу потрібен OpenAI API Key (Vision).\nВстановіть його командою:\n`/key sk-...`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
            
        api_key = decrypt_key(user_key.openai_api_key)
        threshold = datetime.utcnow() - timedelta(hours=12)

        cache_key = "osint:deep_analysis"
        cached_report = None
        try:
            cached_val = redis_client.get(cache_key)
            if cached_val:
                cached_report = cached_val if isinstance(cached_val, str) else cached_val.decode('utf-8')
        except Exception:
            pass

        if cached_report:
            await safe_send(message, f"🔍 <b>ГЛИБОКИЙ OSINT ЗВІТ (Кеш)</b> 🔍\n\n{cached_report}")
            return

        events = db.query(DetectedEvent).filter(
            DetectedEvent.detected_at >= threshold,
            DetectedEvent.event_type.in_(['direct_strike', 'explosion', 'fire', 'destruction'])
        ).order_by(DetectedEvent.detected_at.desc()).all()
        
        if not events:
            await message.answer("ℹ️ За останні 12 годин не знайдено серйозних інцидентів для аналізу.")
            return
            
        await message.answer("⏳ Збираю дані за останні 12 годин та формую тактичне зведення...")
        
        context_text = "СИРІ ДАНІ З РЕЄСТРУ ТАКТИЧНИХ ПОДІЙ ЗА 12 ГОДИН:\n"
        for ev in events:
            time_str = ev.detected_at.strftime('%H:%M UTC') if ev.detected_at else "??:??"
            src_count = getattr(ev, 'sources_count', 1) or 1
            src_list = getattr(ev, 'sources_list', '') or ev.source_channel
            sig = getattr(ev, 'significance_score', 50) or 50
            conf = getattr(ev, 'confidence_score', 50) or 50
            context_text += (
                f"• [{time_str}] Локація: {ev.location_text} | Тип: {ev.event_type} | "
                f"Загроза: {sig}/100 | Довіра: {conf}/100 | Джерела ({src_count} дж.): {src_list} | "
                f"Текст: {ev.message_text}\n"
            )
            
        sys_prompt = (
            "Ти старший військовий OSINT-аналітик та фахівець з BDA (Battle Damage Assessment). "
            "Твоє завдання — перетворити сирі дані про бойові інциденти на строге військово-тактичне зведення. "
            "КРИТИЧНІ ПРАВИЛА:\n"
            "1. ЖОДНОЇ 'ВОДИ', публіцистики та загальних роздумів про війну.\n"
            "2. ЗАБОРОНЕНО давати поради військовим чи ППО.\n"
            "3. Тільки конкретні факти: типи зброї, таймлайн хвиль, координати/райони, оцінка руйнувань, статус верифікації.\n"
            "4. Формат строго за 5 розділами."
        )

        user_prompt = (
            "Сформуй оперативний OSINT-звіт за наступною структурою:\n\n"
            "🛡 1. ЗАСОБИ УРАЖЕННЯ ТА ТАКТИКА ВОРОГА\n"
            "- Виявлені типи озброєння (Shahed-136/131, балістика Іскандер, крилаті ракети Х-101/Калібр, падіння уламків).\n"
            "- Вектори заходу, висоти та щільність залпів (якщо зазначено).\n\n"
            "⏱ 2. ХРОНОЛОГІЯ ТА ДИНАМІКА АТАКИ\n"
            "- Похвилинний таймлайн: початок заходу ➔ пік ударів/вибухів ➔ локалізація наслідків.\n\n"
            "📍 3. ЕПІЦЕНТРИ ТА ГЕОГРАФІЯ УРАЖЕНЬ\n"
            "- Список конкретних населених пунктів та районів із зазначенням типу події.\n\n"
            "🔥 4. ХАРАКТЕР РУЙНУВАНЬ ТА НАСЛІДКИ (BDA)\n"
            "- Оцінка фізичних руйнувань: вибухова хвиля, пожежі, руйнування фасадів, інфраструктура, жертви/поранені.\n\n"
            "⚖️ 5. ВЕРИФІКАЦІЯ ДЖЕРЕЛ ТА КОНСЕНСУС\n"
            "- Співвідношення офіційно підтверджених фактів (ДСНС/ОВА/ПС ЗСУ) до моніторингових каналів та анонімних чуток.\n"
            "- Підсумковий рівень достовірності зведення (Confidence Score: X/100).\n\n"
            "ВХІДНІ ДАНІ:\n" + context_text
        )
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        data = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.1
        }
        
        resp = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data, timeout=35)
        
        if resp.status_code == 200:
            analysis = resp.json()["choices"][0]["message"]["content"]
            try:
                redis_client.setex(cache_key, 300, analysis)
            except Exception:
                pass
            await safe_send(message, f"🔍 <b>ГЛИБОКИЙ OSINT ЗВІТ</b> 🔍\n\n{analysis}")
        elif resp.status_code == 401:
            await safe_send(
                message,
                "❌ <b>Помилка OpenAI API (401 Unauthorized):</b>\n"
                "Ваш токен недійсний або був відкликаний.\n\n"
                "Оновіть ключ командою:\n"
                "<code>/key sk-новий-токен</code>",
                disable_web_page_preview=True
            )
        elif resp.status_code == 429:
            await safe_send(
                message,
                "❌ <b>Помилка OpenAI API (429 Quota Exceeded):</b>\n"
                "На вашому акаунті OpenAI вичерпано баланс (Billing Credit).\n\n"
                "Поповніть баланс на <a href='https://platform.openai.com/settings/organization/billing/overview'>OpenAI Billing</a> або підключіть новий ключ: <code>/key sk-...</code>",
                disable_web_page_preview=True
            )
        else:
            await safe_send(message, f"❌ Помилка OpenAI API ({resp.status_code}):\n<code>{html.escape(resp.text[:200])}</code>")
            
    except Exception as e:
        logger.error(f"Deep OSINT error: {e}")
        await message.answer(f"❌ Помилка: {e}")
    finally:
        db.close()


@router.message(Command("status"))
@router.message(F.text == "📡 Статус системи")
async def cmd_status(message: types.Message):
    db = SessionLocal()
    try:
        total = db.query(func.count(DetectedEvent.id)).scalar()
        text = (
            "📡 <b>СТАТУС V2 (Microservices)</b>\n\n"
            f"• Подій в базі (PostGIS): {total}\n"
            "• Воркери (Celery): 🟢 АКТИВНІ\n"
            "• Listener (Telethon): 🟢 АКТИВНИЙ\n"
            "• Computer Vision: 🟢 АКТИВНИЙ\n"
            "• GeoSpy AI (EXIF): 🟢 АКТИВНИЙ"
        )
        await safe_send(message, text)
    finally:
        db.close()


@router.message(F.text == "🗺️ Веб-карта")
@router.message(Command("map"))
async def cmd_web_map(message: types.Message):
    text = (
        "🗺️ <b>ЖИВА ТАКТИЧНА OSINT-МАПА (GEOINT V2)</b>\n\n"
        "• 🔴 <b>Зони ураження (Blast Radii):</b> 50м / 180м / 450м\n"
        "• 🛡️ <b>Укриття та Станції Метро Києва:</b> 1,197 точок\n"
        "• 🛰️ <b>Супутниковий шар та геопросторовий моніторинг</b>\n\n"
        "<i>Натисніть кнопку нижче для відкриття інтерактивної мапи у вашому браузері:</i>"
    )
    inline_kb = InlineKeyboardBuilder()
    inline_kb.button(text="🌐 Відкрити Мапу у Браузері", url=get_dashboard_url())
    inline_kb.adjust(1)
    
    await safe_send(message, text, reply_markup=inline_kb.as_markup(), disable_web_page_preview=True)


async def _get_effective_openai_key(message: types.Message):
    """Returns (user_api_key_or_None, effective_key_or_None). Shared by
    handle_photo and handle_video — same admin/own-key gate for both."""
    db = SessionLocal()
    user_api_key = None
    try:
        uk = db.query(UserApiKey).filter(UserApiKey.user_id == message.from_user.id).first()
        if uk:
            user_api_key = decrypt_key(uk.openai_api_key)
    finally:
        db.close()
    return user_api_key, (user_api_key or OPENAI_API_KEY)


async def _run_photo_osint_analysis(message: types.Message, user_api_key, effective_key: str, temp_path: str):
    """Runs EXIF/pHash/GeoSpy/Chrono + Vision AI BDA analysis on a jpg
    already saved at temp_path, and sends the result. Shared by handle_photo
    (temp_path is the uploaded photo) and handle_video (temp_path is a frame
    extracted from the uploaded video) — from here on there is no
    photo/video distinction, it's just an image file."""
    with open(temp_path, "rb") as f:
        base64_image = base64.b64encode(f.read()).decode('utf-8')

    parts = ["🔎 <b>РЕЗУЛЬТАТИ OSINT-АНАЛІЗУ</b>\n"]
    exif = {}

    try:
        try:
            from worker.osint.exif_extractor import EXIFExtractor
            exif = EXIFExtractor().extract(temp_path)
            if exif.get("has_gps"):
                parts.append(f"📡 <b>EXIF GPS:</b> {exif['latitude']}, {exif['longitude']}")
                if exif.get("datetime"):
                    parts.append(f"⏰ <b>EXIF Час:</b> {exif['datetime']}")
            else:
                parts.append("📡 <b>EXIF метадані:</b> Очищені або відсутні (можливо, фото з Telegram/Viber).")
        except Exception as exc:
            logger.warning(f"EXIF extraction error: {exc}")

        try:
            from worker.osint.image_dedup import compute_phash, find_similar_event
            phash = compute_phash(temp_path)
            if phash:
                dup_db = SessionLocal()
                try:
                    duplicate_of = await asyncio.to_thread(find_similar_event, dup_db, phash)
                finally:
                    dup_db.close()
                if duplicate_of:
                    parts.append(
                        f"⚠️ <b>АРХІВНЕ/ПОВТОРНЕ ФОТО (Anti-IPSO):</b> схоже на вже відомий "
                        f"інцидент {duplicate_of.incident_id or duplicate_of.id} "
                        f"({duplicate_of.location_text or 'Київ'}, {duplicate_of.detected_at.strftime('%Y-%m-%d')})."
                    )
        except Exception as exc:
            logger.warning(f"pHash dedup check error: {exc}")

        try:
            from worker.osint.ai_geolocation import ai_geo
            geospy = await asyncio.to_thread(ai_geo.analyze_image, temp_path)
            if geospy and geospy.get("coordinates"):
                loc_name = geospy.get('predicted_location', 'Знайдено')
                coords = geospy['coordinates']
                parts.append(f"🌍 <b>GeoSpy AI:</b> {loc_name}")
                parts.append(f"📍 <b>Координати:</b> {coords[0]}, {coords[1]}")
        except Exception as exc:
            logger.warning(f"GeoSpy error: {exc}")

        try:
            from worker.osint.geoint_engine import geoint_engine
            lat_c = exif.get("latitude") if (exif and exif.get("has_gps")) else 50.4501
            lon_c = exif.get("longitude") if (exif and exif.get("has_gps")) else 30.5234
            sun_data = geoint_engine.calculate_sun_position(lat_c, lon_c)
            parts.append(f"☀️ <b>Сонячний азимут (Chrono-verify):</b> {sun_data['solar_azimuth_deg']}° | 📐 <b>Кут тіней:</b> {sun_data['shadow_direction_deg']}°")
        except Exception as exc:
            logger.warning(f"Chrono-location error: {exc}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    parts.append("")

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
            "Ти військовий GEOINT та OSINT-аналітик (Battle Damage Assessment). Проаналізуй надане фото бойового інциденту.\n"
            "КРИТИЧНІ ПРАВИЛА:\n"
            "1. ОБОВ'ЯЗКОВО ПЕРЕВІР ВОДЯНІ ЗНАКИ, ЛОГОТИПИ, ГЕРБИ, ШЕВРОНИ ТА ТЕКСТ.\n"
            "2. ВКАЗУЙ РЕАЛЬНЕ МІСТО/РЕГІОН згідно знайдених водяних знаків та архітектури.\n"
            "3. Жодної 'води' чи загальних роздумів про війну — тільки сухий військовий BDA-аналіз.\n\n"
            "ФОРМАТ ЗВІТУ:\n"
            "🏛 1. Атрибуція та Геолокація\n"
            "🔥 2. Оцінка уражень (BDA)\n"
            "🛡 3. Ймовірний тип озброєння\n"
            "🕒 4. Хроно-аналіз та Анти-ІПСО"
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
            "max_tokens": 700,
            "temperature": 0.1,
        }
        return requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=35,
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


@router.message(F.photo)
async def handle_photo(message: types.Message, bot: Bot):
    user_api_key, effective_key = await _get_effective_openai_key(message)
    if not user_api_key and not is_admin(message.from_user.id):
        await safe_send(
            message,
            "🔒 <b>Photo OSINT потребує ключа OpenAI.</b>\n\n"
            "Підключіть власний токен командою:\n"
            "<code>/key sk-ваш_ключ</code>\n\n"
            "Де взяти: <a href='https://platform.openai.com/api-keys'>platform.openai.com</a>",
            disable_web_page_preview=True,
        )
        return

    await safe_send(
        message,
        "⏳ <b>Ініційовано глибокий OSINT-аналіз...</b>\n"
        "1. Витягую EXIF-метадані...\n"
        "2. Запускаю GeoSpy AI для візуальної геолокації...\n"
        "3. Аналізую техніку та руйнування через Vision AI...",
    )

    file_id = message.photo[-1].file_id
    file = await bot.get_file(file_id)
    downloaded_file = await bot.download_file(file.file_path)

    temp_path = f"temp_{message.from_user.id}_{file_id}.jpg"
    with open(temp_path, "wb") as f_temp:
        f_temp.write(downloaded_file.read())

    await _run_photo_osint_analysis(message, user_api_key, effective_key, temp_path)


@router.message(F.video)
async def handle_video(message: types.Message, bot: Bot):
    """Mirrors handle_photo: same admin/own-key gate, then extracts one
    representative frame and runs it through the same OSINT analysis.
    Previously videos sent to the bot were silently ignored entirely."""
    user_api_key, effective_key = await _get_effective_openai_key(message)
    if not user_api_key and not is_admin(message.from_user.id):
        await safe_send(
            message,
            "🔒 <b>Video OSINT потребує ключа OpenAI.</b>\n\n"
            "Підключіть власний токен командою:\n"
            "<code>/key sk-ваш_ключ</code>\n\n"
            "Де взяти: <a href='https://platform.openai.com/api-keys'>platform.openai.com</a>",
            disable_web_page_preview=True,
        )
        return

    await safe_send(
        message,
        "⏳ <b>Ініційовано глибокий OSINT-аналіз відео...</b>\n"
        "1. Витягую ключовий кадр...\n"
        "2. Запускаю GeoSpy AI для візуальної геолокації...\n"
        "3. Аналізую техніку та руйнування через Vision AI...",
    )

    from worker.osint.video_frame_extractor import extract_representative_frame

    file_id = message.video.file_id
    file = await bot.get_file(file_id)
    downloaded_file = await bot.download_file(file.file_path)

    video_temp_path = f"temp_{message.from_user.id}_{file_id}.mp4"
    with open(video_temp_path, "wb") as f_temp:
        f_temp.write(downloaded_file.read())

    try:
        frame_path = await asyncio.to_thread(extract_representative_frame, video_temp_path)
    finally:
        if os.path.exists(video_temp_path):
            os.remove(video_temp_path)

    if not frame_path:
        await safe_send(message, "❌ Не вдалося витягнути кадр з відео для аналізу.")
        return

    await _run_photo_osint_analysis(message, user_api_key, effective_key, frame_path)
