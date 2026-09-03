import json
import logging
from typing import Set, Dict
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder
from redis.asyncio import Redis

from bot.handlers.utils import safe_send

logger = logging.getLogger(__name__)
router = Router()

KYIV_DISTRICTS: Dict[str, str] = {
    "obolon": "Оболонський",
    "podil": "Подільський",
    "shevchenko": "Шевченківський",
    "pechersk": "Печерський",
    "holosiiv": "Голосіївський",
    "solomiansk": "Солом'янський",
    "sviatoshyn": "Святошинський",
    "darnytsia": "Дарницький",
    "dniprovsk": "Дніпровський",
    "desniansk": "Деснянський",
    "suburbs": "Передмістя (Бровари/Ірпінь/Буча)",
}

def get_redis():
    import os
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    return Redis.from_url(redis_url, decode_responses=True)

async def get_user_districts(chat_id: int) -> Set[str]:
    r = get_redis()
    try:
        districts = await r.smembers(f"user:districts:{chat_id}")
        return set(districts) if districts else set()
    except Exception as e:
        logger.error(f"Error getting user districts: {e}")
        return set()
    finally:
        await r.aclose()

async def toggle_user_district(chat_id: int, district_id: str) -> Set[str]:
    r = get_redis()
    try:
        key = f"user:districts:{chat_id}"
        dist_key = f"district:users:{district_id}"
        is_member = await r.sismember(key, district_id)
        if is_member:
            await r.srem(key, district_id)
            await r.srem(dist_key, str(chat_id))
        else:
            await r.sadd(key, district_id)
            await r.sadd(dist_key, str(chat_id))
        updated = await r.smembers(key)
        return set(updated)
    except Exception as e:
        logger.error(f"Error toggling user district: {e}")
        return set()
    finally:
        await r.aclose()

async def toggle_all_districts(chat_id: int) -> Set[str]:
    r = get_redis()
    try:
        key = f"user:districts:{chat_id}"
        current = await r.smembers(key)
        if len(current) >= len(KYIV_DISTRICTS):
            # Already has all, toggle to none
            await r.delete(key)
            for d in KYIV_DISTRICTS:
                await r.srem(f"district:users:{d}", str(chat_id))
            return set()
        else:
            # Subscribe to all
            all_keys = list(KYIV_DISTRICTS.keys())
            await r.sadd(key, *all_keys)
            for d in all_keys:
                await r.sadd(f"district:users:{d}", str(chat_id))
            return set(all_keys)
    except Exception as e:
        logger.error(f"Error toggling all districts: {e}")
        return set()
    finally:
        await r.aclose()

def build_districts_keyboard(selected_districts: Set[str]):
    builder = InlineKeyboardBuilder()
    for dist_id, name in KYIV_DISTRICTS.items():
        is_sel = dist_id in selected_districts
        icon = "✅" if is_sel else "▫️"
        builder.button(text=f"{icon} {name}", callback_data=f"dist:toggle:{dist_id}")
    
    all_selected = len(selected_districts) >= len(KYIV_DISTRICTS)
    all_icon = "🔔 Всі вибрані" if all_selected else "🔔 Обрати всі"
    builder.button(text=all_icon, callback_data="dist:toggle:all")
    builder.adjust(2, 2, 2, 2, 2, 1, 1)
    return builder.as_markup()

@router.message(Command("districts"))
@router.message(Command("district"))
@router.message(F.text == "📍 Мій район")
@router.message(F.text == "📍 Мій район (Сповіщення)")
@router.message(F.text.ilike("%мій район%"))
async def cmd_districts(message: types.Message):
    selected = await get_user_districts(message.chat.id)
    text = (
        "📍 <b>ПЕРСОНАЛЬНІ СПОВІЩЕННЯ ЗА РАЙОНАМИ КИЄВА</b>\n\n"
        "Оберіть сектори вашого проживання чи роботи. Бот надішле <b>миттєвий пріоритетний пуш</b>, "
        "якщо ворожий БпЛА, ракета або уламки прямуватимуть саме у ваш район.\n\n"
        "<i>Натискайте на кнопки для вибору (✅ — увімкнено):</i>"
    )
    await safe_send(message, text, reply_markup=build_districts_keyboard(selected))

@router.callback_query(F.data.startswith("dist:toggle:"))
async def cb_toggle_district(callback: types.CallbackQuery):
    district_id = callback.data.replace("dist:toggle:", "")
    chat_id = callback.message.chat.id
    
    if district_id == "all":
        selected = await toggle_all_districts(chat_id)
        msg = "✅ Оновлено: підписка на всі райони Києва" if selected else "🛑 Підписку на райони скинуто"
        await callback.answer(msg, show_alert=False)
    else:
        selected = await toggle_user_district(chat_id, district_id)
        dist_name = KYIV_DISTRICTS.get(district_id, district_id)
        status_word = "увімкнено" if district_id in selected else "вимкнено"
        await callback.answer(f"{dist_name}: сповіщення {status_word}", show_alert=False)
    
    try:
        await callback.message.edit_reply_markup(reply_markup=build_districts_keyboard(selected))
    except Exception:
        pass

async def notify_district_subscribers(bot, district_id: str, threat_title: str, threat_desc: str):
    """Sends targeted alert to all users subscribed to a given district."""
    r = get_redis()
    try:
        users = await r.smembers(f"district:users:{district_id}")
        if not users:
            return
        
        dist_name = KYIV_DISTRICTS.get(district_id, district_id)
        text = (
            f"🚨 <b>УВАГА: ЗАГРОЗА ДЛЯ ВАШОГО РАЙОНУ ({dist_name.upper()})!</b>\n\n"
            f"⚠️ <b>Характер загрози:</b> {threat_title}\n"
            f"📍 <b>Деталі:</b> {threat_desc}\n\n"
            f"🛡️ <i>Негайно перейдіть в укриття або дотримуйтесь правила «двох стін»!</i>"
        )
        
        for user_id_str in users:
            try:
                await bot.send_message(int(user_id_str), text, parse_mode=ParseMode.HTML)
            except Exception as ex:
                logger.debug(f"Could not push to user {user_id_str}: {ex}")
    except Exception as e:
        logger.error(f"Error in notify_district_subscribers: {e}")
    finally:
        await r.aclose()
