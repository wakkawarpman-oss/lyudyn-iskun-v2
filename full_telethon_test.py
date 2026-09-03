import asyncio
import os
from telethon import TelegramClient, events
from telethon.sessions import StringSession

API_ID = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"

with open(".env", "r") as f:
    for line in f:
        if line.startswith("SESSION_STRING="):
            SESSION_STRING = line.split("=", 1)[1].strip()
            break

BOT_USERNAME = "lyudyn_iskun_3143_bot"

ALL_COMMANDS = [
    ("/start", 8),
    ("📊 Аналітика", 8),
    ("📈 Графік активності", 15),
    ("📊 Експорт CSV", 15),
    ("🗺️ Згенерувати Мапу (.png)", 15),
    ("📥 Експорт прес-релізу", 15),
    ("🖤 ЧОРНИЙ ГУМОР", 8),
    ("👱‍♀️ ДАША (40 МЕМІВ) 🚗💨", 8),
    ("🐾 ТУПО МЯВ", 8),
    ("🔍 Глибокий OSINT", 8),
    ("📡 Статус системи", 8),
    ("🎯 Прогноз загроз", 8),
    ("📖 Довідник ТТХ", 8),
    ("🛸 Радар Контур", 8),
    ("🔥 ТОП подій", 8),
    ("💥 Резонанс", 8),
    ("🔙 Назад до меню", 8),
    ("/status", 8),
    ("/report", 8),
    ("/help", 8),
    ("/top", 8),
]

async def test_bot():
    print("🚀 З'єднання з Telegram...")
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    me = await client.get_me()
    
    results = {}
    
    for cmd, wait_time in ALL_COMMANDS:
        responses = []
        
        async def handler(event, _responses=responses):
            if event.sender_id != me.id:
                has_media = bool(event.message.media)
                text = event.message.message or ""
                btn_count = 0
                if event.message.reply_markup and hasattr(event.message.reply_markup, 'rows'):
                    btn_count = sum(len(row.buttons) for row in event.message.reply_markup.rows)
                
                info = f"ТЕКСТ: {text[:200]}..." if len(text) > 200 else f"ТЕКСТ: {text}"
                if has_media:
                    info += " | 📎 МЕДІА"
                if btn_count > 0:
                    info += f" | 🔘 КНОПОК: {btn_count}"
                _responses.append(info)
        
        # REGISTER HANDLER BEFORE SENDING MESSAGE
        client.add_event_handler(handler, events.NewMessage(chats=BOT_USERNAME))
        await asyncio.sleep(0.3)
        
        print(f"\n{'='*50}")
        print(f"📤 Надсилаю: '{cmd}'")
        await client.send_message(BOT_USERNAME, cmd)
        
        await asyncio.sleep(wait_time)
        client.remove_event_handler(handler)
        
        if responses:
            for i, r in enumerate(responses):
                print(f"  📥 Відповідь {i+1}: {r}")
            results[cmd] = {"status": "✅", "responses": responses}
        else:
            print(f"  ❌ НЕМАЄ ВІДПОВІДІ!")
            results[cmd] = {"status": "❌", "responses": []}

    await client.disconnect()
    
    # Final report
    print(f"\n\n{'='*60}")
    print(f"📊 ПІДСУМКОВИЙ ЗВІТ E2E ТЕСТУВАННЯ")
    print(f"{'='*60}")
    
    passed = 0
    failed = 0
    errors = []
    
    for cmd, data in results.items():
        status = data["status"]
        resp_count = len(data["responses"])
        print(f"  {status} {cmd:40} ({resp_count} відп.)")
        if status == "✅":
            passed += 1
            # Check for error responses
            for r in data["responses"]:
                if "❌ Помилка" in r or "Error" in r:
                    errors.append(f"{cmd}: {r}")
        else:
            failed += 1
    
    print(f"\n{'─'*60}")
    print(f"  ✅ Пройдено: {passed}/{passed+failed}")
    print(f"  ❌ Провалено: {failed}/{passed+failed}")
    if errors:
        print(f"\n  ⚠️  Команди з помилками у відповіді:")
        for e in errors:
            print(f"    - {e}")
    print(f"{'='*60}")

if __name__ == "__main__":
    asyncio.run(test_bot())
