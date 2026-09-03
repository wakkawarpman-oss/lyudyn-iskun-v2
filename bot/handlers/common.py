import os
import random
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile

from bot.keyboards import get_main_keyboard
from bot.handlers.utils import safe_send, logger

router = Router()

CAT_VARIETIES = [
    {
        "type": "meow",
        "files": ["meow_classic.mp3", "meow_kitten.mp3", "meow_clear.mp3", "meow_soft.mp3", "playful_cat.mp3"],
        "title": "🐱 <b>СПРАВЖНІЙ МЯЯЯУУУУ!</b> 🐾",
        "quotes": [
            "🐾 «Штурман вирушає в політ за позитивом!»",
            "🐾 «Супер-кіт на варті гарного настрою!»",
            "🐾 «Космічний корабель коробкового типу готовий до запуску обіймів!»",
            "🐾 «Справжній пухнастий антидепресант на зв'язку!»"
        ]
    },
    {
        "type": "hiss",
        "files": ["hiss_angry.mp3"],
        "title": "😾 <b>СПРАВЖНЄ БОЙОВЕ ШИПІННЯ!</b> ⚡",
        "quotes": [
            "😾 «Тактичний бойовий кіт зашипів на ворожі шахеди! Ворог не пройде!»",
            "😾 «Ш-ш-ш-ш! Режим бойової люті активовано. Смерть окупантам!»",
            "😾 «Кіт-розвідник зафіксував ціль і шипить на радар!»"
        ]
    },
    {
        "type": "purr",
        "files": ["purr_deep.mp3"],
        "title": "🐾 <b>СПРАВЖНЄ ТАКТИЧНЕ МУРКОТІННЯ...</b> 🛡️",
        "quotes": [
            "🐾 «Тактичне антистрес-муркотіння активовано: рівень тривожності знижено до 0%.»",
            "🐾 «Мур-р-р... Небо під надійним захистом сил ППО, відпочивайте.»",
            "🐾 «Генератор справжнього котячого затишку працює на повну потужність!»"
        ]
    }
]


@router.error()
async def global_error_handler(event: types.ErrorEvent):
    logger.error(f"Global Aiogram Error Caught: {event.exception}", exc_info=event.exception)
    try:
        if event.update.message:
            await event.update.message.answer(
                "⚡ <b>Вибачте, виник тимчасовий збій обробки.</b>\n"
                "Система автоматично перезапустила з'єднання. Спробуйте натиснути кнопку ще раз!",
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_keyboard()
            )
    except Exception as exc:
        logger.error(f"Could not send error message to user: {exc}")
    return True


@router.message(Command("help"))
async def cmd_help(message: types.Message):
    await safe_send(
        message,
        "🛠 <b>Довідка по тактичній системі «ОКІНТ-ПРО»:</b>\n\n"
        "<i>«ЗБИРАЄМО • АНАЛІЗУЄМО • ПЕРЕМАГАЄМО»</i>\n\n"
        "Цей бот використовує ШІ та геоаналітику для моніторингу подій у реальному часі.\n\n"
        "Доступні команди:\n"
        "🔹 /threats — Прогноз загроз та стратегічний звіт РФ\n"
        "🔹 /analytics — Оперативна OSINT-аналітика\n"
        "🔹 /report — Звіт за останні 12 годин\n"
        "🔹 /top — Найрезонансніші події\n"
        "🔹 /resonance — Випадкова вибірка гучних подій\n"
        "🔹 /key — Підключити особистий OpenAI токен\n"
        "🔹 /status — Технічний статус мікросервісів\n"
        "🔹 /vidbiy — Швидкий статус та моніторинг відбою\n"
        "🔹 /help — Ця довідка\n\n"
        "<i>Також ви можете використовувати кнопки меню знизу або "
        "надіслати боту фото для аналізу через Vision AI.</i>",
    )


@router.message(Command("meow"))
@router.message(Command("hiss"))
@router.message(Command("purr"))
@router.message(F.text == "🐾 ТУПО МЯВ")
@router.message(F.text == "ТУПО МЯВ")
@router.message(F.text.ilike("%тупо мяв%"))
@router.message(F.text.ilike("%мяв%"))
@router.message(F.text.ilike("%мяу%"))
@router.message(F.text.ilike("%шип%"))
@router.message(F.text.ilike("%мур%"))
async def cmd_meow(message: types.Message):
    txt = (message.text or "").lower()
    
    if "шип" in txt:
        category = next(c for c in CAT_VARIETIES if c["type"] == "hiss")
    elif "мур" in txt:
        category = next(c for c in CAT_VARIETIES if c["type"] == "purr")
    else:
        category = random.choice(CAT_VARIETIES)
        
    quote = random.choice(category["quotes"])
    chosen_file = random.choice(category["files"])
    audio_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), chosen_file)
    
    if os.path.exists(audio_path):
        audio = FSInputFile(audio_path)
        try:
            await message.answer_audio(
                audio,
                caption=f"{category['title']}\n\n{quote}",
                parse_mode=ParseMode.HTML
            )
            return
        except Exception as e:
            logger.warning(f"Audio send failed: {e}")
            
    await safe_send(message, f"{category['title']}\n\n{quote}")
