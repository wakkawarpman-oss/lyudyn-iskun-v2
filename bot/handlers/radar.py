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
            .limit(10)
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
    
    # Live Neptun radar targets telemetry
    live_section = ""
    try:
        from worker.osint.neptun_radar import get_live_radar_threats
        loop = asyncio.get_event_loop()
        radar_data = await loop.run_in_executor(None, get_live_radar_threats)
        if radar_data and radar_data.get("count", 0) > 0:
            drones = radar_data.get("drones", [])
            kyiv_targets = [d for d in drones if d.get("is_kyiv_threat")]
            ballistic = radar_data.get("ballistic_threat")
            
            lines = [f"🛰️ <b>ЖИВИЙ РАДАР (ЦІЛЕЙ В НЕБІ УКРАЇНИ: {len(drones)})</b>"]
            if ballistic:
                lines.append("⚠️ <b>УВАГА: ЗАФІКСОВАНО БАЛІСТИЧНУ ЗАГРОЗУ!</b>")
            
            if kyiv_targets:
                lines.append("🎯 <b>Цілі у зоні Київського регіону (&lt;180 км):</b>")
                for d in kyiv_targets[:4]:
                    dist = d.get("distance_to_kyiv_km")
                    label = d.get("label")
                    place = d.get("place") or d.get("region") or "Невідомо"
                    speed = int(d.get("speed_kmh") or 0)
                    speed_str = f" | {speed} км/год" if speed > 0 else ""
                    lines.append(f"  • <b>{label}</b>: ~{dist} км ({place}{speed_str})")
            else:
                closest = drones[0]
                lines.append(f"🟢 <i>Прямої загрози Києву немає. Найближча ціль: {closest.get('label')} (~{closest.get('distance_to_kyiv_km')} км, {closest.get('place') or closest.get('region')})</i>")
            
            live_section = "\n".join(lines) + "\n\n"
    except Exception as re:
        logger.warning(f"Neptun radar in bot warning: {re}")

    text = (
        "🛸 <b>РАДАРНЕ СПОСТЕРЕЖЕННЯ ТА ТРЕКІНГ ЦІЛЕЙ («КОНТУР»)</b>\n"
        "<i>Моніторинг польоту БПЛА Shahed-136, ракет та авіації у реальному часі.</i>\n\n"
        f"{live_section}"
        f"📡 <b>Останні зафіксовані повідомлення моніторингу:</b>\n"
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


@router.message(Command("thermal"))
@router.message(Command("firms"))
@router.message(F.text == "🔥 Супутник NASA")
@router.message(F.text.ilike("%супутник%"))
@router.message(F.text.ilike("%термо%"))
async def cmd_thermal_satellite(message: types.Message):
    from worker.osint.firms_viirs import fetch_ukraine_thermal_anomalies
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, fetch_ukraine_thermal_anomalies)
    anomalies = data.get("anomalies", [])
    total_count = len(anomalies)

    high_frp = [a for a in anomalies if (a.get("frp_mw") or 0) >= 15.0]
    high_frp_sorted = sorted(high_frp, key=lambda x: x.get("frp_mw", 0), reverse=True)[:5]

    lines = [
        "🛰️ <b>СУПУТНИКОВИЙ МОНІТОРИНГ ТЕРМО-АНОМАЛІЙ (NASA FIRMS)</b>",
        "<i>Орбітальний радіометр Suomi-NPP VIIRS (375м) у режимі реального часу.</i>\n",
        f"🔥 <b>Зафіксовано теплових спалахів по Україні (24г):</b> <code>{total_count:,}</code>",
        f"⚡ <b>Потужних осередків горіння / вибухів (&gt;15 МВт):</b> <code>{len(high_frp)}</code>\n"
    ]

    if high_frp_sorted:
        lines.append("🔴 <b>Найбільш інтенсивні теплові аномалії:</b>")
        for idx, a in enumerate(high_frp_sorted, 1):
            frp = a.get("frp_mw")
            temp_c = int((a.get("brightness_k") or 300) - 273.15)
            dt_raw = a.get("acq_time", "")
            t_str = dt_raw[11:16] if "T" in dt_raw else ""
            t_disp = f" (фіксація {t_str} UTC)" if t_str else ""
            lines.append(f"  {idx}. <code>{a.get('lat'):.3f}, {a.get('lon'):.3f}</code> — <b>{frp} МВт</b> (~{temp_c}°C){t_disp}")
        lines.append("")

    lines.append("🗺️ <i>Перегляньте всі осередки з динамічним радіусом на інтерактивній веб-мапі:</i>")

    inline_kb = InlineKeyboardBuilder()
    inline_kb.button(text="🔥 Відкрити шар NASA на мапі", url=get_dashboard_url())
    inline_kb.adjust(1)

    await safe_send(message, "\n".join(lines), reply_markup=inline_kb.as_markup(), disable_web_page_preview=True)


@router.message(Command("top"))
@router.message(F.text == "🎖 Ключові інциденти")
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
            .order_by(DetectedEvent.detected_at.desc(), DetectedEvent.resonance_score.desc())
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
                "👉 Натисніть <b>🎖 Ключові інциденти</b> або <b>📋 Звіт (12 год)</b> для перегляду зведень за весь день."
            )
            return

        lines = ["💥 <b>АКТИВНІСТЬ ЗА ОСТАННЮ 1 ГОДИНУ (КИЇВ ТА ОБЛАСТЬ)</b>\n"]
        for idx, e in enumerate(events[:10], 1):
            lines.append(format_human_event_card(idx, e, show_snippet=True))

        lines.append("<i>⏱️ Стрічка відображає унікальні події за останні 60 хвилин.</i>")
        await safe_send(message, "\n".join(lines), disable_web_page_preview=True)
    finally:
        db.close()
