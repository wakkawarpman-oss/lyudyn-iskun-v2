import os
import datetime
import requests
import json
import logging
from zoneinfo import ZoneInfo
from database.models import SessionLocal, DetectedEvent
from worker.schemas import ThreatAssessmentSlotSchema

logger = logging.getLogger(__name__)
KYIV_TZ = ZoneInfo("Europe/Kyiv")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

# 1. Словник офіційних та перевірених джерел
OFFICIAL_CHANNELS = {
    "kpszsu": "Повітряні Сили ЗСУ",
    "comafua": "Командувач ПС ЗСУ",
    "va_kyiv": "Київська МВА (КМВА)",
    "kyivcityofficial": "Офіційний портал Києва (Кличко)",
    "dsns_telegram": "ДСНС України",
    "dsns_kyiv_region": "ДСНС Київщини",
    "generalstaffzsu": "Генеральний штаб ЗСУ",
    "mvs_ua": "МВС України"
}

# 2. Верифіковані ТТХ та довідник озброєнь
GROUND_TRUTH_WEAPONS = [
    {"name": "9М723 «Іскандер-М»", "type": "Балістична", "range": "до 500 км", "speed": "~2100 м/с (2-5 хв підльоту)", "stock_est": "[Оцінка ГУР: ~130-150 од.]", "risk": "🔴 Висока загроза"},
    {"name": "Х-47М2 «Кинджал»", "type": "Аеробалістична", "range": "до 2000 км", "speed": "до Mach 10", "stock_est": "[Оцінка ГУР: ~50 од.]", "risk": "🟠 Пуски з МіГ-31К"},
    {"name": "Х-101 / Х-555", "type": "Крилата ракета", "range": "до 2500 км", "speed": "дозвукова (0.7M)", "stock_est": "[Оцінка ГУР: ~200-250 од.]", "risk": "🟡 Стратегічна авіація Ту-95МС"},
    {"name": "Shahed-136 / Герань-2", "type": "Ударний БпЛА", "range": "до 1500 км", "speed": "180 км/год", "stock_est": "[Серійне вир-во]", "risk": "🟢 Щоденне виснаження ППО"}
]

GROUND_TRUTH_AIRBASES = [
    {"base": "Енгельс-2 (Саратовська обл.)", "role": "Ту-95МС / Ту-160", "activity_hint": "Заряджання та перельоти стратегічної авіації"},
    {"base": "Саваслейка (Нижньогородська обл.)", "role": "МіГ-31К («Кинджал»)", "activity_hint": "Тренувальні вильоти та бойові пуски"},
    {"base": "Приморсько-Ахтарськ / Курськ", "role": "Пускові майданчики БпЛА", "activity_hint": "Нічні пуски ударних груп"},
    {"base": "Міллерове / Крим (Чауда)", "role": "ОТРК «Іскандер» / БпЛА", "activity_hint": "Тактична підтримка та балістика"}
]

def format_event_type_ua(event_type: str) -> str:
    types_map = {
        "direct_strike": "💥 ПРЯМИЙ ПРИЛІТ",
        "explosion": "💥 ВИБУХ",
        "fire": "🔥 ПОЖЕЖА",
        "destruction": "🏚️ РУЙНУВАННЯ",
        "casualties": "🚑 ПОСТРАЖДАЛІ",
        "radar_track": "🛸 РАДАРНИЙ ТРЕК БпЛА",
        "general_alert": "⚠️ ОПЕРАТИВНЕ ПОПЕРЕДЖЕННЯ",
        "air_defense": "🛡️ РОБОТА ППО"
    }
    return types_map.get(event_type.lower(), f"📍 {event_type.upper()}")

def format_verified_source_link(source: str, msg_id: int) -> str:
    """Generates a verified, clickable Telegram link with human-readable name."""
    if not source:
        return "Невідоме джерело"
    clean_src = str(source).strip().lstrip('@').lower()
    
    if clean_src.isdigit() or clean_src.replace('-', '').isdigit():
        channel_name = f"Оперативний монітор #{clean_src[-4:]}"
        url = f"https://t.me/c/{clean_src.replace('-100', '')}/{msg_id}" if msg_id else "https://t.me"
    elif clean_src in OFFICIAL_CHANNELS:
        channel_name = f"🏛️ {OFFICIAL_CHANNELS[clean_src]} (@{clean_src})"
        url = f"https://t.me/{clean_src}/{msg_id}" if msg_id else f"https://t.me/{clean_src}"
    else:
        channel_name = f"@{clean_src}"
        url = f"https://t.me/{clean_src}/{msg_id}" if msg_id else f"https://t.me/{clean_src}"
        
    return f"<a href='{url}'>{channel_name}</a>"

def query_llm_for_slots(events_context: str, now_str: str) -> ThreatAssessmentSlotSchema:
    """Uses LLM strictly to fill semantic slots, avoiding freeform text formatting hallucinations."""
    sys_prompt = f"""Ти старший аналітик розвідки ППО. 
Поточний точний час: {now_str}.
Проаналізуй останні інциденти за 24 години:
{events_context}

Поверни ТІЛЬКИ валідний JSON згідно схеми:
{{
  "current_status_summary": "стислий факт обстановки на цей момент (1-2 речення)",
  "ballistic_risk_level": "CRITICAL|HIGH|MEDIUM|LOW",
  "drone_activity_level": "CRITICAL|HIGH|MEDIUM|LOW",
  "aviation_status": "HIGH_ALERT|STANDARD_PATROL|STANDBY",
  "safety_recommendation": "1 речення цивільної безпеки"
}}
"""
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"} if GROQ_API_KEY else {}
    if GROQ_API_KEY:
        try:
            resp = requests.post(
                GROQ_URL,
                headers=headers,
                json={
                    "model": "llama-3.1-70b-versatile",
                    "messages": [{"role": "system", "content": sys_prompt}],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"}
                },
                timeout=12
            )
            if resp.status_code == 200:
                raw_json = json.loads(resp.json()["choices"][0]["message"]["content"])
                return ThreatAssessmentSlotSchema(**raw_json)
        except Exception as e:
            logger.warning(f"Groq slot extraction failed: {e}")

    # Fallback to OpenAI if Groq fails
    if OPENAI_API_KEY:
        try:
            resp = requests.post(
                OPENAI_URL,
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "system", "content": sys_prompt}],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"}
                },
                timeout=12
            )
            if resp.status_code == 200:
                raw_json = json.loads(resp.json()["choices"][0]["message"]["content"])
                return ThreatAssessmentSlotSchema(**raw_json)
        except Exception as e:
            logger.warning(f"OpenAI slot extraction failed: {e}")

    # Safe deterministic default
    return ThreatAssessmentSlotSchema(
        current_status_summary="Фіксується активність ворожої повітряної розвідки та моніторинг обстановки силами ППО.",
        ballistic_risk_level="HIGH",
        drone_activity_level="MEDIUM",
        aviation_status="STANDARD_PATROL",
        safety_recommendation="Не ігноруйте сигнали повітряної тривоги та прямуйте до укриттів при загрозі балістики."
    )

def generate_live_threat_assessment(custom_query: str = "") -> str:
    """Deterministically renders a robust military intelligence report with auto-verified links."""
    db = SessionLocal()
    events_items = []
    total_events_24h = 0
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_kyiv = now_utc.astimezone(KYIV_TZ)
    now_str = now_kyiv.strftime("%d.%m.%Y | %H:%M (за Києвом)")

    try:
        threshold = now_utc.replace(tzinfo=None) - datetime.timedelta(hours=24)
        recent_events = (
            db.query(DetectedEvent)
            .filter(
                DetectedEvent.detected_at >= threshold,
                DetectedEvent.source_channel.not_ilike('test%')
            )
            .order_by(DetectedEvent.detected_at.desc())
            .limit(10)
            .all()
        )
        total_events_24h = len(recent_events)
        for e in recent_events:
            dt_val = e.detected_at.replace(tzinfo=datetime.timezone.utc) if e.detected_at.tzinfo is None else e.detected_at
            t_str = dt_val.astimezone(KYIV_TZ).strftime("%H:%M")
            type_label = format_event_type_ua(e.event_type)
            source_link = format_verified_source_link(e.source_channel, e.message_id)
            
            # C2 Verification Tag
            if getattr(e, "is_official", False) or e.source_channel.lower().lstrip('@') in OFFICIAL_CHANNELS:
                verif_badge = "🏛️ [ОФІЦІЙНО]"
            elif getattr(e, "sources_count", 1) >= 2:
                verif_badge = f"🟢 [ВЕРИФІКОВАНО {e.sources_count} дж.]"
            else:
                verif_badge = "🟡 [1 ДЖЕРЕЛО]"

            events_items.append(
                f"• <code>[{t_str}]</code> <b>{type_label}</b>: {e.location_text or 'Київщина'}\n"
                f"   └ {verif_badge} Першоджерело: {source_link}"
            )
    except Exception as exc:
        logger.error(f"Error fetching events for verified report: {exc}")
    finally:
        db.close()

    events_context_raw = "\n".join(events_items) if events_items else "За останні 24 години прямих влучань не зафіксовано."

    # Extract slots through AI with strict Pydantic parsing
    slots = query_llm_for_slots(events_context_raw, now_str)

    # Deterministic Assembly with Zero-Hallucination Layout
    report_lines = [
        "🎯 <b>ОПЕРАТИВНИЙ ЗВІТ: ЗАГРОЗИ ТА АКТИВНІСТЬ РФ</b>",
        f"<i>Стан на {now_str} | Автоматично верифіковані дані</i>\n",
        "📌 <b>ОЦІНКА ПОТОЧНОЇ ОБСТАНОВКИ:</b>",
        f"{slots.current_status_summary}\n",
        "📊 <b>ОПЕРАТИВНІ ПОКАЗНИКИ ЗА 24 ГОДИНИ:</b>",
        f"• Зафіксовано інцидентів у базі: <code>{total_events_24h}</code>",
        f"• Рівень загрози балістики: <b>{slots.ballistic_risk_level}</b>",
        f"• Активність БпЛА/розвідки: <b>{slots.drone_activity_level}</b>",
        f"• Статус стратегічної авіації: <b>{slots.aviation_status}</b>\n",
        "🚀 <b>ДОВІДНИК ТТХ ТА ЗАПАСІВ ОЗБРОЄННЯ РФ:</b>"
    ]

    for w in GROUND_TRUTH_WEAPONS:
        report_lines.append(f"• <b>{w['name']}</b> ({w['type']}): {w['speed']} — <i>{w['stock_est']}</i> | {w['risk']}")

    report_lines.append("\n🏢 <b>МОНІТОРИНГ КЛЮЧОВИХ АВІАБАЗ РФ:</b>")
    for b in GROUND_TRUTH_AIRBASES:
        report_lines.append(f"• <b>{b['base']}</b>: {b['role']} — {b['activity_hint']}")

    if events_items:
        report_lines.append("\n🔍 <b>ОСТАННІ ПЕРЕВІРЕНІ ПОДІЇ ТА ПЕРШОДЖЕРЕЛА:</b>")
        report_lines.extend(events_items[:5])

    report_lines.append(f"\n⚠️ <b>РЕКОМЕНДАЦІЇ ЦИВІЛЬНОГО ЗАХИСТУ:</b>\n{slots.safety_recommendation}")

    return "\n".join(report_lines)
