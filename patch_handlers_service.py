import re

content = open("bot/handlers.py").read()

# We need to replace cmd_analytics and cmd_top_events
analytics_pattern = re.compile(r'@router.message\(F.text == "📊 Аналітика"\)\n@router.message\(F.text.ilike\("%аналітик%"\)\)\nasync def cmd_analytics\(message: types.Message\):.*?return', re.DOTALL)
top_pattern = re.compile(r'@router.message\(F.text == "🔥 ТОП подій"\)\nasync def cmd_top_events\(message: types.Message\):.*?return text\s+await message.answer\(text\)', re.DOTALL)

new_analytics = '''from services.analytics_service import AnalyticsService

@router.message(F.text == "📊 Аналітика")
@router.message(F.text.ilike("%аналітик%"))
async def cmd_analytics(message: types.Message):
    await message.answer(AnalyticsService.format_analytics_report(hours=24), parse_mode="Markdown")
'''

new_top = '''@router.message(F.text == "🔥 ТОП подій")
async def cmd_top_events(message: types.Message):
    await message.answer(AnalyticsService.format_top_events_report(hours=24, limit=5), parse_mode="Markdown")
'''

# Wait, the regex might be tricky if it doesn't match perfectly.
# Let's just do a manual string replace or use sed if we can find the exact function.
