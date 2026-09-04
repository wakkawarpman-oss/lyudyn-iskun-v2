import os
from datetime import datetime, timedelta
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from sqlalchemy import func

from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.keyboards import get_main_keyboard
from bot.alert_monitor import (
    get_current_kyiv_alert_status,
    format_all_clear_banner,
    format_active_alert_banner,
    format_stop_monitoring_banner,
    register_vidbiy_subscriber,
    unregister_vidbiy_subscriber
)
from bot.handlers.utils import safe_send, logger, get_dashboard_url
from database.models import SessionLocal, DetectedEvent

router = Router()


@router.message(Command("start"))
@router.message(F.text == "▶️ Розпочати")
async def cmd_start(message: types.Message):
    greeting = (
        "🛡️ <b>ОКІНТ-ПРО — МУЛЬТИДОМЕННИЙ C4ISR/OSINT АРСЕНАЛ</b>\n"
        "<i>«ЗБИРАЄМО • АНАЛІЗУЄМО • ПЕРЕМАГАЄМО»</i>\n\n"
        "Платформа безперервно інтегрує космічні, радарні, радіоелектронні та агентурні потоки 24/7. "
        "Ось ключові інструменти та їхня суть:\n\n"
        "🛸 <b>NEPTUN LIVE / РАДАР «КОНТУР»</b> (<code>/radar</code>)\n"
        "↳ <i>Суть:</i> Живий радар повітряних цілей у небі України. Автоматичний розрахунок курсу, швидкості та часу підльоту БпЛА/ракет до Києва методом Dead Reckoning.\n\n"
        "✈️ <b>ADS-B ТРЕКІНГ АВІАЦІЇ (OpenSky / ADSBexchange)</b>\n"
        "↳ <i>Суть:</i> Детекція реальних бортів та транспондерів над координатами інцидентів у заданий час, виявлення розвідувальної авіації.\n\n"
        "⚓ <b>AIS МОРСЬКИЙ МОНІТОРИНГ (MarineTraffic)</b>\n"
        "↳ <i>Суть:</i> Спектральний моніторинг судноплавства Чорного та Азовського морів, виявлення ворожих військових конвоїв та морських блокад.\n\n"
        "🛰️ <b>СУПУТНИКИ SENTINEL-2 ТА NASA FIRMS</b> (<code>/satellite</code>)\n"
        "↳ <i>Суть:</i> Мультиспектральний космічний аналіз (Sentinel Hub) для виявлення оптичних змін/руйнувань до і після ударів + термоточки вибухів VIIRS.\n\n"
        "🛡️ <b>КУПОЛИ ППО ТА ЗОНИ ВОГНЮ WEZ</b> (<code>/layers</code>)\n"
        "↳ <i>Суть:</i> Розрахунок реальних ТТХ, радіусів РЛС та зон ураження комплексів Тор-М2, Панцир-С1, Бук-М3, С-400.\n\n"
        "📐 <b>LOB-ПЕЛЕНГАЦІЯ ТА ВЕРИФІКАЦІЯ CEP</b> (<code>/layers</code>)\n"
        "↳ <i>Суть:</i> Пряма геодезична засічка WGS-84, триангуляція азимутів спостереження та кругове ймовірне відхилення епіцентру.\n\n"
        "📹 <b>ОПТИЧНА РОЗВІДКА CCTV ТОТ</b> (<code>/layers</code>)\n"
        "↳ <i>Суть:</i> Вузли відеоспостереження та аналітики ТОТ (Донецьк, Севастополь, Харків, Енергодар).\n\n"
        "📻 <b>SIGINT РАДІОПЕРЕХОПЛЕННЯ ТА РЕБ</b> (<code>/ew</code>)\n"
        "↳ <i>Суть:</i> Супутниковий моніторинг радіозавад Sentinel-1 CSAR 5 GHz + кореляція військового радіоефіру.\n\n"
        "☀️ <b>ХРОНОЛОКАЦІЯ СОНЯЧНИХ ТІНЕЙ (NOAA)</b>\n"
        "↳ <i>Суть:</i> Верифікація часу зйомки кадрів за астрономічним кутом сонця та вектором тіні об'єктів.\n\n"
        "🗺️ <b>NOTAMs АНАЛІЗ</b>\n"
        "↳ <i>Суть:</i> Контроль повідомлень про закриття повітряного простору та зон особливих режимів польотів військової авіації.\n\n"
        "🟢 <b>ВІДБІЙ МОНІТОРИНГ</b> (<code>/vidbiy</code>)\n"
        "↳ <i>Суть:</i> Відстежує найшвидше підтвердження відбою тривоги. Ви першими знаєте, коли відкриваються магазини, ТРЦ, кафе та відновлює рух транспорт.\n\n"
        "🎯 <b>ПРОГНОЗ ЗАГРОЗ</b> (<code>/threats</code>)\n"
        "↳ <i>Суть:</i> Зведення балістичних загроз та активності стратегічної авіації РФ (Ту-95МС, МіГ-31К, Оленья, Енгельс).\n\n"
        "🕸️ <b>МЕРЕЖА ТА ІПСО (TELERECON)</b> (<code>/network</code>)\n"
        "↳ <i>Суть:</i> Граф зв'язків та пересилань між 20+ каналами для виявлення скоординованих інформаційних атак та ботоферм.\n\n"
        "📸 <b>МУЛЬТИМОДАЛЬНИЙ VISION AI</b>\n"
        "↳ <i>Суть:</i> Надішліть боту фото чи відео кадру з дрона — нейромережа розрахує координати, тип озброєння та пошкодження.\n\n"
        "👇 <b>Оберіть потрібний інструмент на клавіатурі нижче:</b>"
    )
    await safe_send(message, greeting, reply_markup=get_main_keyboard())
    from bot.handlers.osint import get_dashboard_url
    dash_url = get_dashboard_url()
    inline_kb = InlineKeyboardBuilder()
    inline_kb.button(text="🗺️ ВІДКРИТИ ЖИВУ ТАКТИЧНУ ВЕБ-МАПУ", url=dash_url)
    inline_kb.button(text="🎛 ТАКТИЧНІ ШАРИ", callback_data="more:layers")
    inline_kb.adjust(1, 1)
    await safe_send(
        message,
        "🗺️ <b>ГОЛОВНИЙ ІНСТРУМЕНТ СИСТЕМИ — ТАКТИЧНА ВЕБ-МАПА C4ISR:</b>\n"
        "<i>Повний живий моніторинг повітряних цілей, куполів ППО, LOB-пеленгів, укриттів та зон ураження.</i>",
        reply_markup=inline_kb.as_markup()
    )


@router.message(Command("sync"))
@router.message(Command("update"))
@router.message(F.text == "🔄 АКТУАЛІЗАЦІЯ ПОДІЙ")
@router.message(F.text.ilike("%актуалізація%"))
@router.message(F.text.ilike("%актуализация%"))
async def cmd_sync_events(message: types.Message):
    import redis.asyncio as aioredis
    r = aioredis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
    
    # 20s cooldown per chat to prevent spamming
    rate_key = f"rate:sync:{message.chat.id}"
    try:
        is_locked = await r.get(rate_key)
        if is_locked:
            await safe_send(
                message,
                "⏳ <b>Опитування джерел уже виконується у фоні.</b>\n\n"
                "Зачекайте 15-30 секунд для завершення ШІ-аналізу або натисніть "
                "<b>💥 Резонанс</b> / <b>🎖 Ключові інциденти</b> для перегляду останніх даних."
            )
            return
        await r.setex(rate_key, 20, "1")
    except Exception as exc:
        logger.warning(f"Sync rate limit error: {exc}")

    await safe_send(
        message,
        "⏳ <b>Запущено актуалізацію подій...</b>\n"
        "<i>• Опитування 20+ моніторингових джерел (ПС ЗСУ, Контур, eRadar)\n"
        "• Збір свіжих повідомлень та фіксація загроз за останні години\n"
        "• ШІ-аналіз та геоприв'язка нових інцидентів...</i>"
    )
    
    # Snapshot BEFORE triggering sync — this is the pre-sync baseline, not a
    # result of the sync we're about to kick off (see below for why we can't
    # honestly report a post-sync count here).
    db = SessionLocal()
    total_24h_before = 0
    try:
        threshold = datetime.utcnow() - timedelta(hours=24)
        total_24h_before = db.query(func.count(DetectedEvent.id)).filter(
            DetectedEvent.detected_at >= threshold,
            DetectedEvent.source_channel.not_ilike('test%')
        ).scalar() or 0
    finally:
        db.close()

    import redis.asyncio as aioredis
    try:
        r = aioredis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
        await r.publish("sync_commands", "sync_now")
    except Exception as e:
        logger.error(f"Redis publish error: {e}")

    # NOT claiming completion here: the listener re-fetches up to 5 messages
    # from each of 20+ channels, and each one runs the full LLM+geocode
    # pipeline (real Groq API calls) asynchronously via Celery — that
    # reliably takes longer than any fixed short wait would cover. Only say
    # what's actually true: it was triggered, and processing runs in the
    # background.
    dash_url = get_dashboard_url()
    sync_kb = InlineKeyboardBuilder()
    sync_kb.button(text="🗺️ Переглянути оновлену мапу", url=dash_url)
    sync_kb.button(text="🎛 Тактичні шари", callback_data="more:layers")
    sync_kb.adjust(1, 1)

    await safe_send(
        message,
        "🔄 <b>Актуалізацію ЗАПУЩЕНО у фоні.</b>\n\n"
        f"📊 <b>Інцидентів у базі станом ЗАРАЗ (24 год, до цього запуску):</b> <code>{total_24h_before}</code>\n"
        "20+ джерел опитуються, нові повідомлення проходять ШІ-аналіз та геоприв'язку — "
        "це займає час, не миттєво. Нові/оновлені дані з'являться в стрічці та на мапі "
        "протягом ~30-60 секунд по мірі обробки.\n\n"
        "👉 Натисніть <b>💥 Резонанс</b> або <b>🎖 Ключові інциденти</b> за хвилину-дві для перегляду.",
        reply_markup=sync_kb.as_markup()
    )


@router.message(Command("vidbiy"))
@router.message(Command("all_clear"))
@router.message(F.text == "🟢 ВІДБІЙ МОНІТОРИНГ")
@router.message(F.text == "ВІДБІЙ МОНІТОРИНГ")
@router.message(F.text == "🟢 ВІДБІЙ")
@router.message(F.text == "ВІДБІЙ")
async def cmd_vidbiy_monitoring(message: types.Message):
    status = get_current_kyiv_alert_status()
    if status["is_alert"]:
        register_vidbiy_subscriber(message.chat.id)
        msg_text = format_active_alert_banner(
            region="м. Київ та Київська область",
            event_time=status.get("timestamp"),
            threat_info="Загроза ударних БпЛА / ракетної небезпеки"
        )
        inline_kb = InlineKeyboardBuilder()
        inline_kb.button(text="🛑 СТОП МОНІТОРИНГ", callback_data="vidbiy:stop")
        inline_kb.adjust(1)
        await safe_send(message, msg_text, reply_markup=inline_kb.as_markup())
    else:
        msg_text = format_all_clear_banner(
            region="м. Київ та Київська область",
            event_time=status.get("timestamp"),
            source=status.get("source", "КМВА / Офіційний моніторинг тривог (@kyiv_alarm)")
        )
        inline_kb = InlineKeyboardBuilder()
        inline_kb.button(text="🔔 Чергувати наступний відбій", callback_data="vidbiy:subscribe_next")
        inline_kb.adjust(1)
        await safe_send(message, msg_text, reply_markup=inline_kb.as_markup())


@router.callback_query(F.data == "vidbiy:subscribe_next")
async def cb_subscribe_next(callback: types.CallbackQuery):
    register_vidbiy_subscriber(callback.message.chat.id)
    await callback.answer("✅ Підписку на відбій активовано!", show_alert=True)
    inline_kb = InlineKeyboardBuilder()
    inline_kb.button(text="🛑 СТОП МОНІТОРИНГ", callback_data="vidbiy:stop")
    inline_kb.adjust(1)
    await callback.message.reply(
        "🔔 <b>РЕЖИМ ОЧІКУВАННЯ ВІДБОЮ АКТИВОВАНО:</b>\n"
        "Скрипт постійно чергує найшвидші джерела. При оголошенні відбою ви негайно отримаєте великий зелений банер про відкриття магазинів та транспорту.",
        reply_markup=inline_kb.as_markup()
    )


@router.callback_query(F.data == "vidbiy:stop")
async def cb_stop_vidbiy_monitoring(callback: types.CallbackQuery):
    unregister_vidbiy_subscriber(callback.message.chat.id)
    stop_banner = format_stop_monitoring_banner()
    await callback.answer("🛑 Моніторинг відбою зупинено!", show_alert=False)
    inline_kb = InlineKeyboardBuilder()
    inline_kb.button(text="🟢 ВІДБІЙ МОНІТОРИНГ", callback_data="vidbiy:subscribe_next")
    inline_kb.adjust(1)
    try:
        await callback.message.edit_text(
            f"{callback.message.html_text}\n\n➖➖➖➖➖➖➖➖➖➖\n{stop_banner}",
            reply_markup=inline_kb.as_markup(),
            parse_mode=ParseMode.HTML
        )
    except Exception:
        await callback.message.answer(stop_banner, reply_markup=inline_kb.as_markup(), parse_mode=ParseMode.HTML)


@router.message(Command("stop_vidbiy"))
@router.message(Command("stop_monitoring"))
@router.message(F.text == "🛑 СТОП МОНІТОРИНГ")
@router.message(F.text == "СТОП МОНІТОРИНГ")
@router.message(F.text.ilike("%стоп моніторинг%"))
@router.message(F.text.ilike("%зупинити моніторинг%"))
async def cmd_stop_vidbiy(message: types.Message):
    unregister_vidbiy_subscriber(message.chat.id)
    stop_banner = format_stop_monitoring_banner()
    inline_kb = InlineKeyboardBuilder()
    inline_kb.button(text="🟢 УВІМКНУТИ МОНІТОРИНГ", callback_data="vidbiy:subscribe_next")
    inline_kb.adjust(1)
    await safe_send(message, stop_banner, reply_markup=inline_kb.as_markup())
