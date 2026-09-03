import os
import asyncio
import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import json
from worker.celery_app import app as celery_app
import redis.asyncio as aioredis

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
# Accept comma-separated strings for session pooling
SESSION_STRINGS_RAW = os.getenv("SESSION_STRING", "")
SESSION_STRINGS = [s.strip() for s in SESSION_STRINGS_RAW.split(",") if s.strip()]
TARGET_CHANNELS = [ch.strip() for ch in os.getenv("TARGET_CHANNELS", "").split(",") if ch.strip()]
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
MAX_VIDEO_DURATION_S = 120
MAX_VIDEO_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

def extract_forward_source(msg):
    if not getattr(msg, 'fwd_from', None):
        return None
    fwd = msg.fwd_from
    if getattr(fwd, 'from_name', None):
        return str(fwd.from_name)
    if getattr(fwd, 'from_id', None):
        f_id = getattr(fwd.from_id, 'channel_id', None) or getattr(fwd.from_id, 'user_id', None) or getattr(fwd.from_id, 'chat_id', None)
        if f_id:
            return str(f_id)
    return None


async def perform_sync(client, valid_channels):
    """Fetches the latest messages from the last 24 hours from all target channels."""
    threshold_dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
    backfilled_count = 0

    print(f"🚀 Performing deep on-demand sync for {len(valid_channels)} channels...")
    for entity in valid_channels:
        try:
            ch_name = getattr(entity, 'username', None) or str(entity.id)
            recent_msgs = await client.get_messages(entity, limit=10)
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
                        "media_path": None,
                        "fwd_from": extract_forward_source(msg)
                    }
                    celery_app.send_task('worker.tasks.process_message', args=[json.dumps(payload)])
                    backfilled_count += 1
            print(f"  • Synced @{ch_name}")
        except Exception as ex:
            print(f"  ⚠️ Sync warning for {getattr(entity, 'username', 'channel')}: {ex}")
            
    print(f"✅ On-demand sync finished: {backfilled_count} messages pushed to queue.")
    return backfilled_count


async def listen_for_sync_commands(clients_dict):
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
                        # Run sync on all clients for their assigned channels
                        tasks = []
                        for client, channels in clients_dict.items():
                            tasks.append(perform_sync(client, channels))
                        await asyncio.gather(*tasks)
                await asyncio.sleep(0.5)
            except Exception as e:
                await asyncio.sleep(1.0)
    except Exception as exc:
        print(f"Redis subscriber error: {exc}")

def chunk_list(lst, n):
    """Yield successive chunks from lst to distribute channels."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

async def main():
    if not SESSION_STRINGS:
        print("No SESSION_STRING provided. Exiting listener.")
        return

    os.makedirs("/app/media", exist_ok=True)
    
    print(f"Initializing {len(SESSION_STRINGS)} Telethon sessions (Pool Mode)...")
    clients = []
    for idx, sstr in enumerate(SESSION_STRINGS):
        client = TelegramClient(StringSession(sstr), API_ID, API_HASH)
        await client.start()
        clients.append(client)
        print(f"✅ Session {idx+1}/{len(SESSION_STRINGS)} authenticated.")

    # Validate channels using the first client (they are global anyway)
    print("Validating channels...")
    valid_channels_names = []
    for ch in TARGET_CHANNELS:
        try:
            # just verifying the entity exists
            await clients[0].get_entity(ch)
            valid_channels_names.append(ch)
        except Exception as e:
            print(f"❌ Skipping invalid channel {ch}: {e}")

    if not valid_channels_names:
        print("No valid channels found. Exiting.")
        return

    # Distribute channels evenly across the pool (round-robin)
    clients_dict = {client: [] for client in clients}
    for idx, ch in enumerate(valid_channels_names):
        assigned_client = clients[idx % len(clients)]
        clients_dict[assigned_client].append(ch)
    
    for idx, (client, assigned_channels) in enumerate(clients_dict.items()):
        if not assigned_channels:
            continue
        print(f"🤖 Assigning {len(assigned_channels)} channels to Session {idx+1}")
        
        valid_entities = []
        for ch in assigned_channels:
            try:
                ent = await client.get_entity(ch)
                valid_entities.append(ent)
            except Exception as e:
                print(f"⚠️ Error resolving {ch} on Session {idx+1}: {e}")
        
        # Register handler specifically for this client's chunk of channels
        @client.on(events.NewMessage(chats=valid_entities))
        async def handler(event, current_client=client): # Capture client in closure
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
            elif getattr(msg, 'video', None):
                # Videos were previously ignored entirely (has_media=True but
                # media_path stayed None, so no OSINT ever ran on them).
                # Bound duration/size before downloading — strike footage is
                # usually short; long videos aren't worth the bandwidth/disk
                # for a single representative frame downstream.
                try:
                    duration = getattr(msg.file, 'duration', None) or 0
                    size = getattr(msg.file, 'size', None) or 0
                    if duration <= MAX_VIDEO_DURATION_S and size <= MAX_VIDEO_SIZE_BYTES:
                        file_name = f"video_{msg.id}.mp4"
                        path = f"/app/media/{file_name}"
                        await msg.download_media(file=path)
                        media_path = path
                    else:
                        print(f"Skipping oversized/long video msg {msg.id}: duration={duration}s size={size}B")
                except Exception as e:
                    print(f"Failed to download video: {e}")

            payload = {
                "channel": event.chat.username or str(event.chat_id),
                "message_id": msg.id,
                "text": msg.text or "",
                "date": msg.date.isoformat() if msg.date else None,
                "views": msg.views or 0,
                "forwards": msg.forwards or 0,
                "has_media": bool(msg.media),
                "media_path": media_path,
                "fwd_from": extract_forward_source(msg)
            }
            
            celery_app.send_task('worker.tasks.process_message', args=[json.dumps(payload)])
            print(f"Pushed live msg {msg.id} from {payload['channel']} to Celery (via Session)")

    # Initial sync
    sync_tasks = []
    for client, channels in clients_dict.items():
        sync_tasks.append(perform_sync(client, channels))
    await asyncio.gather(*sync_tasks)

    # Start Redis sync command listener in background
    asyncio.create_task(listen_for_sync_commands(clients_dict))

    # Start Redis heartbeat
    async def heartbeat_redis():
        r = aioredis.from_url(REDIS_URL)
        while True:
            try:
                await r.set("telethon_last_ping", datetime.datetime.utcnow().isoformat())
            except Exception:
                pass
            await asyncio.sleep(60)
            
    asyncio.create_task(heartbeat_redis())
    
    # Background periodic sync every 45s so no messages are ever lost or delayed
    async def periodic_sync():
        while True:
            await asyncio.sleep(45)
            try:
                tasks = [perform_sync(c, chs) for c, chs in clients_dict.items()]
                await asyncio.gather(*tasks)
            except Exception as pe:
                print(f"Periodic sync warning: {pe}")
                
    asyncio.create_task(periodic_sync())

    print(f"Listener active for {len(valid_channels_names)} channels across {len(clients)} sessions. Waiting for live messages...")
    await asyncio.gather(*[client.run_until_disconnected() for client in clients])

if __name__ == "__main__":
    asyncio.run(main())
