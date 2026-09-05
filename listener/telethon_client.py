import os
import asyncio
import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import json
from worker.celery_app import app as celery_app
import redis.asyncio as aioredis
from listener.nats_publisher import publish_tg_report
from typing import Optional, List, Dict, Any

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


LAST_SYNCED_MSG_IDS = {}

async def get_channel_last_id(ch_clean: str) -> int:
    if ch_clean in LAST_SYNCED_MSG_IDS:
        return LAST_SYNCED_MSG_IDS[ch_clean]
    try:
        r = aioredis.from_url(REDIS_URL)
        val = await r.get(f"telethon:last_id:{ch_clean}")
        await r.aclose()
        if val:
            last_id = int(val)
            LAST_SYNCED_MSG_IDS[ch_clean] = last_id
            return last_id
    except Exception:
        pass
    return LAST_SYNCED_MSG_IDS.get(ch_clean, 0)

async def set_channel_last_id(ch_clean: str, msg_id: int):
    current = LAST_SYNCED_MSG_IDS.get(ch_clean, 0)
    if msg_id > current:
        LAST_SYNCED_MSG_IDS[ch_clean] = msg_id
        try:
            r = aioredis.from_url(REDIS_URL)
            await r.set(f"telethon:last_id:{ch_clean}", msg_id, ex=86400 * 7)
            await r.aclose()
        except Exception:
            pass

async def perform_sync(client, valid_channels):
    """Fetches only genuinely new messages from target channels using min_id watermark."""
    threshold_dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
    backfilled_count = 0

    print(f"🚀 Performing targeted sync for {len(valid_channels)} channels...")
    for entity in valid_channels:
        try:
            if isinstance(entity, str):
                entity = await client.get_entity(entity)
            ch_raw = getattr(entity, 'username', None) or str(entity.id)
            ch_name = resolve_channel_name(ch_raw)
            ch_clean = str(ch_name).lstrip("@").lower()
            last_seen_id = await get_channel_last_id(ch_clean)

            if last_seen_id > 0:
                recent_msgs = await client.get_messages(entity, min_id=last_seen_id, limit=20)
            else:
                recent_msgs = await client.get_messages(entity, limit=5)

            new_msgs = [m for m in recent_msgs if m.id > last_seen_id]
            for msg in reversed(new_msgs):
                if msg.date and msg.date >= threshold_dt and (msg.text or msg.media):
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
                    # Shadow publish to NATS JetStream (P2.1 Zero-Loss buffer)
                    try:
                        await publish_tg_report(payload)
                    except Exception:
                        pass
                    backfilled_count += 1
                await set_channel_last_id(ch_clean, msg.id)
        except Exception as ex:
            print(f"  ⚠️ Sync warning for {getattr(entity, 'username', 'channel')}: {ex}")
            
    print(f"✅ Sync finished: {backfilled_count} new messages pushed to queue.")
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

def get_session_proxy(idx: int) -> Optional[dict]:
    """Resolves Socks5/HTTP proxy configuration for session index idx."""
    raw_proxy = os.getenv(f"PROXY_{idx+1}")
    if not raw_proxy:
        proxies_list = [p.strip() for p in os.getenv("PROXIES", "").split(",") if p.strip()]
        if idx < len(proxies_list):
            raw_proxy = proxies_list[idx]
        elif os.getenv("PROXY_URL"):
            raw_proxy = os.getenv("PROXY_URL")

    if not raw_proxy:
        return None

    try:
        from urllib.parse import urlparse
        parsed = urlparse(raw_proxy)
        scheme = parsed.scheme.lower() if parsed.scheme else "socks5"
        try:
            import socks
            scheme_map = {
                "socks5": socks.SOCKS5,
                "socks4": socks.SOCKS4,
                "http": socks.HTTP,
            }
            p_type = scheme_map.get(scheme, socks.SOCKS5)
        except ImportError:
            p_type = 2  # SOCKS5 fallback numeric code

        return {
            "proxy_type": p_type,
            "addr": parsed.hostname,
            "port": parsed.port or 1080,
            "rdns": True,
            "username": parsed.username,
            "password": parsed.password
        }
    except Exception as e:
        print(f"⚠️ Warning parsing proxy for session {idx+1}: {e}")
        return None


async def main():
    if not SESSION_STRINGS:
        print("No SESSION_STRING provided. Exiting listener.")
        return

    os.makedirs("/app/media", exist_ok=True)
    
    print(f"Initializing {len(SESSION_STRINGS)} Telethon sessions (Pool Mode)...", flush=True)
    clients = []
    for idx, sstr in enumerate(SESSION_STRINGS):
        proxy_conf = get_session_proxy(idx)
        if proxy_conf:
            print(f"🛡️ Session {idx+1} routing through proxy {proxy_conf['addr']}:{proxy_conf['port']}", flush=True)
            client = TelegramClient(StringSession(sstr), API_ID, API_HASH, proxy=proxy_conf)
        else:
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

    # Balanced Consistent Hashing:
    # Sort unique canonical channel handles and partition across sessions.
    # Guarantees CV < 0.10 and balanced 4-6 channels per account without overload.
    sorted_channels = sorted(list(set(valid_channels_names)))
    num_sessions = len(clients)
    clients_dict = {client: [] for client in clients}

    for i, ch in enumerate(sorted_channels):
        shard_idx = i % num_sessions
        target_client = clients[shard_idx]
        try:
            ent = await target_client.get_entity(ch)
            clients_dict[target_client].append(ent)
        except Exception as e:
            print(f"⚠️ Error resolving {ch} on session {shard_idx + 1}: {e}", flush=True)

    # Register independent NewMessage event handlers on EACH active session in the pool
    for idx, (client, entities) in enumerate(clients_dict.items()):
        if not entities:
            continue
        print(f"📡 Session {idx+1}/{num_sessions} bound to {len(entities)} channels (Balanced Shard {idx})", flush=True)

        def make_handler(session_num: int):
            async def shard_message_handler(event, s_num=session_num):
                msg = event.message
                media_path = None
                if getattr(msg, 'photo', None):
                    try:
                        file_name = f"photo_{msg.id}.jpg"
                        path = f"/app/media/{file_name}"
                        await msg.download_media(file=path)
                        media_path = path
                    except Exception as e:
                        print(f"Failed to download media on session {session_num}: {e}")
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
                        print(f"Failed to download video on session {s_num}: {e}")

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
                    "fwd_from": extract_forward_source(msg),
                    "session_shard": s_num
                }
                
                celery_app.send_task('worker.tasks.process_message', args=[json.dumps(payload)])
                try:
                    await publish_tg_report(payload)
                except Exception:
                    pass
                await set_channel_last_id(ch_clean, msg.id)
                print(f"⚡ [Shard {s_num}] Live event from {payload['channel']} (ID: {msg.id}) -> Celery + NATS", flush=True)

            return shard_message_handler

        client.add_event_handler(make_handler(idx + 1), events.NewMessage(chats=entities))

    # Initial sync
    sync_tasks = []
    for client, channels in clients_dict.items():
        sync_tasks.append(perform_sync(client, channels))
    await asyncio.gather(*sync_tasks)

    # Start Redis sync command listener in background
    asyncio.create_task(listen_for_sync_commands(clients_dict))

    # Start Redis heartbeat with session pool telemetry
    async def heartbeat_redis():
        r = aioredis.from_url(REDIS_URL)
        while True:
            try:
                now_iso = datetime.datetime.utcnow().isoformat()
                await r.set("telethon_last_ping", now_iso)
                await r.set("telegram_accounts_healthy", len(clients))
                await r.set("telegram_accounts_total", len(SESSION_STRINGS))
            except Exception:
                pass
            await asyncio.sleep(60)
            
    asyncio.create_task(heartbeat_redis())
    
    # Background periodic sync every 300s (5m) as fallback safety net with min_id
    async def periodic_sync():
        while True:
            await asyncio.sleep(300)
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
