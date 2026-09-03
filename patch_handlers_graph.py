import sys

content = open("bot/handlers.py").read()

new_handlers = """
from bot.graph_generator import generate_analytics_graph

@router.message(Command("graph"))
@router.message(F.text == "📈 Графік активності")
async def cmd_graph(message: types.Message):
    await message.answer("⏳ Малюю графік активності за 24 години...")
    try:
        loop = asyncio.get_event_loop()
        import functools
        graph_file = await loop.run_in_executor(None, functools.partial(generate_analytics_graph, hours=24))
        
        if graph_file:
            await message.answer_photo(
                photo=types.BufferedInputFile(graph_file.getvalue(), filename=graph_file.name),
                caption="📈 **Динаміка інцидентів та цілей (останні 24 год)**",
                parse_mode="Markdown"
            )
        else:
            await message.answer("Немає достатньо даних для побудови графіка.")
    except Exception as e:
        logger.error(f"Graph error: {e}")
        await message.answer("❌ Помилка генерації графіка.")
"""

if "from bot.export" in content:
    content = content.replace("from bot.export", new_handlers + "\nfrom bot.export")
    open("bot/handlers.py", "w").write(content)
    print("Patched handlers.py with graph")
else:
    print("Could not find insertion point!")
