"""
Human-in-the-Loop (HITL) Tactical Review & Feedback Handler.
Allows military OSINT analysts to confirm or reject contentious incidents directly in Telegram,
bidirectionally updating Beta-Bernoulli SourceReputation and calibrating the fusion pipeline.
"""
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder

import redis
from database.models import SessionLocal, DetectedEvent
from worker.grading import SourceReputation

logger = logging.getLogger(__name__)
router = Router()

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")


def _get_redis_client():
    try:
        return redis.Redis.from_url(REDIS_URL)
    except Exception as e:
        logger.warning(f"Redis connection error in HITL handler: {e}")
        return None


def get_source_reputation(ch: str, r_client=None) -> SourceReputation:
    """Loads source reputation from Redis or returns default prior."""
    r = r_client or _get_redis_client()
    if r:
        try:
            raw = r.get(f"source_rep:{ch}")
            if raw:
                data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
                return SourceReputation.from_dict(data)
        except Exception as e:
            logger.debug(f"Failed to load source rep: {e}")
    return SourceReputation(alpha=2.0, beta=2.0)


def save_source_reputation(ch: str, rep: SourceReputation, r_client=None):
    """Saves updated source reputation into Redis."""
    r = r_client or _get_redis_client()
    if r:
        try:
            r.set(f"source_rep:{ch}", json.dumps(rep.to_dict()), ex=86400 * 30)
        except Exception as e:
            logger.warning(f"Failed to save source rep: {e}")


def build_hitl_keyboard(event_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Підтвердити (Бойовий)", callback_data=f"hitl:confirm:{event_id}")
    builder.button(text="❌ Фейк / ІПСО", callback_data=f"hitl:fake:{event_id}")
    builder.button(text="🔇 Побутовий шум", callback_data=f"hitl:noise:{event_id}")
    builder.adjust(1, 2)
    return builder.as_markup()


@router.message(Command("hitl"))
@router.message(F.text == "🔍 HITL-Черга")
async def cmd_hitl_queue(message: types.Message):
    """Displays unconfirmed or contentious incidents awaiting analyst validation."""
    await message.answer("⏳ Завантажую оперативну чергу HITL-верифікації...")

    db = SessionLocal()
    try:
        threshold = datetime.utcnow() - timedelta(hours=48)
        pending_events = db.query(DetectedEvent).filter(
            DetectedEvent.detected_at >= threshold,
            DetectedEvent.verification_status.in_(["UNVERIFIED_SINGLE_SOURCE", "POSSIBLE_IPSO"]),
            DetectedEvent.confidence_score.between(25, 80)
        ).order_by(DetectedEvent.detected_at.desc()).limit(3).all()

        if not pending_events:
            await message.answer(
                "🟢 <b>Черга верифікації чиста!</b>\n\nВсі недавні інциденти мають достатній консенсус джерел або вже верифіковані.",
                parse_mode=ParseMode.HTML
            )
            return

        for ev in pending_events:
            ch_clean = str(ev.source_channel or "OSINT").lstrip("@")
            rep = get_source_reputation(ch_clean)
            rep_score = int(rep.reputation() * 100)

            text_card = (
                f"⚠️ <b>ПОТРІБНА ВЕРИФІКАЦІЯ АНАЛІТИКА</b> [#{ev.id}]\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📍 <b>Локація:</b> {ev.location_text or 'Київ та область'}\n"
                f"⚡ <b>Тип загрози:</b> {ev.event_type}\n"
                f"📡 <b>Джерело:</b> @{ch_clean} (C2 Довіра: {rep_score}%)\n"
                f"🎯 <b>Первинний скоринг:</b> Загроза: {ev.significance_score}/100 | Довіра: {ev.confidence_score}/100\n"
                f"📝 <b>Текст:</b> <i>{ev.message_text[:250] if ev.message_text else 'Немає опису'}</i>\n"
            )

            await message.answer(
                text_card,
                reply_markup=build_hitl_keyboard(ev.id),
                parse_mode=ParseMode.HTML
            )
    except Exception as e:
        logger.error(f"HITL queue error: {e}")
        await message.answer(f"❌ Помилка завантаження черги: {e}")
    finally:
        db.close()


@router.callback_query(F.data.startswith("hitl:"))
async def process_hitl_callback(callback: types.CallbackQuery):
    """Processes analyst decision button clicks, updates DB and recalibrates source reputation."""
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Некоректний формат команди", show_alert=True)
        return

    action = parts[1]
    event_id = int(parts[2])
    analyst_name = callback.from_user.username or callback.from_user.first_name or "Аналітик"

    db = SessionLocal()
    r = _get_redis_client()
    try:
        ev = db.query(DetectedEvent).filter(DetectedEvent.id == event_id).first()
        if not ev:
            await callback.answer("❌ Інцидент не знайдено в базі даних", show_alert=True)
            return

        ch_clean = str(ev.source_channel or "OSINT").lstrip("@")
        rep = get_source_reputation(ch_clean, r_client=r)
        old_score = int(rep.reputation() * 100)

        if action == "confirm":
            ev.verification_status = "CONFIRMED_ANALYST"
            ev.confidence_score = min(98, ev.confidence_score + 25)
            rep.update(confirmed=True)
            decision_title = "✅ <b>ВЕРИФІКОВАНО (Бойовий інцидент)</b>"
            decision_badge = "Підтверджено оператором"
        elif action == "fake":
            ev.verification_status = "REJECTED_ANALYST"
            ev.confidence_score = max(5, ev.confidence_score - 40)
            rep.update(confirmed=False)
            decision_title = "❌ <b>СПРОСТОВАНО (Дезінформація / Фейк)</b>"
            decision_badge = "Відхилено як недостовірне"
        elif action == "noise":
            ev.verification_status = "DISCARDED_NOISE"
            ev.event_type = "civilian_noise"
            rep.update(confirmed=False)
            decision_title = "🔇 <b>ПОЗНАЧЕНО ЯК ЦИВІЛЬНИЙ ШУМ</b>"
            decision_badge = "Вилучено з карти загроз"
        else:
            await callback.answer("Невідома дія", show_alert=True)
            return

        db.commit()
        save_source_reputation(ch_clean, rep, r_client=r)
        new_score = int(rep.reputation() * 100)

        updated_text = (
            f"{decision_title} [#{ev.id}]\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Аналітик:</b> @{analyst_name}\n"
            f"📍 <b>Локація:</b> {ev.location_text or 'Київ'}\n"
            f"📊 <b>Статус:</b> {decision_badge}\n"
            f"📡 <b>Репутація @{ch_clean}:</b> {old_score}% ➔ <b>{new_score}%</b> (α={rep.alpha:.1f}, β={rep.beta:.1f})\n"
        )

        await callback.message.edit_text(updated_text, parse_mode=ParseMode.HTML, reply_markup=None)
        await callback.answer(f"Рішення збережено! Репутація джерела оновлена: {new_score}%")
    except Exception as e:
        logger.error(f"Failed to process HITL feedback: {e}")
        await callback.answer(f"Помилка: {e}", show_alert=True)
    finally:
        db.close()
