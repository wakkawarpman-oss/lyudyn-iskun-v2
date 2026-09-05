"""
NATS JetStream Tactical Intelligence Publisher.
Handles resilient connection, stream configuration, and zero-loss dispatching
for OSINT Telegram messages and multi-domain sensor feeds.
"""
import asyncio
import json
import logging
import os
from typing import Optional, Dict, Any

try:
    import nats
    from nats.aio.client import Client as NATSClient
    from nats.js import JetStreamContext
    from nats.js.api import StreamConfig, RetentionPolicy, StorageType
    from nats.js.errors import BadRequestError
    HAS_NATS = True
except ImportError:
    HAS_NATS = False
    NATSClient = Any
    JetStreamContext = Any

logger = logging.getLogger(__name__)

NATS_URL = os.getenv("NATS_URL", "nats://nats:4222")
STREAM_NAME = "OSINT_INTEL"
STREAM_SUBJECTS = ["osint.tg.>", "osint.sensor.>"]

_nc: Optional[NATSClient] = None
_js: Optional[JetStreamContext] = None
_lock = asyncio.Lock()


async def get_jetstream() -> Optional[JetStreamContext]:
    """Returns a connected JetStream context, reconnecting if necessary."""
    if not HAS_NATS:
        return None
    global _nc, _js
    if _js is not None and _nc is not None and _nc.is_connected:
        return _js

    async with _lock:
        if _js is not None and _nc is not None and _nc.is_connected:
            return _js

        try:
            logger.info(f"Connecting to NATS at {NATS_URL}...")
            _nc = await nats.connect(
                servers=[NATS_URL],
                connect_timeout=5,
                reconnect_time_wait=2,
                max_reconnect_attempts=10,
                name="okint_listener"
            )
            _js = _nc.jetstream()

            # Ensure durable stream exists
            try:
                await _js.add_stream(
                    StreamConfig(
                        name=STREAM_NAME,
                        subjects=STREAM_SUBJECTS,
                        retention=RetentionPolicy.LIMITS,
                        storage=StorageType.FILE,
                        max_age=86400 * 30,  # 30 days (720h) retention
                        max_msgs=10_000_000,
                        duplicate_window=120.0  # 120s dedup window
                    )
                )
                logger.info(f"Verified NATS JetStream stream '{STREAM_NAME}'.")
            except BadRequestError as be:
                # Stream might already exist with existing configuration
                logger.debug(f"NATS Stream exists or configured: {be}")

            return _js
        except Exception as e:
            logger.warning(f"Failed to connect to NATS JetStream ({e}). Operating in degraded mode.")
            _nc = None
            _js = None
            return None


async def publish_tg_report(payload: Dict[str, Any]) -> bool:
    """Publishes a Telegram report into NATS JetStream with dedup headers.
    
    Returns True if successfully acknowledged by JetStream, False otherwise.
    """
    try:
        js = await get_jetstream()
        if js is None:
            return False

        ch_name = payload.get("channel", "unknown")
        msg_id = payload.get("message_id", 0)
        oblast = payload.get("oblast", "all")
        date_str = str(payload.get("date", ""))

        ch_clean = str(ch_name).lstrip("@").lower().replace("/", "_")
        msg_key = f"{ch_clean}_{msg_id}"
        subject = f"osint.tg.report.{oblast}"

        payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Nats-Msg-Id": msg_key,
            "X-Source-Channel": str(ch_name),
            "X-Detected-At": date_str
        }

        ack = await js.publish(subject, payload_bytes, headers=headers, timeout=3.0)
        logger.debug(f"Published message {msg_key} to NATS {subject} (seq: {ack.seq})")
        return True
    except Exception as ex:
        logger.warning(f"Failed to publish message to NATS JetStream: {ex}")
        return False


async def close_nats():
    """Cleanly closes NATS connection."""
    global _nc, _js
    async with _lock:
        if _nc is not None:
            try:
                await _nc.drain()
                await _nc.close()
            except Exception:
                pass
            _nc = None
            _js = None
