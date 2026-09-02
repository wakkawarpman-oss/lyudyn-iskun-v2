with open('/Users/gonzo/Desktop/V2/lyudyn-iskun-v2/bot/handlers.py', 'r') as f:
    content = f.read()

# 1. Add Command handlers
content = content.replace('@router.message(F.text == "📊 Звіт (12 год)")', '@router.message(Command("report"))\n@router.message(F.text == "📊 Звіт (12 год)")')
content = content.replace('@router.message(F.text == "🔥 ТОП подій")', '@router.message(Command("top"))\n@router.message(F.text == "🔥 ТОП подій")')

# 2. Add /help
help_code = """
@router.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "🛠 **Довідка по системі Людин Іскун V2:**\\n\\n"
        "Цей бот використовує ШІ для моніторингу подій у реальному часі.\\n\\n"
        "Доступні команди:\\n"
        "🔹 /start — Головне меню\\n"
        "🔹 /report — Звіт за останні 12 годин\\n"
        "🔹 /top — Найрезонансніші події\\n"
        "🔹 /status — Технічний статус мікросервісів\\n"
        "🔹 /help — Ця довідка\\n\\n"
        "💡 *Також ви можете використовувати кнопки меню знизу або надіслати боту фото для аналізу через Vision AI.*",
        parse_mode=ParseMode.MARKDOWN
    )
"""
content += help_code

with open('/Users/gonzo/Desktop/V2/lyudyn-iskun-v2/bot/handlers.py', 'w') as f:
    f.write(content)
