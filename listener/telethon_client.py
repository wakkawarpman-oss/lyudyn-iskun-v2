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

CHANNELS_REGISTRY_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "database", "channels", "channel_registry.json")

def load_target_channels():
    if os.path.exists(CHANNELS_REGISTRY_PATH):
        try:
            with open(CHANNELS_REGISTRY_PATH, "r", encoding="utf-8") as f:
                reg = json.load(f)
            channels = []
            for ob, ch_list in reg.items():
                for c in ch_list:
                    uname = c.get("username", "").strip()
                    if uname:
                        if not uname.startswith("@"):
                            uname = f"@{uname}"
                        if uname not in channels:
                            channels.append(uname)
            if channels:
                print(f"📡 Loaded {len(channels)} target channels from {CHANNELS_REGISTRY_PATH}")
                return channels
        except Exception as e:
            print(f"⚠️ Warning loading channel_registry.json: {e}")
    return [ch.strip() for ch in os.getenv("TARGET_CHANNELS", "").split(",") if ch.strip()]

def get_channel_oblast_map():
    mapping = {}
    if os.path.exists(CHANNELS_REGISTRY_PATH):
        try:
            with open(CHANNELS_REGISTRY_PATH, "r", encoding="utf-8") as f:
                reg = json.load(f)
            for ob, ch_list in reg.items():
                for c in ch_list:
                    uname = c.get("username", "").strip().lstrip("@").lower()
                    mapping[uname] = ob
        except Exception:
            pass
    return mapping

TARGET_CHANNELS = load_target_channels()
CHANNEL_OBLAST_MAP = get_channel_oblast_map()
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
MAX_VIDEO_DURATION_S = 120
MAX_VIDEO_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

ID_TO_CANONICAL_HANDLE = {
    "1181169156": "kievreal1",
    "-1001181169156": "kievreal1",
    "2053889953": "operatyvnyi_monitor",
    "-1002053889953": "operatyvnyi_monitor",
}

def resolve_channel_name(raw_name: str) -> str:
    cleaned = str(raw_name).strip().lstrip("@")
    return ID_TO_CANONICAL_HANDLE.get(cleaned, raw_name)

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
            if isinstance(entity, str):
                entity = await client.get_entity(entity)
            ch_raw = getattr(entity, 'username', None) or str(entity.id)
            ch_name = resolve_channel_name(ch_raw)
            recent_msgs = await client.get_messages(entity, limit=10)
            for msg in recent_msgs:
                if msg.date and msg.date >= threshold_dt and (msg.text or msg.media):
                    ch_clean = str(ch_name).lstrip("@").lower()
                    payload = {
                        "channel": ch_name,
                        "oblast": CHANNEL_OBLAST_MAP.get(ch_clean, "all"),
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
    
    print(f"Initializing {len(SESSION_STRINGS)} Telethon sessions (Pool Mode)...", flush=True)
    clients = []
    for idx, sstr in enumerate(SESSION_STRINGS):
        client = TelegramClient(StringSession(sstr), API_ID, API_HASH)
        await client.start()
        clients.append(client)
        print(f"✅ Session {idx+1}/{len(SESSION_STRINGS)} authenticated.", flush=True)

    # Validate channels using the first client (they are global anyway)
    print("Validating channels...", flush=True)
    valid_channels_names = []
    for ch in TARGET_CHANNELS:
        try:
            # just verifying the entity exists
            await clients[0].get_entity(ch)
            valid_channels_names.append(ch)
        except Exception as e:
            print(f"❌ Skipping invalid channel {ch}: {e}", flush=True)

    if not valid_channels_names:
        print("No valid channels found. Exiting.", flush=True)
        return

    # Bind all channels to clients. Primary session (Session 1) has full resolving rights
    clients_dict = {client: [] for client in clients}
    primary_client = clients[0]

    primary_entities = []
    for ch in valid_channels_names:
        try:
            ent = await primary_client.get_entity(ch)
            primary_entities.append(ent)
        except Exception as e:
            print(f"⚠️ Error resolving {ch} on primary client: {e}", flush=True)

    print(f"📡 Primary Session bound to {len(primary_entities)} active channels across Ukraine!", flush=True)
    clients_dict[primary_client] = primary_entities

    # Register NewMessage handler on primary client
    if primary_entities:
        @primary_client.on(events.NewMessage(chats=primary_entities))
        async def primary_handler(event):
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

            ch_raw = event.chat.username or str(event.chat_id)
            ch_name = resolve_channel_name(ch_raw)
            ch_clean = str(ch_name).lstrip("@").lower()
            payload = {
                "channel": ch_name,
                "oblast": CHANNEL_OBLAST_MAP.get(ch_clean, "all"),
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
            print(f"⚡ Live event from {payload['channel']} (ID: {msg.id}) -> Celery Worker")

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
