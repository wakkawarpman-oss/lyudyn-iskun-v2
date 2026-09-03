import asyncio
import functools
import io
import re
from datetime import datetime, timedelta
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode

from bot.export import generate_csv_export
from bot.graph_generator import generate_analytics_graph
from bot.threat_report import generate_live_threat_assessment
from bot.ui_formatter import format_human_event_card, format_source_display
from bot.handlers.utils import (
    safe_send, unique_by_incident,
    CONFIRMED_INCIDENT_TYPES, KYIV_REGION_FILTER, logger
)
from database.models import SessionLocal, DetectedEvent

router = Router()


@router.message(Command("graph"))
@router.message(F.text == "📈 Графік активності")
async def cmd_graph(message: types.Message):
    await message.answer("⏳ Малюю графік активності за 24 години...")
    try:
        loop = asyncio.get_event_loop()
        graph_file = await loop.run_in_executor(None, functools.partial(generate_analytics_graph, hours=24))
        
        if graph_file:
            await message.answer_photo(
                photo=types.BufferedInputFile(graph_file.getvalue(), filename=graph_file.name),
                caption="📈 <b>Динаміка інцидентів та цілей (останні 24 год)</b>",
                parse_mode=ParseMode.HTML
            )
        else:
            await message.answer("Немає достатньо даних для побудови графіка.")
    except Exception as e:
        logger.error(f"Graph error: {e}")
        await message.answer("❌ Помилка генерації графіка.")


@router.message(Command("csv"))
@router.message(F.text == "📊 Експорт CSV")
async def cmd_csv_export(message: types.Message):
    await message.answer("⏳ Формую базу даних інцидентів (CSV) за 24 години...")
    try:
        csv_file = generate_csv_export(hours=24)
        await message.answer_document(
            document=types.BufferedInputFile(csv_file.getvalue(), filename=csv_file.name),
            caption="✅ <b>Дані OSINT платформи (24h).</b>",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"CSV error: {e}")
        await message.answer("❌ Помилка експорту.")



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

        events = unique_by_incident(raw_events)

        if not events:
            await safe_send(
                message,
                "📋 <b>ОПЕРАТИВНИЙ ЗВІТ — КИЇВЩИНА (12 ГОДИН)</b>\n\n"
                "<i>✅ За останні 12 годин підтверджених фізичних інцидентів у Києві та області не зафіксовано (обстановка спокійна).</i>"
            )
            return

        lines = [
            "📋 <b>ОПЕРАТИВНИЙ ЗВІТ — КИЇВЩИНА (12 ГОДИН)</b>\n"
            f"<i>Зафіксовано {len(raw_events)} повідомлень ({len(events)} унікальних інцидентів)</i>\n"
        ]
        for idx, e in enumerate(events[:10], 1):
            lines.append(format_human_event_card(idx, e, show_snippet=True))

        if len(events) > 10:
            lines.append(f"<i>...та ще {len(events) - 10} інцидентів у базі даних.</i>")

        await safe_send(message, "\n".join(lines), disable_web_page_preview=True)
    finally:
        db.close()


@router.message(Command("analytics"))
@router.message(F.text == "📊 Аналітика")
@router.message(F.text.ilike("%аналітик%"))
async def cmd_analytics(message: types.Message):
    db = SessionLocal()
    try:
        threshold_24h = datetime.utcnow() - timedelta(hours=24)
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
        
        dedup_events = unique_by_incident(raw_events)
        total_24h = len(dedup_events)
        
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
                
        source_counts = {}
        for e in raw_events:
            ch = e.source_channel or 'unknown'
            source_counts[ch] = source_counts.get(ch, 0) + 1
            
        sorted_sources = sorted(source_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        sources_str = "\n".join([f"• {format_source_display(ch)}: <b>{cnt} повідомлень</b>" for ch, cnt in sorted_sources]) or "• Немає даних"

        try:
            from worker.tasks import get_time_window_stats
            time_stats = get_time_window_stats(db)
            spike_badge = "🔴 <b>СПАЙК АКТИВНОСТІ (Хвиля / Залп)</b>" if time_stats.get("spike") else "🟢 <b>Спокійно (Фонова активність)</b>"
            window_str = (
                f"⏱️ <b>Що відбувається зараз:</b>\n"
                f"• За останні 5 хв: <code>{time_stats.get('events_5m', 0)}</code> | за 15 хв: <code>{time_stats.get('events_15m', 0)}</code> | за 60 хв: <code>{time_stats.get('events_60m', 0)}</code>\n"
                f"• Стан активності: {spike_badge}\n\n"
            )
        except Exception as twe:
            logger.warning(f"Time window calculation warning: {twe}")
            window_str = ""

        text = (
            "📊 <b>ОПЕРАТИВНА ОБСТАНОВКА — КИЇВЩИНА (24 ГОДИНИ)</b>\n\n"
            f"За останні 24 години система зафіксувала <b>{len(raw_events)} первинних повідомлень</b> "
            f"(після дедублікації та фільтрації — <b>{total_24h} унікальних подій</b>).\n\n"
            f"{window_str}"
            "🎯 <b>Розподіл унікальних подій за 24 години:</b>\n"
            f"• 🛸 <b>БпЛА / Радарні цілі:</b> <code>{cats['bpla']}</code>\n"
            f"• 💥 <b>Влучання та вибухи:</b> <code>{cats['strike']}</code>\n"
            f"• 🔥 <b>Пожежі та наслідки:</b> <code>{cats['fire']}</code>\n"
            f"• 🛡️ <b>Зафіксована робота ППО:</b> <code>{cats['defense']}</code>\n"
            f"• ⚠️ <b>Інші повідомлення:</b> <code>{cats['other']}</code>\n\n"
            "📡 <b>ТОП-5 джерел моніторингу за обсягом:</b>\n"
            f"{sources_str}\n\n"
            "🗺️ <i>Для перегляду інтерактивної мапи натисніть <b>/map</b>!</i>"
        )
        
        await safe_send(message, text, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Analytics error: {e}")
        await safe_send(message, f"❌ Помилка формування аналітики: {e}")
    finally:
        db.close()


@router.message(Command("export"))
@router.message(Command("pdf"))
@router.message(F.text == "📥 Експорт прес-релізу")
async def cmd_export_report(message: types.Message):
    await message.answer("⏳ Формую верифікований прес-реліз (Markdown)...")
    
    report_ua = generate_live_threat_assessment(lang="ua")
    report_en = generate_live_threat_assessment(lang="en")
    
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
    clean_md = re.sub(r'<[^>]+>', '', full_md)
    
    file_bytes = io.BytesIO(clean_md.encode('utf-8'))
    file_bytes.name = f"Iskun_PressRelease_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.md"
    
    await message.answer_document(
        document=types.BufferedInputFile(file_bytes.getvalue(), filename=file_bytes.name),
        caption="✅ Верифікований прес-реліз готовий до публікації."
    )
