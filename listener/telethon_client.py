import os
import asyncio
import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import json
from celery import Celery
import redis.asyncio as aioredis

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")
TARGET_CHANNELS = [ch.strip() for ch in os.getenv("TARGET_CHANNELS", "").split(",") if ch.strip()]
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery('worker', broker=REDIS_URL)

async def perform_sync(client, valid_channels):
    """Fetches the latest messages from the last 12 hours from all target channels."""
    threshold_dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=12)
    backfilled_count = 0

    print(f"🚀 Performing on-demand sync for {len(valid_channels)} channels...")
    for entity in valid_channels:
        try:
            ch_name = getattr(entity, 'username', None) or str(entity.id)
            recent_msgs = await client.get_messages(entity, limit=12)
            for msg in recent_msgs:
                if msg.date and msg.date >= threshold_dt and (msg.text or msg.media):
                    payload = {
                        "channel": ch_name,
                        "message_id": msg.id,
                        "text": msg.text or "",
                        "date": msg.date.isoformat() if msg.date else None,
                        "views": msg.views or 0,
                        "forwards": msg.forwards or 0,
                        "has_media": bool(msg.media),
                        "media_path": None
                    }
                    celery_app.send_task('worker.tasks.process_message', args=[json.dumps(payload)])
                    backfilled_count += 1
            print(f"  • Synced @{ch_name}")
        except Exception as ex:
            print(f"  ⚠️ Sync warning for {getattr(entity, 'username', 'channel')}: {ex}")

    print(f"✅ On-demand sync finished: {backfilled_count} messages pushed to queue.")
    return backfilled_count


async def listen_for_sync_commands(client, valid_channels):
    """Listens for on-demand sync events published via Redis."""
    try:
        r = aioredis.from_url(REDIS_URL)
        pubsub = r.pubsub()
        await pubsub.subscribe("sync_commands")
        print("📡 Subscribed to Redis sync_commands channel.")
        while True:
            try:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg.get("data"):
                    data_str = msg["data"].decode('utf-8') if isinstance(msg["data"], bytes) else str(msg["data"])
                    if "sync" in data_str:
                        print("⚡ Triggering on-demand sync from bot button...")
                        await perform_sync(client, valid_channels)
                await asyncio.sleep(0.5)
            except Exception as e:
                await asyncio.sleep(1.0)
    except Exception as exc:
        print(f"Redis subscriber error: {exc}")


async def main():
    if not SESSION_STRING:
        print("No SESSION_STRING provided. Exiting listener.")
        return

    os.makedirs("/app/media", exist_ok=True)
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()

    print("Validating channels...")
    valid_channels = []
    for ch in TARGET_CHANNELS:
        try:
            entity = await client.get_entity(ch)
            valid_channels.append(entity)
            print(f"✅ Verified channel: {ch}")
        except Exception as e:
            print(f"❌ Skipping invalid channel {ch}: {e}")

    if not valid_channels:
        print("No valid channels found. Exiting.")
        return

    # Run initial sync on boot
    await perform_sync(client, valid_channels)

    # Start Redis sync command listener in background
    asyncio.create_task(listen_for_sync_commands(client, valid_channels))

    @client.on(events.NewMessage(chats=valid_channels))
    async def handler(event):
        msg = event.message
        media_path = None
        if getattr(msg, 'photo', None):
            try:
                file_name = f"photo_{msg.id}.jpg"
                path = f"/app/media/{file_name}"
                await msg.download_media(file=path)
                media_path = path
            except Exception as e:
                print(f"Failed to download media: {e}")

        payload = {
            "channel": event.chat.username or str(event.chat_id),
            "message_id": msg.id,
            "text": msg.text or "",
            "date": msg.date.isoformat() if msg.date else None,
            "views": msg.views or 0,
            "forwards": msg.forwards or 0,
            "has_media": bool(msg.media),
            "media_path": media_path
        }
        
        celery_app.send_task('worker.tasks.process_message', args=[json.dumps(payload)])
        print(f"Pushed live msg {msg.id} from {payload['channel']} to Celery")

    print(f"Listener active for {len(valid_channels)} channels. Waiting for live messages & on-demand sync...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
