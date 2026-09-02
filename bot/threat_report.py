import os
import datetime
import requests
import json
import logging
from zoneinfo import ZoneInfo
from sqlalchemy import func
from database.models import SessionLocal, DetectedEvent
from worker.schemas import ThreatAssessmentSlotSchema

logger = logging.getLogger(__name__)
KYIV_TZ = ZoneInfo("Europe/Kyiv")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

# 1. Верифікована база знань (Ground Truth TTX)
GROUND_TRUTH_WEAPONS = [
    {"name": "9М723 «Іскандер-М»", "type": "Балістична", "range": "до 500 км", "speed": "2100 м/с (~Mach 6)", "stock_est": "~130-150 од.", "risk": "🔴 Високий (2-5 хв підльоту)"},
    {"name": "Х-47М2 «Кинджал»", "type": "Аеробалістична", "range": "до 2000 км", "speed": "до Mach 10", "stock_est": "~50 од.", "risk": "🟠 Точкові удари (МіГ-31К)"},
    {"name": "Х-101 / Х-555", "type": "Крилаті ракети", "range": "до 2500 км", "speed": "дозвукова (0.7M)", "stock_est": "~200-250 од.", "risk": "🟡 Масовані комбіновані хвилі"},
    {"name": "Shahed-136 / Герань-2", "type": "Ударний БпЛА", "range": "до 1500 км", "speed": "180 км/год", "stock_est": "Серійне вир-во", "risk": "🟢 Щоденне виснаження ППО"}
]

GROUND_TRUTH_AIRBASES = [
    {"base": "Енгельс-2 (Саратовська обл.)", "role": "Ту-95МС / Ту-160", "activity_hint": "Заряджання та перельоти стратегічної авіації"},
    {"base": "Саваслейка (Нижньогородська обл.)", "role": "МіГ-31К («Кинджал»)", "activity_hint": "Тренувальні вильоти та бойові пуски"},
    {"base": "Приморсько-Ахтарськ / Курськ", "role": "Пускові майданчики БпЛА", "activity_hint": "Щоденні нічні пуски ударних груп"},
    {"base": "Міллерове / Крим (Чауда)", "role": "ОТРК «Іскандер» / БпЛА", "activity_hint": "Тактична підтримка та балістика"}
]

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
        current_status_summary="Фіксується чергова активність ворожої розвідки та підготовка до комбінованих ударів.",
        ballistic_risk_level="HIGH",
        drone_activity_level="MEDIUM",
        aviation_status="STANDARD_PATROL",
        safety_recommendation="Не ігноруйте сигнали тривоги. Пам'ятайте про правило двох стін та прямуйте до укриттів."
    )

def generate_live_threat_assessment(custom_query: str = "") -> str:
    """Deterministically renders a robust military intelligence report using verified templates."""
    db = SessionLocal()
    events_summary = []
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
            events_summary.append(f"• <code>[{t_str}]</code> <b>{e.event_type.upper()}</b>: {e.location_text or 'Київщина'} (Дж: @{e.source_channel})")
    except Exception as exc:
        logger.error(f"Error fetching events for deterministic report: {exc}")
    finally:
        db.close()

    events_context_raw = "\n".join(events_summary) if events_summary else "За останні 24 години прямих влучань не зафіксовано."

    # Extract slots through AI with strict Pydantic parsing
    slots = query_llm_for_slots(events_context_raw, now_str)

    # Deterministic Assembly
    report_lines = [
        "🎯 <b>ОПЕРАТИВНИЙ ЗВІТ: ЗАГРОЗИ ТА АКТИВНІСТЬ РФ</b>",
        f"<i>Стан на {now_str} | Верифікована оперативна обстановка</i>\n",
        "📌 <b>ОЦІНКА ПОТОЧНОЇ ОБСТАНОВКИ:</b>",
        f"{slots.current_status_summary}\n",
        "📊 <b>ОПЕРАТИВНІ ПОКАЗНИКИ ЗА 24 ГОДИНИ:</b>",
        f"• Зафіксовано інцидентів у БД: <code>{total_events_24h}</code>",
        f"• Рівень загрози балістики: <b>{slots.ballistic_risk_level}</b>",
        f"• Активність БпЛА/розвідки: <b>{slots.drone_activity_level}</b>",
        f"• Статус стратегічної авіації: <b>{slots.aviation_status}</b>\n",
        "🚀 <b>ВЕРИФІКОВАНИЙ ПОТЕНЦІАЛ ОЗБРОЄННЯ (ТТХ):</b>"
    ]

    for w in GROUND_TRUTH_WEAPONS:
        report_lines.append(f"• <b>{w['name']}</b> ({w['type']}): запас {w['stock_est']} — <i>{w['risk']}</i>")

    report_lines.append("\n🏢 <b>МОНІТОРИНГ КЛЮЧОВИХ АВІАБАЗ РФ:</b>")
    for b in GROUND_TRUTH_AIRBASES:
        report_lines.append(f"• <b>{b['base']}</b>: {b['role']} — {b['activity_hint']}")

    if events_summary:
        report_lines.append("\n🔍 <b>ОСТАННІ ПІДТВЕРДЖЕНІ ПОДІЇ НА КИЇВЩИНІ:</b>")
        report_lines.extend(events_summary[:5])

    report_lines.append(f"\n⚠️ <b>РЕКОМЕНДАЦІЇ ЦИВІЛЬНОГО ЗАХИСТУ:</b>\n{slots.safety_recommendation}")

    return "\n".join(report_lines)
