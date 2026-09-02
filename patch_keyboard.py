with open('/Users/gonzo/Desktop/V2/lyudyn-iskun-v2/bot/handlers.py', 'r') as f:
    content = f.read()

old_kb = """def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="▶️ Розпочати")
    builder.button(text="📊 Звіт (12 год)")
    builder.button(text="🔥 ТОП подій")
    builder.button(text="📡 Статус системи")
    builder.button(text="💎 Premium")
    builder.adjust(1, 2, 2)
    return builder.as_markup(resize_keyboard=True)"""

new_kb = """def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="▶️ Розпочати")
    builder.button(text="📊 Звіт (12 год)")
    builder.button(text="🔥 ТОП подій")
    builder.button(text="🗺️ Веб-карта")
    builder.button(text="📡 Статус системи")
    builder.button(text="💎 Premium")
    builder.adjust(1, 2, 2, 1)
    return builder.as_markup(resize_keyboard=True)"""

content = content.replace(old_kb, new_kb)

# Add handler for web map
handler_code = """
@router.message(F.text == "🗺️ Веб-карта")
async def cmd_web_map(message: types.Message):
    await message.answer(
        "🗺️ <b>Жива OSINT Мапа</b>\\n\\n"
        "Перегляньте всі події на інтерактивній карті:\\n"
        "👉 http://136.113.156.17/\\n\\n"
        "<i>(Оскільки це тестовий сервер, посилання працює через HTTP. Для відкриття просто натисніть на нього)</i>",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=False
    )
"""

content += handler_code

with open('/Users/gonzo/Desktop/V2/lyudyn-iskun-v2/bot/handlers.py', 'w') as f:
    f.write(content)
