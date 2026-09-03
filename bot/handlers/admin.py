import asyncio
from aiogram import Router, types, F
from aiogram.filters import Command

from bot.handlers.utils import safe_send, admin_only, logger
from database.models import SessionLocal, UserApiKey, encrypt_key, decrypt_key

router = Router()


@router.message(Command("key"))
async def cmd_set_key(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip().startswith("sk-"):
        await safe_send(
            message,
            "⚠️ <b>Формат команди:</b>\n"
            "<code>/key sk-proj-ваш_особистий_ключ_openai</code>\n\n"
            "Отримати ключ: <a href='https://platform.openai.com/api-keys'>platform.openai.com/api-keys</a>",
            disable_web_page_preview=True,
        )
        return
    
    raw_key = args[1].strip()
    await _save_user_key(message, raw_key)


@router.message(F.text.startswith("sk-"))
async def cmd_catch_raw_key(message: types.Message):
    raw_key = message.text.strip()
    if len(raw_key) > 20:
        await _save_user_key(message, raw_key)


async def _save_user_key(message: types.Message, raw_key: str):
    db = SessionLocal()
    try:
        uid = message.from_user.id
        uname = message.from_user.username
        user_key = db.query(UserApiKey).filter(UserApiKey.user_id == uid).first()
        if user_key:
            user_key.openai_api_key = encrypt_key(raw_key)
            user_key.username = uname
        else:
            user_key = UserApiKey(user_id=uid, username=uname, openai_api_key=encrypt_key(raw_key))
            db.add(user_key)
        db.commit()
        
        masked = raw_key[:7] + "..." + raw_key[-4:]
        await safe_send(
            message,
            f"✅ <b>Персональний токен OpenAI збережено!</b>\n\n"
            f"🔑 <b>Активний ключ:</b> <code>{masked}</code>\n"
            f"📸 Тепер просто надішліть будь-яке фото в цей чат для повного OSINT-аналізу через Vision AI.\n\n"
            f"<i>Змінити: <code>/key sk-...</code> | Видалити: <code>/delkey</code></i>",
        )
    except Exception as exc:
        db.rollback()
        logger.error(f"Error saving user API key: {exc}")
        await message.answer("❌ Помилка при збереженні токена.")
    finally:
        db.close()


@router.message(Command("delkey"))
@admin_only
async def cmd_del_key(message: types.Message):
    db = SessionLocal()
    try:
        uid = message.from_user.id
        deleted = db.query(UserApiKey).filter(UserApiKey.user_id == uid).delete()
        db.commit()
        if deleted:
            await message.answer("🗑 Ваш персональний токен OpenAI видалено.")
        else:
            await message.answer("ℹ️ У вас не було збереженого персонального токена.")
    finally:
        db.close()


@router.message(Command("mykey"))
async def cmd_my_key(message: types.Message):
    db = SessionLocal()
    try:
        uid = message.from_user.id
        user_key = db.query(UserApiKey).filter(UserApiKey.user_id == uid).first()
        if user_key:
            k = decrypt_key(user_key.openai_api_key)
            masked = k[:7] + "..." + k[-4:]
            await safe_send(
                message,
                f"🔑 <b>Ваш підключений токен:</b> <code>{masked}</code>\n"
                f"🟢 <b>Статус:</b> АКТИВНИЙ\n\n"
                f"<i>Видалити: <code>/delkey</code></i>",
            )
        else:
            await safe_send(
                message,
                "ℹ️ <b>Персональний токен не підключено.</b>\n"
                "Використовується системний ключ (за наявності).\n\n"
                "Підключити власний: <code>/key sk-...</code>",
            )
    finally:
        db.close()


@router.message(F.text == "🔑 Мій ключ")
async def cmd_premium(message: types.Message):
    db = SessionLocal()
    try:
        uid = message.from_user.id
        user_key = db.query(UserApiKey).filter(UserApiKey.user_id == uid).first()
        if user_key:
            k = decrypt_key(user_key.openai_api_key)
            masked = k[:7] + "..." + k[-4:]
            await safe_send(
                message,
                f"💎 <b>Premium Vision AI: АКТИВОВАНО ✅</b>\n\n"
                f"🔑 <b>Ваш токен:</b> <code>{masked}</code>\n"
                f"📸 <b>Безлімітний аналіз фото:</b> Доступний\n\n"
                f"Просто надішліть фото в чат для аналізу!\n\n"
                f"🔹 Змінити токен: <code>/key sk-новий-ключ</code>\n"
                f"🔹 Видалити токен: <code>/delkey</code>",
            )
        else:
            await safe_send(
                message,
                "💎 <b>Підключення власного Vision AI (OpenAI API)</b>\n\n"
                "Ви або ваші колеги можете підключити <b>власний API-токен OpenAI</b> для безлімітного аналізу фото через GPT-4o Vision!\n\n"
                "📖 <b>Інструкція (як отримати ключ за 1 хвилину):</b>\n"
                "1️⃣ Зареєструйтесь / Увійдіть на <a href='https://platform.openai.com/signup'>platform.openai.com</a>\n"
                "2️⃣ Відкрийте розділ <a href='https://platform.openai.com/api-keys'>API Keys</a>\n"
                "3️⃣ Натисніть <b>Create new secret key</b> і скопіюйте його\n"
                "4️⃣ Надішліть ключ сюди боту командою:\n"
                "<code>/key sk-proj-xxxxxxxxxxxxxxxxxxxx</code>\n"
                "<i>(Або просто надішліть ключ текстом у цей чат)</i>\n\n"
                "🛡 <i>Кожен користувач може мати свій окремий ключ. Вся аналітика (звіти, ТОП, карта) — безкоштовна для всіх.</i>",
                disable_web_page_preview=True,
            )
    finally:
        db.close()


@router.message(Command("clean"))
@router.message(Command("flush"))
@router.message(F.text == "🧹 Очистити старі дані")
@admin_only
async def cmd_manual_cleanup(message: types.Message):
    from worker.tasks import cleanup_old_events
    await message.answer("⏳ Запускаю ротацію бази даних та скидання застарілого кешу...")
    res = await asyncio.to_thread(cleanup_old_events, retention_hours=24)
    del_cnt = res.get("deleted_events", 0)
    await message.answer(
        f"✅ **РОТАЦІЮ БД ТА КЕШУ ЗАВЕРШЕНО!**\n\n"
        f"• Очищено застарілих подій (>24 год): **{del_cnt}**\n"
        f"• Скинуто кеш мапи та аналітики Redis: 🟢 **Успішно**\n"
        f"• База оптимізована під оперативне 24-годинне вікно."
    )
