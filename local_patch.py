import re

with open('/Users/gonzo/Desktop/V2/lyudyn-iskun-v2/bot/handlers.py', 'r') as f:
    content = f.read()

content = re.sub(r'@router\.message\(Command\("ops"\)\).*', '', content, flags=re.DOTALL)

code = """
@router.message(Command("ops"))
@router.message(F.text == "🔫 Спецоперації")
async def cmd_ops_events(message: types.Message):
    db = SessionLocal()
    try:
        events = db.query(DetectedEvent).filter(DetectedEvent.event_type.like('%armed_conflict%')).order_by(DetectedEvent.detected_at.desc()).limit(10).all()
        
        if not events:
            await message.answer("За останні 24 години спецоперацій або збройних конфліктів не зафіксовано.")
            return
            
        report = "🔫 <b>Останні Спецоперації та Збройні конфлікти:</b>\\n\\n"
        for idx, e in enumerate(events, 1):
            report += f"{idx}. <b>{e.event_type.upper()}</b> (Резонанс: {e.resonance_score})\\n"
            report += f"📍 {e.location_text or 'Невідомо'}\\n"
            report += f"Джерело: <a href='https://t.me/{e.source_channel}/{e.message_id}'>@{e.source_channel}</a>\\n\\n"
            
        await message.answer(report, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    finally:
        db.close()
"""
content += code

with open('/Users/gonzo/Desktop/V2/lyudyn-iskun-v2/bot/handlers.py', 'w') as f:
    f.write(content)
