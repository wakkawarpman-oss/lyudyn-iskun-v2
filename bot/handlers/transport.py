import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.handlers.utils import safe_send
from bot.alert_monitor import get_current_kyiv_alert_status

logger = logging.getLogger(__name__)
router = Router()

@router.message(Command("transport"))
@router.message(Command("metro"))
@router.message(F.text == "🚇 Метро & Транспорт")
@router.message(F.text.ilike("%метро%"))
@router.message(F.text.ilike("%транспорт%"))
async def cmd_transport_status(message: types.Message):
    status = get_current_kyiv_alert_status()
    is_alert = status.get("is_alert", False)
    
    if is_alert:
        text = (
            "🚇 <b>ОПЕРАТИВНИЙ СТАН ТРАНСПОРТУ КИЄВА (ТРИВАЄ ТРИВОГА)</b>\n\n"
            "🔴 <b>КИЇВСЬКИЙ МЕТРОПОЛІТЕН:</b>\n"
            "• 🛡️ <b>46 підземних станцій</b> працюють цілодобово <b>як укриття</b>.\n"
            "• ⚠️ Рух поїздів наземними ділянками та через мости <b>ПРИЗУПИНЕНО</b>:\n"
            "  — 🔴 <i>Червона лінія:</i> поїзди курсують від «Академмістечка» лише до станції «Театральна» / «Арсенальна».\n"
            "  — 🟢 <i>Зелена лінія:</i> рух через Південний міст до Лівого берега призупинено, поїзди курсують «Сирець» — «Звіринецька».\n"
            "  — 🔵 <i>Синя лінія:</i> працює повністю у підземному контурі.\n\n"
            "🚌 <b>НАЗЕМНИЙ КОМУНАЛЬНИЙ ТРАНСПОРТ:</b>\n"
            "• Автобуси, тролейбуси та трамваї «Київпастранс» <b>призупиняють рух</b> та довозять пасажирів до найближчого укриття.\n\n"
            "🚆 <b>КИЇВСЬКА КІЛЬЦЕВА ЕЛЕКТРИЧКА (Kyiv City Express):</b>\n"
            "• 🟢 <b>ПРОДОВЖУЄ РУХ!</b> Поїзди курсують за графіком, сполучаючи Правий та Лівий береги через залізничний міст.\n\n"
            "<i>Щойно лунає відбій — метро та наземний транспорт відновлюють штатні графіки за 10–15 хвилин.</i>"
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="🟢 Очікувати відбій та відкриття", callback_data="vidbiy:subscribe_next")
        builder.button(text="📍 Мій район", callback_data="dist:show")
        builder.adjust(1)
        await safe_send(message, text, reply_markup=builder.as_markup())
    else:
        text = (
            "🚇 <b>СТАН ТРАНСПОРТУ ТА МЕТРО КИЄВА (ШТАТНИЙ РЕЖИМ)</b>\n\n"
            "🟢 <b>ПОВІТРЯНОЇ ТРИВОГИ НЕМАЄ — ВСЕ ПРАЦЮЄ!</b>\n\n"
            "🚇 <b>КИЇВСЬКИЙ МЕТРОПОЛІТЕН:</b>\n"
            "• ✅ Усі 3 лінії (🔴 Червона, 🔵 Синя, 🟢 Зелена) курсують у звичайному режимі.\n"
            "• ✅ Мостові переходи (міст Метро, Південний міст) <b>ВІДКРИТІ</b> для руху поїздів.\n"
            "• ⏱️ Інтервали руху: у пікові години 2.5–3 хв, міжпікові 5–6 хв.\n\n"
            "🚌 <b>НАЗЕМНИЙ ТРАНСПОРТ:</b>\n"
            "• ✅ Автобуси, тролейбуси, трамваї та маршрутні таксі працюють за повними маршрутами.\n\n"
            "🚆 <b>КІЛЬЦЕВА ЕЛЕКТРИЧКА:</b>\n"
            "• ✅ Рух здійснюється за стандартним розкладом навколо Києва."
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="🔔 Сповіщати про зміни при тривозі", callback_data="vidbiy:subscribe_next")
        builder.button(text="📍 Мій район", callback_data="dist:show")
        builder.adjust(1)
        await safe_send(message, text, reply_markup=builder.as_markup())

@router.callback_query(F.data == "dist:show")
async def cb_dist_show(callback: types.CallbackQuery):
    from bot.handlers.districts import get_user_districts, build_districts_keyboard
    selected = await get_user_districts(callback.message.chat.id)
    text = (
        "📍 <b>ОБЕРІТЬ ВАШ РАЙОН ПРОЖИВАННЯ:</b>\n"
        "Бот миттєво сповістить, якщо БпЛА або ракети прямуватимуть до вашого сектору:"
    )
    await callback.message.reply(text, reply_markup=build_districts_keyboard(selected), parse_mode=ParseMode.HTML)
    await callback.answer()
