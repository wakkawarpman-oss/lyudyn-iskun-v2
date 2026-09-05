import logging
from typing import Set, Dict, List, Optional
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder
from redis.asyncio import Redis

from bot.handlers.utils import safe_send
from bot.districts_registry import (
    CITIES_REGISTRY,
    DISTRICTS_REGISTRY,
    FLAT_DISTRICTS,
    MICRODISTRICT_LOOKUP,
    resolve_target_districts,
    normalize_district_key,
    get_district_info,
    get_city_for_district,
    get_district_display_name
)

logger = logging.getLogger(__name__)
router = Router()

# Backward compatibility alias for legacy tests and imports
KYIV_DISTRICTS = {
    k.split(":")[-1]: {"name": v["name"], "micro": v["micro"]}
    for k, v in DISTRICTS_REGISTRY["kyiv"].items()
}


def get_redis():
    import os
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    return Redis.from_url(redis_url, decode_responses=True)


async def get_user_districts(chat_id: int) -> Set[str]:
    """Retrieves user subscriptions with automatic migration of legacy un-prefixed keys."""
    r = get_redis()
    try:
        raw_districts = await r.smembers(f"user:districts:{chat_id}")
        if not raw_districts:
            return set()
        
        normalized: Set[str] = set()
        needs_migration = False
        for d in raw_districts:
            norm_k = normalize_district_key(d)
            normalized.add(norm_k)
            if norm_k != d:
                needs_migration = True
        
        # Auto-migrate legacy keys in Redis if needed
        if needs_migration:
            key = f"user:districts:{chat_id}"
            await r.delete(key)
            if normalized:
                await r.sadd(key, *list(normalized))
        
        return normalized
    except Exception as e:
        logger.error(f"Error getting user districts: {e}")
        return set()
    finally:
        await r.aclose()


async def toggle_user_district(chat_id: int, district_id: str) -> Set[str]:
    """Toggles a single district subscription for user in Redis."""
    district_key = normalize_district_key(district_id)
    r = get_redis()
    try:
        key = f"user:districts:{chat_id}"
        dist_key = f"district:users:{district_key}"
        is_member = await r.sismember(key, district_key)
        if is_member:
            await r.srem(key, district_key)
            await r.srem(dist_key, str(chat_id))
        else:
            await r.sadd(key, district_key)
            await r.sadd(dist_key, str(chat_id))
        
        updated = await r.smembers(key)
        return {normalize_district_key(d) for d in updated}
    except Exception as e:
        logger.error(f"Error toggling user district: {e}")
        return set()
    finally:
        await r.aclose()


async def toggle_all_city_districts(chat_id: int, city_id: str) -> Set[str]:
    """Toggles all districts of a specific city for the user."""
    city_districts = list(DISTRICTS_REGISTRY.get(city_id, {}).keys())
    if not city_districts:
        return await get_user_districts(chat_id)

    r = get_redis()
    try:
        key = f"user:districts:{chat_id}"
        current = {normalize_district_key(d) for d in await r.smembers(key)}
        city_selected = [d for d in city_districts if d in current]

        if len(city_selected) >= len(city_districts):
            # All selected in this city -> unsubscribe from this city
            for d in city_districts:
                await r.srem(key, d)
                await r.srem(f"district:users:{d}", str(chat_id))
        else:
            # Subscribe to all in this city
            await r.sadd(key, *city_districts)
            for d in city_districts:
                await r.sadd(f"district:users:{d}", str(chat_id))

        updated = await r.smembers(key)
        return {normalize_district_key(d) for d in updated}
    except Exception as e:
        logger.error(f"Error toggling city districts for {city_id}: {e}")
        return set()
    finally:
        await r.aclose()


async def toggle_all_districts(chat_id: int) -> Set[str]:
    """Legacy toggle all (defaults to Kyiv for backward compatibility with tests)."""
    return await toggle_all_city_districts(chat_id, "kyiv")


# ─── KEYBOARD BUILDERS ───

def build_cities_keyboard(selected_districts: Set[str]):
    """Builds Tier-1 City Selection Inline Keyboard with subscription counters."""
    builder = InlineKeyboardBuilder()

    # Pre-count active subscriptions per city
    city_counts: Dict[str, int] = {c: 0 for c in CITIES_REGISTRY}
    for d in selected_districts:
        cid = get_city_for_district(d)
        if cid in city_counts:
            city_counts[cid] += 1

    for cid, cinfo in CITIES_REGISTRY.items():
        count = city_counts.get(cid, 0)
        badge = f" ({count})" if count > 0 else ""
        icon = "✅ " if count > 0 else ""
        btn_text = f"{icon}{cinfo['icon']} {cinfo['name']}{badge}"
        builder.button(text=btn_text, callback_data=f"dist:city:{cid}")

    # Layout: 2 buttons per row, last single
    builder.adjust(2, 2, 2, 2, 1)

    # Global clear button if any subscriptions exist
    if selected_districts:
        builder.button(text="🛑 Скинути всі підписки", callback_data="dist:clear_all")
        builder.adjust(2, 2, 2, 2, 1, 1)

    return builder.as_markup()


def build_city_districts_keyboard(city_id: str, selected_districts: Set[str]):
    """Builds Tier-2 District Selection Keyboard for a specific city."""
    builder = InlineKeyboardBuilder()
    city_dists = DISTRICTS_REGISTRY.get(city_id, {})

    for dist_key, info in city_dists.items():
        is_sel = dist_key in selected_districts
        icon = "✅" if is_sel else "▫️"
        name = info["name"]
        builder.button(text=f"{icon} {name}", callback_data=f"dist:toggle:{dist_key}")

    # Count how many selected in this city
    all_count = len(city_dists)
    sel_count = sum(1 for d in city_dists if d in selected_districts)
    all_selected = (sel_count >= all_count) and all_count > 0

    toggle_all_icon = "🔔 Всі обрані" if all_selected else "🔔 Обрати всі"
    builder.button(text=toggle_all_icon, callback_data=f"dist:toggle_all:{city_id}")
    builder.button(text="🔙 До вибору міст", callback_data="dist:menu:cities")

    # Grid layout: pairs of districts, then toggle all, then back
    rows = [2] * (len(city_dists) // 2)
    if len(city_dists) % 2 != 0:
        rows.append(1)
    rows.extend([1, 1])
    builder.adjust(*rows)
    return builder.as_markup()


def build_districts_keyboard(selected_districts: Set[str]):
    """Backward compatibility keyboard renderer (defaults to Kyiv)."""
    # Normalize selected set to canonical keys
    norm_selected = {normalize_district_key(d) for d in selected_districts}
    return build_city_districts_keyboard("kyiv", norm_selected)


# ─── COMMAND HANDLERS ───

@router.message(Command("districts"))
@router.message(Command("district"))
@router.message(F.text == "📍 Мій район")
@router.message(F.text == "📍 Мій район (Сповіщення)")
@router.message(F.text.ilike("%мій район%"))
async def cmd_districts(message: types.Message):
    """Entrypoint for localized district early warning across 9 Ukrainian cities."""
    selected = await get_user_districts(message.chat.id)
    total_active = len(selected)

    text = (
        "📍 <b>ПЕРСОНАЛЬНІ СПОВІЩЕННЯ ЗА СЕКТОРАМИ ТА РАЙОНАМИ МІСТ УКРАЇНИ</b>\n\n"
        "Оберіть ваше місто та сектори спостереження. Система OKINT-PRO надішле "
        "<b>миттєвий пріоритетний пуш</b>, якщо ворожий БпЛА Shahed, ракета або небезпечні уламки "
        "прямуватимуть саме до вашого району чи масиву.\n\n"
        "🗺️ <b>Підтримувані оперативні центри:</b>\n"
        "• 🏛️ <b>Київ</b> — 10 адміністративних районів та передмістя\n"
        "• 🌊 <b>Дніпро</b> — 8 районів (Південмаш, Придніпровськ, мости)\n"
        "• ⚡ <b>Запоріжжя</b> — 7 районів (ДніпроГЕС, Мотор Січ, Промзона)\n"
        "• 🛡️ <b>Харків</b> — 9 районів (Салтівка, ХТЗ, Павлове Поле)\n"
        "• 🏰 <b>Львів</b> — 6 районів (Сихів, Рясне, ЛДАРЗ, Стрий)\n"
        "• ⚓ <b>Миколаїв</b> — 4 райони (Варварівка, Інгульський міст, порти)\n"
        "• 🌲 <b>Суми</b> — 2 райони (Сумихімпром, Баси, Курська)\n"
        "• ⛵ <b>Одеса</b> — 4 райони (Пересипський/Поскот, Хаджибейський/Черемушки, Приморський, Київський/Таїрова) та порти\n"
        "• 🌾 <b>Полтава</b> — 3 райони (179-й НЦ зв'язку, Левада, Половки)\n\n"
        f"📊 <i>Зараз активно підписок:</i> <b>{total_active}</b> секторів.\n"
        "<i>Натисніть на потрібне місто нижче, щоб налаштувати райони:</i>"
    )
    await safe_send(message, text, reply_markup=build_cities_keyboard(selected))


# ─── CALLBACK HANDLERS ───

@router.callback_query(F.data == "dist:menu:cities")
async def cb_menu_cities(callback: types.CallbackQuery):
    """Navigates back to the Tier-1 Cities Selection Menu."""
    selected = await get_user_districts(callback.message.chat.id)
    text = (
        "📍 <b>ОБЕРІТЬ МІСТО ДЛЯ НАЛАШТУВАННЯ СПОВІЩЕНЬ:</b>\n\n"
        "Оберіть необхідне місто, щоб увімкнути або вимкнути сповіщення за окремими мікрорайонами.\n"
        f"📊 <i>Всього обрано секторів:</i> <b>{len(selected)}</b>"
    )
    try:
        await callback.message.edit_text(text, reply_markup=build_cities_keyboard(selected), parse_mode=ParseMode.HTML)
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("dist:city:"))
async def cb_select_city(callback: types.CallbackQuery):
    """Navigates into Tier-2 District Selection Menu for the given city."""
    city_id = callback.data.replace("dist:city:", "")
    city_info = CITIES_REGISTRY.get(city_id)
    if not city_info:
        await callback.answer("Місто не знайдено", show_alert=False)
        return

    selected = await get_user_districts(callback.message.chat.id)
    city_dists = DISTRICTS_REGISTRY.get(city_id, {})

    lines = [
        f"{city_info['icon']} <b>СЕКТОРИ ТА РАЙОНИ МІСТА {city_info['name'].upper()}</b>\n",
        f"⚠️ <i>Профіль загрози:</i> {city_info.get('threat_profile', '')}\n",
        "🗺️ <b>Опис секторів та мікрорайонів:</b>"
    ]

    for d_key, d_meta in city_dists.items():
        name = d_meta["name"]
        legacy_str = f" (кол. {d_meta['legacy']})" if "legacy" in d_meta else ""
        micro_str = f": <i>{d_meta.get('micro', '')}</i>" if d_meta.get("micro") else ""
        lines.append(f"• <b>{name}{legacy_str}</b>{micro_str}")

    lines.append("\n<i>Натискайте на кнопки нижче для перемикання (✅ — увімкнено):</i>")
    text = "\n".join(lines)

    try:
        await callback.message.edit_text(
            text,
            reply_markup=build_city_districts_keyboard(city_id, selected),
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("dist:toggle:"))
async def cb_toggle_district(callback: types.CallbackQuery):
    """Toggles a single district and updates the current city keyboard."""
    district_param = callback.data.replace("dist:toggle:", "")
    district_key = normalize_district_key(district_param)
    chat_id = callback.message.chat.id

    if district_param == "all":
        # Legacy callback support
        selected = await toggle_all_city_districts(chat_id, "kyiv")
        await callback.answer("Оновлено підписку на Київ", show_alert=False)
        try:
            await callback.message.edit_reply_markup(reply_markup=build_city_districts_keyboard("kyiv", selected))
        except Exception:
            pass
        return

    selected = await toggle_user_district(chat_id, district_key)
    dist_info = get_district_info(district_key)
    city_id = dist_info.get("city_id", "kyiv")
    dist_name = dist_info.get("name", district_key)
    status_word = "увімкнено" if district_key in selected else "вимкнено"

    await callback.answer(f"{dist_name}: сповіщення {status_word}", show_alert=False)
    try:
        await callback.message.edit_reply_markup(
            reply_markup=build_city_districts_keyboard(city_id, selected)
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("dist:toggle_all:"))
async def cb_toggle_all_city(callback: types.CallbackQuery):
    """Toggles all districts in a specified city."""
    city_id = callback.data.replace("dist:toggle_all:", "")
    chat_id = callback.message.chat.id
    selected = await toggle_all_city_districts(chat_id, city_id)

    city_info = CITIES_REGISTRY.get(city_id, {"name": city_id})
    city_dists = DISTRICTS_REGISTRY.get(city_id, {})
    has_any = any(d in selected for d in city_dists)
    msg = f"✅ Підписка на всі райони ({city_info['name']})" if has_any else f"🛑 Райони {city_info['name']} вимкнено"

    await callback.answer(msg, show_alert=False)
    try:
        await callback.message.edit_reply_markup(
            reply_markup=build_city_districts_keyboard(city_id, selected)
        )
    except Exception:
        pass


@router.callback_query(F.data == "dist:clear_all")
async def cb_clear_all_districts(callback: types.CallbackQuery):
    """Unsubscribes user from all districts across all cities."""
    chat_id = callback.message.chat.id
    r = get_redis()
    try:
        key = f"user:districts:{chat_id}"
        current = await r.smembers(key)
        for d in current:
            await r.srem(f"district:users:{d}", str(chat_id))
        await r.delete(key)
    except Exception as e:
        logger.error(f"Error clearing all districts: {e}")
    finally:
        await r.aclose()

    await callback.answer("🛑 Всі підписки на райони скасовано", show_alert=False)
    try:
        await callback.message.edit_text(
            "🛑 <b>Всі підписки на райони успішно скинуто.</b>\n\n"
            "Ви можете обрати нові міста та сектори для спостереження:",
            reply_markup=build_cities_keyboard(set()),
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass


# ─── PUSH NOTIFICATION ENGINE ───

async def notify_district_subscribers(bot, district_id: str, threat_title: str, threat_desc: str):
    """Sends targeted alert to all users subscribed to a given district across all 9 cities."""
    district_key = normalize_district_key(district_id)
    r = get_redis()
    try:
        # Collect subscribers from both canonical key and legacy key (if applicable)
        users = set(await r.smembers(f"district:users:{district_key}"))
        legacy_key = district_key.split(":")[-1]
        if legacy_key != district_key:
            legacy_users = await r.smembers(f"district:users:{legacy_key}")
            if legacy_users:
                users.update(legacy_users)

        if not users:
            return

        dist_info = get_district_info(district_key)
        dist_name = dist_info.get("name", district_id)
        city_id = dist_info.get("city_id", "kyiv")
        city_meta = CITIES_REGISTRY.get(city_id, {"name": city_id.title(), "icon": "📍"})

        text = (
            f"🚨 <b>УВАГА: ЗАГРОЗА ДЛЯ ВАШОГО СЕКТОРУ!</b>\n\n"
            f"📍 <b>Локація:</b> {city_meta['icon']} <b>{city_meta['name']}</b> — {dist_name} район\n"
            f"⚠️ <b>Характер загрози:</b> {threat_title}\n"
            f"🎯 <b>Деталі обстановки:</b> {threat_desc}\n\n"
            f"🛡️ <i>Негайно перейдіть в укриття або скористайтесь правилом «двох стін»!</i>"
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
