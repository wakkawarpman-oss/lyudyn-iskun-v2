import asyncio
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
import os

SESSION_STRING = "1AZWarzIBuxn2en4A-VSKAgZyVLFnaT2R6xlRawQoSwkNcO74b_05KqulBNgElHRvDCWppppXr_zFrikxCdK0ChS0KpaCLgAgDpw7RMkcCe-HSvjVy6GDn7EY2VYI7bwT33a8npDVH8dYHeiBZFDdRkKJwK_7cR-bNLmTeqwSS6WGlk0JHW6YmTkEALLHGB_JpcmotxZS6s1X674xibGPfB_Ulb4VYCy433iakf3N5nbyQQ4OuuNX4x5G13J5qMqCJIfPuJ1Yq67itjcsEiUdV97nggOEjxP04Z4MoVmxqhQL8rIPDMnLMO0Sj7vkuwChew308Bdp-Jn-H4uy2sWlyfr7Gsflq6A="
API_ID = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"
BOT_USERNAME = "@lyudyn_iskun_3143_bot"

async def main():
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    
    print("--- Sending /start ---")
    await client.send_message(BOT_USERNAME, "/start")
    
    await asyncio.sleep(2)
    messages = await client.get_messages(BOT_USERNAME, limit=2)
    for msg in messages[::-1]:
        print(f"BOT: {msg.text}")
        if msg.reply_markup:
            print("KEYBOARD:")
            for row in msg.reply_markup.rows:
                buttons = " | ".join([b.text for b in row.buttons])
                print(f"  [{buttons}]")

    print("\n--- Sending '📊 Аналітика' ---")
    await client.send_message(BOT_USERNAME, "📊 Аналітика")
    await asyncio.sleep(2)
    messages = await client.get_messages(BOT_USERNAME, limit=1)
    print(f"BOT: {messages[0].text}")

    print("\n--- Sending '📈 Графік активності' ---")
    await client.send_message(BOT_USERNAME, "📈 Графік активності")
    await asyncio.sleep(4)  # Wait for graph rendering
    messages = await client.get_messages(BOT_USERNAME, limit=1)
    print(f"BOT: {messages[0].text}")
    if messages[0].photo:
        print("BOT (Photo attached)")

    await client.disconnect()

asyncio.run(main())
