import os
import datetime
import requests
import logging
from sqlalchemy import func
from database.models import SessionLocal, DetectedEvent

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Baseline strategic intelligence
STRATEGIC_KNOWLEDGE = """
КЛЮЧОВІ ОБ'ЄКТИ ТА АВІАБАЗИ РФ (БАЗА СПОСТЕРЕЖЕННЯ):
1. Енгельс-2 (Саратовська обл.): Ту-95МС, Ту-160 (носії Х-101/555) — рівень загрози ВИСОКИЙ при завантаженні ракет.
2. Оленья / Українка (Мурманська / Амурська обл.): Ту-95МС, Ту-22М3 (резерв, ротація та перельоти).
3. Саваслейка (Нижньогородська обл.): МіГ-31К (носії аеробалістичних ракет Х-47М2 «Кинджал»).
4. Гвардійське / Мис Чауда (Крим): пускові майданчики Shahed-136/Герань-2.
5. Міллерове (Ростовська обл.): пуски БПЛА, позиційні райони ОТРК «Іскандер-М».
6. Приморсько-Ахтарськ (Краснодарський край): щоденні пуски груп ударних БПЛА.
7. Капустин Яр / Плесецьк: ракетні полігони випробувань МБР / Орєшнік / РС-24.

ЗАПАСИ ТА ВИРОБНИЦТВО РАКЕТ РФ (ОЦІНКА):
- 9М723 «Іскандер-М»: ~130-150 од. угруповання (темп вир-ва ~60/міс) — основна балістична загроза.
- Х-47М2 «Кинджал»: ~50 од. (виробництво обмежене ~4-6/міс) — точкові удари.
- «Орєшнік» / IRBM: менше 20 од. (низькосерійне вир-во ~5-6 на рік).
- KN-23/KN-24: ~50 од. (імпорт із КНДР).
"""


from zoneinfo import ZoneInfo
KYIV_TZ = ZoneInfo("Europe/Kyiv")

def generate_live_threat_assessment(custom_query: str = "") -> str:
    """Performs real-time intelligence synthesis using current DB events and Groq LLM reasoning."""
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
            .limit(15)
            .all()
        )
        total_events_24h = len(recent_events)
        for e in recent_events:
            dt_val = e.detected_at.replace(tzinfo=datetime.timezone.utc) if e.detected_at.tzinfo is None else e.detected_at
            t_str = dt_val.astimezone(KYIV_TZ).strftime("%H:%M")
            events_summary.append(f"• [{t_str}] {e.event_type.upper()} у {e.location_text or 'невідомо'} (Джерело: @{e.source_channel}, Резонанс: {e.resonance_score}/100)")
    except Exception as exc:
        logger.error(f"Error fetching live events for threat analysis: {exc}")
    finally:
        db.close()

    events_context = "\n".join(events_summary) if events_summary else "За останні 12-24 години прямих ударів не зафіксовано (фаза перегрупування/розвідки)."

    # Use LLM to synthesize live analysis
    if GROQ_API_KEY:
        sys_prompt = (
            "Ти черговий офіцер військової розвідки та аналітик сил ППО. "
            "Сформуй АКТУАЛЬНИЙ ОПЕРАТИВНИЙ ЗВІТ ЩОДО ЗАГРОЗ ОБСТРІЛІВ НА ЦЕЙ МОМЕНТ для месенджера Telegram. "
            "НЕ ВИКОРИСТОВУЙ <html>, <body>, <head> теги! Тільки текст, емодзі, <b>, <i>, <code>.\n\n"
            f"Поточний точний час: {now_str}.\n"
            f"База знань розвідки:\n{STRATEGIC_KNOWLEDGE}\n\n"
            f"Свіжі інциденти з перевірених моніторингових джерел:\n{events_context}\n\n"
            "Структура звіту:\n"
            "🎯 <b>ОПЕРАТИВНИЙ ЗВІТ: ЗАГРОЗИ ТА АКТИВНІСТЬ РФ НА ЦЕЙ МОМЕНТ</b>\n"
            f"<i>Стан на {now_str} | Реальна оперативна обстановка</i>\n\n"
            "📌 <b>ОЦІНКА ПОТОЧНОЇ ОБСТАНОВКИ:</b>\n"
            "(Аналіз активності ворога на цей точний час, чи була недавня хвиля, чи триває підготовка до нових ударів)\n\n"
            "🚀 <b>БАЛІСТИЧНІ ТА АЕРОБАЛІСТИЧНІ ЗАГРОЗИ:</b>\n"
            "(Оцінка готовності Іскандер-М, Кинджал, Орєшнік, запаси та ризики)\n\n"
            "🏢 <b>АКТИВНІСТЬ КЛЮЧОВИХ АВІАБАЗ РФ (ТОП-ОБ'ЄКТИ):</b>\n"
            "(Енгельс-2, Саваслейка, Приморсько-Ахтарськ, Орел, Крим із рівнями загрози 🔴/🟡/🟢)\n\n"
            "⚡ <b>ПРОГНОЗ НА НАЙБЛИЖЧІ 12-24 ГОДИНИ:</b>\n"
            "(Ймовірні часові вікна наступних пусків, типи зброї та напрямки)\n\n"
            "⚠️ <b>РЕКОМЕНДАЦІЇ ЦИВІЛЬНОГО ЗАХИСТУ:</b>\n"
            "(Коротка порада безпеки при загрозі балістики)"
        )

        user_content = custom_query if custom_query else f"Проаналізуй обстановку та надай актуальний прогноз загроз станом на {now_str}."

        try:
            headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
            data = {
                "model": "openai/gpt-oss-120b",
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_content}
                ],
                "temperature": 0.2,
                "max_tokens": 1200
            }
            resp = requests.post(GROQ_URL, headers=headers, json=data, timeout=20)
            if resp.status_code == 200:
                raw_text = resp.json()["choices"][0]["message"]["content"].strip()
                # Clean any markdown html fence if any
                if raw_text.startswith("```html"):
                    raw_text = raw_text[7:]
                if raw_text.startswith("```"):
                    raw_text = raw_text[3:]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3]
                return raw_text.strip()
        except Exception as e:
            logger.error(f"Groq dynamic analysis error: {e}")

    # Fallback if LLM is unavailable
    risk_level = "🔴 КРИТИЧНИЙ" if total_events_24h >= 6 else "🟠 ПІДВИЩЕНИЙ" if total_events_24h >= 2 else "🟡 ПОМІРНИЙ"
    return (
        f"🎯 <b>ОПЕРАТИВНИЙ ЗВІТ: ЗАГРОЗИ ТА АКТИВНІСТЬ РФ</b>\n"
        f"<i>Стан на {now_str} | Аналіз поточної активності</i>\n\n"
        f"⚡ <b>Рівень загрози на цей момент:</b> <b>{risk_level}</b>\n"
        f"📊 <b>Зафіксовано подій за 24г:</b> <code>{total_events_24h}</code>\n\n"
        f"📌 <b>Оцінка обстановки:</b>\n"
        f"Фіксується чергування стратегічної авіації на аеродромах <b>Енгельс-2</b> (Ту-95МС/Ту-160) та <b>Саваслейка</b> (МіГ-31К). "
        f"Ймовірні пуски БПЛА Shahed-136 з Приморсько-Ахтарська та Курська у нічний час.\n\n"
        f"🚀 <b>Балістичний потенціал:</b>\n"
        f"• ОТРК «Іскандер-М»: ~130-150 од. (основна загроза)\n"
        f"• Х-47М2 «Кинджал»: ~50 од. на чергуванні\n"
        f"• «Орєшнік»: менше 20 од. (стратегічний тиск)\n\n"
        f"⚠️ <b>Пам'ятайте:</b> Час підльоту балістичної ракети — 2-5 хвилин. Не ігноруйте сигнали тривоги!"
    )
