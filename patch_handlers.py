import sys

content = open("bot/handlers.py").read()

new_handlers = """
from bot.export import generate_csv_export
from bot.map_generator import generate_static_map

@router.message(Command("csv"))
@router.message(F.text == "📊 Експорт CSV")
async def cmd_csv_export(message: types.Message):
    await message.answer("⏳ Формую базу даних інцидентів (CSV) за 24 години...")
    try:
        csv_file = generate_csv_export(hours=24)
        await message.answer_document(
            document=types.BufferedInputFile(csv_file.getvalue(), filename=csv_file.name),
            caption="✅ Дані OSINT платформи (24h)."
        )
    except Exception as e:
        logger.error(f"CSV error: {e}")
        await message.answer("❌ Помилка експорту.")

@router.message(Command("map"))
@router.message(F.text == "🗺️ Згенерувати Мапу (.png)")
async def cmd_static_map(message: types.Message):
    await message.answer("⏳ Рендеринг тактичної мапи...")
    try:
        # Run in executor so it doesn't block asyncio
        loop = asyncio.get_event_loop()
        import functools
        map_file = await loop.run_in_executor(None, functools.partial(generate_static_map, hours=24))
        
        await message.answer_photo(
            photo=types.BufferedInputFile(map_file.getvalue(), filename=map_file.name),
            caption="🗺️ **Знімок тактичної мапи за останні 24 години**\\nЧервоний: Вибухи/Влучання | Помаранчевий: Шахеди/Радари",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Map generation error: {e}")
        await message.answer("❌ Помилка рендерингу мапи.")
"""

# Insert before "from bot.threat_report import generate_live_threat_assessment"
if "from bot.threat_report" in content:
    content = content.replace("from bot.threat_report", new_handlers + "\nfrom bot.threat_report")
    open("bot/handlers.py", "w").write(content)
    print("Patched handlers.py")
else:
    print("Could not find insertion point!")
