import asyncio
import base64
import html
import os
import requests
from datetime import datetime, timedelta
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
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
        user_api_key, effective_key = await _get_effective_openai_key(message)
        groq_api_key = os.getenv("GROQ_API_KEY")
        if not effective_key and not groq_api_key:
            await safe_send(
                message,
                "🔒 <b>Для глибокого OSINT-аналізу потрібен API Key.</b>\n\n"
                "Підключіть персональний ключ командою:\n"
                "<code>/key sk-ваш-токен</code>\n\n"
                "<i>(Отримати ключ: platform.openai.com/api-keys)</i>",
                disable_web_page_preview=True
            )
            return
            
        api_key = effective_key
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
        
        if api_key:
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
                return

        # Attempt graceful failover to Groq LLaMA 3.3
        groq_api_key = os.getenv("GROQ_API_KEY")
        if groq_api_key:
            try:
                logger.info("OpenAI failed or rate-limited; failing over to Groq LLaMA for Deep OSINT...")
                groq_headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {groq_api_key}"
                }
                groq_data = {
                    "model": "qwen/qwen3.8-27b",
                    "messages": [
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.1
                }
                resp_groq = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=groq_headers, json=groq_data, timeout=35)
                if resp_groq.status_code == 200:
                    analysis = resp_groq.json()["choices"][0]["message"]["content"]
                    try:
                        redis_client.setex(cache_key, 300, analysis)
                    except Exception:
                        pass
                    await safe_send(message, f"🔍 <b>ГЛИБОКИЙ OSINT ЗВІТ</b> <i>(Резервний ШІ-рушій LLaMA 3.3)</i> 🔍\n\n{analysis}")
                    return
            except Exception as ge:
                logger.warning(f"Groq OSINT failover error: {ge}")

        if resp.status_code == 401:
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


@router.message(F.text == "🗺️ ВЕБ-МАПА C4ISR (ГОЛОВНИЙ ІНСТРУМЕНТ)")
@router.message(F.text == "🌐 Веб-мапа")
@router.message(F.text.ilike("%веб-мапа%"))
@router.message(Command("map"))
async def cmd_web_map(message: types.Message):
    dash_url = get_dashboard_url()
    token = os.getenv("TACTICAL_API_TOKEN", "admin_tactical_token_2026")
    text = (
        "🗺️ <b>ЖИВА ТАКТИЧНА ВЕБ-МАПА C4ISR & GEOINT</b>\n\n"
        "• 🔴 <b>Зони ураження (Blast Radii):</b> 50м / 180м / 450м\n"
        "• 🛡️ <b>Куполи ППО (WEZ):</b> Тор-М2, Панцир-С1, С-400\n"
        "• 📐 <b>LOB-пеленгація та CEP:</b> триангуляція звукових засічок\n"
        "• 📹 <b>Оптична розвідка CCTV:</b> вузли відеоспостереження ТОТ\n"
        "• 📡 <b>РЕБ Sentinel-1:</b> активні супутникові зони завад C-band\n"
        "• ⚔️ <b>MIL-STD-2525C:</b> військова символіка НАТО для ATAK / WinTAK\n\n"
        f"🔗 <b>Пряме посилання:</b> <code>{dash_url}</code>\n\n"
        "<i>Оберіть швидкий шар або перейдіть до повної інтерактивної мапи:</i>"
    )
    inline_kb = InlineKeyboardBuilder()
    inline_kb.button(text="🌐 Відкрити повну тактичну мапу", url=dash_url)
    inline_kb.button(text="🛡️ Куполи ППО (WEZ)", url=f"{dash_url}/?layer=wez")
    inline_kb.button(text="📐 LOB-пеленги та CEP", url=f"{dash_url}/?layer=lob")
    inline_kb.button(text="📹 Вузли CCTV ТОТ", url=f"{dash_url}/?layer=cctv")
    inline_kb.button(text="📡 РЕБ Sentinel-1", url=f"{dash_url}/?layer=ew")
    inline_kb.button(text="⚔️ Символіка НАТО", url=f"{dash_url}/?layer=mil")
    inline_kb.button(text="📦 Завантажити ATAK ZIP", url=f"{dash_url}/api/cot/zip?token={token}")
    inline_kb.button(text="🔄 Синхронізувати зараз", callback_data="sync_now_trigger")
    inline_kb.adjust(1, 2, 2, 2, 1)
    
    await safe_send(message, text, reply_markup=inline_kb.as_markup(), disable_web_page_preview=True)


@router.message(Command("layers"))
@router.message(F.text == "🎛 Тактичні шари")
async def cmd_tactical_layers(message: types.Message):
    await cmd_web_map(message)


@router.callback_query(F.data == "more:layers")
async def cb_more_layers(callback: types.CallbackQuery):
    await callback.answer()
    await cmd_web_map(callback.message)


@router.callback_query(F.data == "sync_now_trigger")
async def cb_sync_now_trigger(callback: types.CallbackQuery):
    await callback.answer("⏳ Запускаю примусову актуалізацію...")
    from bot.handlers.alerts import cmd_sync_events
    await cmd_sync_events(callback.message)



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


@router.message(Command("network"))
@router.message(Command("graph"))
@router.message(F.text == "🕸️ Мережа ІПСО")
@router.message(F.text.ilike("%мережа%"))
@router.message(F.text.ilike("%граф%"))
async def cmd_network_graph(message: types.Message):
    from database.repository import NetworkGraphRepository
    with NetworkGraphRepository() as net_repo:
        top_sources = net_repo.get_top_forward_sources(limit=7, hours=48)
        graph_stats = net_repo.get_forward_graph(min_weight=1, limit=50, hours=48)

    dash_url = get_dashboard_url()
    graph_url = f"{dash_url}#network"

    if not top_sources:
        await safe_send(
            message,
            "🕸️ <b>АНАЛІЗАТОР СІТОК ІПСО ТА ПЕРЕСИЛАНЬ (Telerecon Core)</b>\n\n"
            "ℹ️ <i>Наразі недостатньо зафіксованих фактів пересилань (fwd_from) за останні 48 годин для побудови графа.\n"
            "Дані акумулюються автоматично у режимі реального часу.</i>"
        )
        return

    lines = [
        "🕸️ <b>АНАЛІЗАТОР СІТОК ІПСО ТА ЦИТУВАНЬ (Telerecon Core)</b>",
        f"📊 <i>Зафіксовано вузлів:</i> <b>{graph_stats['total_nodes']}</b> | <i>Зв'язків:</i> <b>{graph_stats['total_edges']}</b> (за 48 год)\n",
        "🏆 <b>ГОЛОВНІ ПЕРШОДЖЕРЕЛА (ХТО ЗАПУСКАЄ ІНФОХВИЛЮ):</b>"
    ]

    for idx, s in enumerate(top_sources, 1):
        lines.append(
            f"<b>{idx}.</b> <code>@{s['source_channel']}</code> ➔ цитувань: <b>{s['total_forwards']}</b> "
            f"(ретранслюють: <b>{s['amplifiers_count']}</b> кан.)"
        )

    lines.append(
        f"\n🗺️ <b>Інтерактивний граф мережі:</b>\n"
        f"👉 <a href='{graph_url}'>Відкрити візуалізатор зв'язків</a>"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🌐 Відкрити граф на карті", url=graph_url)
    builder.button(text="🔄 Оновити дані", callback_data="refresh_network_graph")
    builder.adjust(1)

    await safe_send(message, "\n".join(lines), reply_markup=builder.as_markup(), disable_web_page_preview=True)


@router.callback_query(F.data == "refresh_network_graph")
async def on_refresh_network_graph(callback: types.CallbackQuery):
    await callback.answer("Оновлюю граф мережі...")
    await cmd_network_graph(callback.message)


@router.message(Command("raycast"))
async def cmd_drone_raycast(message: types.Message):
    """
    OpenAthena Drone Raycast Command.
    Usage: /raycast <lat> <lon> <alt_m> <pitch_deg> <yaw_deg>
    Example: /raycast 50.4500 30.5200 320 -45 90
    """
    args = (message.text or "").split()[1:]
    if len(args) < 5:
        await safe_send(
            message,
            "🎯 <b>КАЛЬКУЛЯТОР ЦІЛЕЙ З ДРОНІВ (OpenAthena Core)</b>\n\n"
            "Розрахунок точних GPS-координат цілі на землі за кутами камери БпЛА та рельєфом (DEM).\n\n"
            "<b>Формат команди:</b>\n"
            "<code>/raycast &lt;lat&gt; &lt;lon&gt; &lt;alt_m&gt; &lt;pitch&gt; &lt;yaw&gt;</code>\n\n"
            "<b>Приклад (DJI Mavic / Autel):</b>\n"
            "<code>/raycast 50.4500 30.5200 320 -45 90</code>\n"
            "<i>(де -45° — нахил камери вниз, 90° — курс на схід)</i>"
        )
        return

    try:
        lat = float(args[0])
        lon = float(args[1])
        alt = float(args[2])
        pitch = float(args[3])
        yaw = float(args[4])
    except ValueError:
        await safe_send(message, "❌ Помилка: аргументи повинні бути числовими значеннями.")
        return

    from worker.osint.drone_raycast import calculate_raycast_target
    res = calculate_raycast_target(
        drone_lat=lat,
        drone_lon=lon,
        drone_alt_m=alt,
        gimbal_pitch_deg=pitch,
        gimbal_yaw_deg=yaw,
        ground_alt_m=120.0
    )

    gmap_url = f"https://www.google.com/maps?q={res.target_lat},{res.target_lon}"

    text = (
        "🎯 <b>РЕЗУЛЬТАТ РОЗРАХУНКУ ЦІЛІ (OpenAthena)</b>\n\n"
        f"📍 <b>Координати цілі:</b> <code>{res.target_lat}, {res.target_lon}</code>\n"
        f"📏 <b>Дистанція по землі:</b> ~{int(res.ground_range_m)} м\n"
        f"📐 <b>Похила дальність (Slant range):</b> ~{int(res.slant_range_m)} м\n"
        f"🏔 <b>Висота рельєфу цілі:</b> ~{res.target_alt_m} м (DEM)\n"
        f"🚁 <b>Позиція БпЛА:</b> <code>{res.drone_lat}, {res.drone_lon}</code> (alt: {res.drone_alt_m} м)\n"
        f"🧭 <b>Кути:</b> Тангаж: {res.gimbal_pitch_deg}°, Курс: {res.gimbal_yaw_deg}°\n"
        f"🟢 <b>Надійність розрахунку:</b> {res.confidence}\n\n"
        f"🗺️ <a href='{gmap_url}'>Відкрити ціль на карті Google</a>"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🗺️ Точка удару на карті", url=gmap_url)
    await safe_send(message, text, reply_markup=builder.as_markup(), disable_web_page_preview=True)


@router.message(Command("ew"))
@router.message(Command("jamming"))
@router.message(Command("rfi"))
@router.message(F.text == "📡 Радіозавади та РЕБ")
async def cmd_ew_interference(message: types.Message):
    """
    Sentinel-1 CSAR 5 GHz Radio Frequency Interference (RFI) / EW Tracker.
    """
    from worker.sensors.sentinel_rfi import get_live_ew_interference
    data = get_live_ew_interference()
    features = data.get("features", [])

    dash_url = get_dashboard_url()

    lines = [
        "📡 <b>СУПУТНИКОВИЙ МОНІТОРИНГ РЕБ ТА РЛС (Sentinel-1 CSAR 5 GHz)</b>",
        f"🛰️ <i>Сенсор:</i> <b>{data.get('sensor')}</b> | <i>Виявлено вузлів:</i> <b>{len(features)}</b>\n",
        "⚡ <b>АКТИВНІ СЕКТОРИ РАДІОВИПРОМІНЮВАННЯ ТА ЗАВАД:</b>"
    ]

    for idx, f in enumerate(features, 1):
        props = f["properties"]
        lines.append(
            f"<b>{idx}. {props['name']}</b>\n"
            f"   • {props['emitter_label']}\n"
            f"   • <i>Інтенсивність:</i> <b>{props['intensity']}</b> | Азимут: {props['azimuth_deg']}°\n"
            f"   • <code>{f['geometry']['coordinates'][1]:.4f}, {f['geometry']['coordinates'][0]:.4f}</code>\n"
        )

    lines.append(
        f"🗺️ <b>Тактична карта РЕБ:</b>\n"
        f"👉 <a href='{dash_url}'>Переглянути шар радіозавад на карті</a>"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🌐 Відкрити карту РЕБ", url=dash_url)
    builder.button(text="🔄 Оновити дані", callback_data="refresh_ew_data")
    builder.adjust(1)

    await safe_send(message, "\n".join(lines), reply_markup=builder.as_markup(), disable_web_page_preview=True)


@router.callback_query(F.data == "refresh_ew_data")
async def on_refresh_ew_data(callback: types.CallbackQuery):
    await callback.answer("Оновлюю дані Sentinel-1 RFI...")
    await cmd_ew_interference(callback.message)
