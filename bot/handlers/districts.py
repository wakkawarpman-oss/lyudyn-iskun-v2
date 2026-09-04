import logging
from typing import Set, Dict, List
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder
from redis.asyncio import Redis

from bot.handlers.utils import safe_send

logger = logging.getLogger(__name__)
router = Router()

KYIV_DISTRICTS: Dict[str, Dict[str, str]] = {
    "shevchenko": {
        "name": "Шевченківський",
        "micro": "Татарка, Лук'янівка, Сирець, Шулявка, Нивки, КПІ"
    },
    "podil": {
        "name": "Подільський",
        "micro": "Поділ, Виноградар, Куренівка, Вітряні Гори, Воздвиженка, Татарка"
    },
    "obolon": {
        "name": "Оболонський",
        "micro": "Оболонь, Мінський масив, Пріорка, Пуща-Водиця"
    },
    "pechersk": {
        "name": "Печерський",
        "micro": "Печерськ, Липки, Звіринець, Видубичі, Чорна Гора"
    },
    "solomiansk": {
        "name": "Солом'янський",
        "micro": "Солом'янка, Чоколівка, Відрадний, Жуляни, Кардачі"
    },
    "holosiiv": {
        "name": "Голосіївський",
        "micro": "Голосієво, Теремки, Деміївка, Корчувате, Феофанія"
    },
    "sviatoshyn": {
        "name": "Святошинський",
        "micro": "Борщагівка, Академмістечко, Біличі, Новобіличі"
    },
    "darnytsia": {
        "name": "Дарницький",
        "micro": "Позняки, Осокорки, Харківський, Бортничі"
    },
    "dniprovsk": {
        "name": "Дніпровський",
        "micro": "Русанівка, Березняки, Воскресенка, Лівобережний, ДВРЗ"
    },
    "desniansk": {
        "name": "Деснянський",
        "micro": "Троєщина, Лісовий масив, Биківня"
    },
    "suburbs": {
        "name": "Передмістя",
        "micro": "Бровари, Буча, Ірпінь, Бориспіль, Вишгород"
    }
}

# Microdistrict to district morphological stem lookup
MICRODISTRICT_LOOKUP: Dict[str, List[str]] = {
    "татарк": ["shevchenko", "podil"],
    "лук'янів": ["shevchenko"],
    "лук’янів": ["shevchenko"],
    "сирець": ["shevchenko"],
    "сирц": ["shevchenko"],
    "шуляв": ["shevchenko"],
    "нивк": ["shevchenko"],
    "кпі": ["shevchenko", "solomiansk"],
    "політех": ["shevchenko", "solomiansk"],
    "кудряв": ["shevchenko"],
    "поділ": ["podil"],
    "виноградар": ["podil"],
    "куренів": ["podil"],
    "вітрян": ["podil"],
    "воздвижен": ["podil"],
    "пріорк": ["podil", "obolon"],
    "оболон": ["obolon"],
    "мінськ": ["obolon"],
    "пущ": ["obolon"],
    "печерськ": ["pechersk"],
    "липк": ["pechersk"],
    "звіринець": ["pechersk"],
    "звіринц": ["pechersk"],
    "видубич": ["pechersk"],
    "чорна гора": ["pechersk"],
    "солом'ян": ["solomiansk"],
    "солом’ян": ["solomiansk"],
    "чоколів": ["solomiansk"],
    "відрадн": ["solomiansk"],
    "жулян": ["solomiansk"],
    "кардач": ["solomiansk"],
    "караваєв": ["solomiansk"],
    "голосієв": ["holosiiv"],
    "голосіїв": ["holosiiv"],
    "теремк": ["holosiiv"],
    "деміїв": ["holosiiv"],
    "корчуват": ["holosiiv"],
    "феофані": ["holosiiv"],
    "пирогов": ["holosiiv"],
    "китаєв": ["holosiiv"],
    "борщагів": ["sviatoshyn"],
    "академмістеч": ["sviatoshyn"],
    "білич": ["sviatoshyn"],
    "новобілич": ["sviatoshyn"],
    "святошин": ["sviatoshyn"],
    "позняк": ["darnytsia"],
    "осокорк": ["darnytsia"],
    "харківськ": ["darnytsia"],
    "бортнич": ["darnytsia"],
    "червоний хутір": ["darnytsia"],
    "русанів": ["dniprovsk"],
    "березняк": ["dniprovsk"],
    "воскресен": ["dniprovsk"],
    "лівобереж": ["dniprovsk"],
    "дврз": ["dniprovsk"],
    "райдужн": ["dniprovsk"],
    "троєщин": ["desniansk"],
    "лісов": ["desniansk"],
    "биківн": ["desniansk"],
    "бровар": ["suburbs"],
    "буч": ["suburbs"],
    "ірпін": ["suburbs"],
    "бориспіл": ["suburbs"],
    "вишгород": ["suburbs"],
}

def resolve_target_districts(text: str) -> List[str]:
    """Resolves any mention of microdistricts (e.g. Татарка, Позняки) to parent district IDs."""
    text_lower = text.lower()
    districts = set()
    for micro_stem, d_ids in MICRODISTRICT_LOOKUP.items():
        if micro_stem in text_lower:
            districts.update(d_ids)
    return sorted(list(districts))

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
    for dist_id, info in KYIV_DISTRICTS.items():
        is_sel = dist_id in selected_districts
        icon = "✅" if is_sel else "▫️"
        name = info["name"]
        builder.button(text=f"{icon} {name}", callback_data=f"dist:toggle:{dist_id}")
    
    all_selected = len(selected_districts) >= len(KYIV_DISTRICTS)
    all_icon = "🔔 Всі обрані" if all_selected else "🔔 Обрати всі"
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
        "📍 <b>ПЕРСОНАЛЬНІ СПОВІЩЕННЯ ЗА РАЙОНАМИ ТА МІКРОРАЙОНАМИ КИЄВА</b>\n\n"
        "Оберіть ваші сектори. Бот надішле <b>миттєвий пріоритетний пуш</b>, якщо ворожий БпЛА, "
        "ракета або уламки прямуватимуть саме до вашого масиву.\n\n"
        "🗺 <b>Сектори та їхні масиви:</b>\n"
        "• 🏛 <b>Шевченківський:</b> <i>Татарка, Лук'янівка, Сирець, Шулявка, Нивки, КПІ</i>\n"
        "• ⛵ <b>Подільський:</b> <i>Поділ, Виноградар, Куренівка, Вітряні Гори, Воздвиженка, Татарка</i>\n"
        "• 🏢 <b>Оболонський:</b> <i>Оболонь, Мінський масив, Пріорка, Пуща-Водиця</i>\n"
        "• 👑 <b>Печерський:</b> <i>Печерськ, Липки, Звіринець, Видубичі, Чорна Гора</i>\n"
        "• ✈️ <b>Солом'янський:</b> <i>Солом'янка, Чоколівка, Відрадний, Жуляни, Кардачі</i>\n"
        "• 🌳 <b>Голосіївський:</b> <i>Голосієво, Теремки, Деміївка, Корчувате, Феофанія</i>\n"
        "• 🌲 <b>Святошинський:</b> <i>Борщагівка, Академмістечко, Біличі, Новобіличі</i>\n"
        "• 🏙 <b>Дарницький:</b> <i>Позняки, Осокорки, Харківський, Бортничі</i>\n"
        "• 🌊 <b>Дніпровський:</b> <i>Русанівка, Березняки, Воскресенка, Лівобережний, ДВРЗ</i>\n"
        "• 🗼 <b>Деснянський:</b> <i>Троєщина, Лісовий масив, Биківня</i>\n"
        "• 🛡 <b>Передмістя:</b> <i>Бровари, Буча, Ірпінь, Бориспіль, Вишгород</i>\n\n"
        "<i>Натискайте на кнопки нижче для перемикання (✅ — увімкнено):</i>"
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
        dist_info = KYIV_DISTRICTS.get(district_id, {"name": district_id})
        dist_name = dist_info["name"] if isinstance(dist_info, dict) else dist_info
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
        
        dist_info = KYIV_DISTRICTS.get(district_id, {"name": district_id})
        dist_name = dist_info["name"] if isinstance(dist_info, dict) else dist_info
        text = (
            f"🚨 <b>УВАГА: ЗАГРОЗА ДЛЯ ВАШОГО СЕКТОРУ ({dist_name.upper()})!</b>\n\n"
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
