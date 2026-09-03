import asyncio
from datetime import datetime, timedelta
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.threat_report import generate_live_threat_assessment, generate_reference_card
from bot.ui_formatter import format_human_event_card, format_kyiv_time, format_source_display, clean_event_snippet
from bot.handlers.utils import (
    safe_send, get_dashboard_url, unique_by_incident,
    CONFIRMED_INCIDENT_TYPES, KYIV_REGION_FILTER, logger
)
from database.models import SessionLocal, DetectedEvent
from worker.geo_extractors.vector_extractor import extract_threat_vector

router = Router()


@router.message(Command("radar"))
@router.message(Command("kontur"))
@router.message(F.text == "🛸 Радар Контур")
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
            line = f"• <b>[{t_str}]</b> {format_source_display(e.source_channel)}: {snippet}"

            # Deterministic vector estimate (bearing/ETA), NOT a Kalman
            # filter — only fires when the text names both an origin and a
            # destination. See worker/geo_extractors/vector_extractor.py.
            vector = extract_threat_vector(e.message_text)
            if vector:
                line += (
                    f"\n  ↳ 🧭 {vector.bearing_deg}° | {vector.weapon_label} ~{int(vector.speed_kmh)} км/год "
                    f"| ETA до {vector.destination_name}: ~{int(vector.eta_minutes)} хв"
                )
                if vector.next_landmark:
                    line += f" | далі ймовірно {vector.next_landmark} (~{int(vector.next_landmark_eta_minutes)} хв)"

            recent_radar_events.append(line)
    except Exception as ex:
        logger.error(f"Radar query error: {ex}")
    finally:
        db.close()
        
    radar_feed = "\n".join(recent_radar_events) if recent_radar_events else "<i>Наразі повітряний простір над столицею спокійний (активних повітряних цілей не зафіксовано).</i>"
    
    text = (
        "🛸 <b>РАДАРНЕ СПОСТЕРЕЖЕННЯ ТА ТРЕКІНГ ЦІЛЕЙ («КОНТУР»)</b>\n"
        "<i>Моніторинг польоту БПЛА Shahed-136, ракет та авіації у реальному часі.</i>\n\n"
        f"📡 <b>Свіжа радіолокаційна обстановка:</b>\n"
        f"{radar_feed}\n\n"
        "🗺️ <b>Оберіть тактичну мапу для перегляду:</b>"
    )
    
    inline_kb = InlineKeyboardBuilder()
    inline_kb.button(text="🛸 Відкрити Радар «Контур»", url="https://t.me/kontur_map_bot/app")
    inline_kb.button(text="🗺️ Наша Тактична GEOINT Мапа", url=get_dashboard_url())
    inline_kb.adjust(1, 1)
    
    await safe_send(message, text, reply_markup=inline_kb.as_markup(), disable_web_page_preview=True)


@router.message(Command("threats"))
@router.message(Command("forecast"))
@router.message(F.text == "🎯 Прогноз загроз")
async def cmd_threat_report(message: types.Message):
    txt = (message.text or "").strip().lower()
    is_en = " en" in txt or txt.endswith("/threats_en")
    prompt = ""
    if txt.startswith("/threats ") or txt.startswith("/forecast "):
        prompt = txt.split(maxsplit=1)[1].strip()

    wait_msg = (
        "⏳ <b>Querying database for verified events in the last 24 hours...</b>\n"
        "<i>• Scanning recorded incidents and air alerts\n"
        "• Calculating threat levels from confirmed data\n"
        "• Cross-referencing source verification status...</i>"
    ) if is_en else (
        "⏳ <b>Запитую базу даних щодо верифікованих подій за останні 24 години...</b>\n"
        "<i>• Перевірка зафіксованих інцидентів та повітряних тривог\n"
        "• Розрахунок рівнів загрози за підтвердженими фактами\n"
        "• Звірка статусів верифікації джерел...</i>"
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


@router.message(Command("top"))
@router.message(F.text == "🔥 ТОП подій")
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

        events = unique_by_incident(raw_events)

        if not events:
            await safe_send(
                message,
                "🔥 <b>НАЙВАЖЛИВІШІ ПОДІЇ (КИЇВ ТА ОБЛАСТЬ, 24 ГОДИНИ)</b>\n\n"
                "<i>Поки що немає даних для ТОПу зафіксованих інцидентів по Києву.</i>"
            )
            return

        lines = [
            "🔥 <b>НАЙВАЖЛИВІШІ ПОДІЇ ЗА 24 ГОДИНИ (КИЇВ ТА ОБЛАСТЬ)</b>\n"
            f"<i>Всього {len(raw_events)} повідомлень ➔ {len(events)} унікальних інцидентів після дедублікації</i>\n"
        ]
        for idx, e in enumerate(events[:10], 1):
            lines.append(format_human_event_card(idx, e, show_snippet=True))

        await safe_send(message, "\n".join(lines), disable_web_page_preview=True)
    finally:
        db.close()


@router.message(Command("resonance"))
@router.message(F.text == "💥 Резонанс")
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

        events = unique_by_incident(raw_events)

        if not events:
            await safe_send(
                message,
                "💥 <b>АКТИВНІСТЬ ЗА ОСТАННЮ 1 ГОДИНУ (КИЇВ ТА ОБЛАСТЬ)</b>\n\n"
                "<i>✅ За останні 60 хвилин нових підтверджених прильотів чи вибухів по Києву та області не зафіксовано (обстановка спокійна).</i>\n\n"
                "👉 Натисніть <b>🔥 ТОП подій</b> або <b>📋 Звіт (12 год)</b> для перегляду зведень за весь день."
            )
            return

        lines = ["💥 <b>АКТИВНІСТЬ ЗА ОСТАННЮ 1 ГОДИНУ (КИЇВ ТА ОБЛАСТЬ)</b>\n"]
        for idx, e in enumerate(events[:10], 1):
            lines.append(format_human_event_card(idx, e, show_snippet=True))

        lines.append("<i>⏱️ Стрічка відображає унікальні події за останні 60 хвилин.</i>")
        await safe_send(message, "\n".join(lines), disable_web_page_preview=True)
    finally:
        db.close()
