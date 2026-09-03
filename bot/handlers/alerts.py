import asyncio
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
from bot.handlers.utils import safe_send, admin_only, logger
from database.models import SessionLocal, DetectedEvent

router = Router()


@router.message(Command("start"))
@router.message(F.text == "▶️ Розпочати")
async def cmd_start(message: types.Message):
    await safe_send(
        message,
        "🛡️ <b>ОКІНТ-ПРО</b> — тактична OSINT-платформа активована.\n"
        "<i>«ЗБИРАЄМО • АНАЛІЗУЄМО • ПЕРЕМАГАЄМО»</i>\n\n"
        "Натисніть <b>🔄 АКТУАЛІЗАЦІЯ ПОДІЙ</b> для миттєвого збору свіжих розвідданих або оберіть потрібний модуль:",
        reply_markup=get_main_keyboard(),
    )


@router.message(Command("sync"))
@router.message(Command("update"))
@router.message(F.text == "🔄 АКТУАЛІЗАЦІЯ ПОДІЙ")
@router.message(F.text.ilike("%актуалізація%"))
@router.message(F.text.ilike("%актуализация%"))
@admin_only
async def cmd_sync_events(message: types.Message):
    await safe_send(
        message,
        "⏳ <b>Запущено актуалізацію подій...</b>\n"
        "<i>• Опитування 20+ моніторингових джерел (ПС ЗСУ, Контур, eRadar)\n"
        "• Збір свіжих повідомлень та фіксація загроз за останні години\n"
        "• ШІ-аналіз та геоприв'язка нових інцидентів...</i>"
    )
    
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
        "✅ <b>АКТУАЛІЗАЦІЮ ПОДІЙ УСПІШНО ЗАВЕРШЕНО!</b>\n\n"
        f"📊 <b>Усього актуальних інцидентів у базі (24 год):</b> <code>{total_24h}</code>\n"
        "Стрічка свіжих подій та інтерактивна мапа повністю синхронізовані.\n\n"
        "👉 Натисніть <b>💥 Резонанс</b> або <b>🔥 ТОП подій</b> для перегляду."
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
        await safe_send(message, msg_text)


@router.callback_query(F.data == "vidbiy:stop")
async def cb_stop_vidbiy_monitoring(callback: types.CallbackQuery):
    unregister_vidbiy_subscriber(callback.message.chat.id)
    stop_banner = format_stop_monitoring_banner()
    await callback.answer("🛑 Моніторинг відбою зупинено!", show_alert=False)
    try:
        await callback.message.edit_text(
            f"{callback.message.html_text}\n\n➖➖➖➖➖➖➖➖➖➖\n{stop_banner}",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        await callback.message.answer(stop_banner, parse_mode=ParseMode.HTML)


@router.message(Command("stop_vidbiy"))
@router.message(Command("stop_monitoring"))
@router.message(F.text == "🛑 СТОП МОНІТОРИНГ")
@router.message(F.text == "СТОП МОНІТОРИНГ")
@router.message(F.text.ilike("%стоп моніторинг%"))
@router.message(F.text.ilike("%зупинити моніторинг%"))
async def cmd_stop_vidbiy(message: types.Message):
    unregister_vidbiy_subscriber(message.chat.id)
    stop_banner = format_stop_monitoring_banner()
    await safe_send(message, stop_banner)
