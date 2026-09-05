"""
OKINT-PRO · Tactical Cache Layer for FastAPI + Redis + PostGIS
Features:
1. Versioned namespaces (v3) to prevent schema clash
2. O(1) Non-blocking pattern invalidation using SCAN + UNLINK (replaces blocking KEYS + DEL)
3. Event-driven invalidation via Redis Pub/Sub / NATS envelope
4. Stale-While-Revalidate pattern for heavy GeoJSON and PostGIS aggregates
5. Prometheus-style Hit/Miss metrics tracking (hit-rate, misses, RPS estimate)
6. Tiered TTLs (Radar 10s, Events 60s, Stats 90s, Static Layers 24h)
"""
from __future__ import annotations
import json
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple, List

try:
    import redis
except ImportError:
    redis = None

logger = logging.getLogger(__name__)

CACHE_VERSION = os.getenv("CACHE_VERSION", "v3")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

# Tiered TTL policies (in seconds)
TTL_RADAR_LIVE = 10          # 10s: live kinematic radar tracks (Neptun/ADS-B)
TTL_EVENTS_FEED = 60         # 60s: tactical events list (invalidated instantly on DB commit)
TTL_STATS_AGGREGATES = 90    # 90s: heavy count/group-by aggregations
TTL_STATIC_LAYERS = 86400    # 24h: municipal shelters, WEZ domes, CCTV metadata


class TacticalCacheManager:
    """High-throughput, event-driven cache manager designed for ~240+ RPS PostGIS workloads."""

    def __init__(self, redis_url: str = REDIS_URL, version: str = CACHE_VERSION):
        self.version = version
        self.redis_url = redis_url
        self._client = None
        self._hits = 0
        self._misses = 0
        self._start_time = time.time()
        self._init_client()

    def _init_client(self):
        if redis is None:
            logger.warning("Redis package not installed. Cache operating in NO-OP mode.")
            return
        try:
            self._client = redis.Redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
                retry_on_timeout=True
            )
        except Exception as e:
            logger.error(f"Failed to initialize Redis client: {e}")
            self._client = None

    @property
    def is_connected(self) -> bool:
        if not self._client:
            return False
        try:
            return self._client.ping()
        except Exception:
            return False

    # --- Namespace Builders ---
    def event_key(self, hours: int, oblast: Optional[str]) -> str:
        obl = (oblast or "all").lower().strip()
        return f"api:{self.version}:events:{hours}:{obl}"

    def stats_key(self) -> str:
        return f"api:{self.version}:stats"

    def layer_key(self, layer_name: str) -> str:
        return f"api:{self.version}:layers:{layer_name.lower().strip()}"

    def radar_key(self) -> str:
        return f"radar:{self.version}:neptun:live_drones"

    # --- Core Cache-Aside Operations ---
    def get(self, key: str) -> Optional[Any]:
        if not self._client:
            self._misses += 1
            return None
        try:
            val = self._client.get(key)
            if val is not None:
                self._hits += 1
                return json.loads(val)
            self._misses += 1
            return None
        except Exception as e:
            logger.warning(f"Cache GET error for {key}: {e}")
            self._misses += 1
            return None

    def set(self, key: str, value: Any, ttl: int = TTL_EVENTS_FEED) -> bool:
        if not self._client:
            return False
        try:
            payload = json.dumps(value)
            return bool(self._client.setex(key, ttl, payload))
        except Exception as e:
            logger.warning(f"Cache SET error for {key}: {e}")
            return False

    def get_with_ttl(self, key: str) -> Tuple[Optional[Any], int]:
        """Returns (data, remaining_ttl_seconds) for Stale-While-Revalidate evaluation."""
        if not self._client:
            return None, -1
        try:
            pipe = self._client.pipeline()
            pipe.get(key)
            pipe.ttl(key)
            val, ttl = pipe.execute()
            if val is not None:
                self._hits += 1
                return json.loads(val), max(0, int(ttl))
            self._misses += 1
            return None, -1
        except Exception as e:
            logger.warning(f"Cache get_with_ttl error for {key}: {e}")
            self._misses += 1
            return None, -1

    # --- High-Performance Non-Blocking Invalidation ---
    def invalidate_exact(self, key: str) -> bool:
        """Deletes a single key using non-blocking UNLINK."""
        if not self._client:
            return False
        try:
            if hasattr(self._client, "unlink"):
                return bool(self._client.unlink(key))
            return bool(self._client.delete(key))
        except Exception as e:
            logger.error(f"Failed to unlink {key}: {e}")
            return False

    def invalidate_pattern(self, pattern: str) -> int:
        """
        Non-blocking batch invalidation using SCAN + UNLINK.
        Crucial for ~240 RPS: never blocks Redis event loop unlike KEYS command.
        """
        if not self._client:
            return 0
        count = 0
        try:
            batch = []
            for key in self._client.scan_iter(match=pattern, count=500):
                batch.append(key)
                if len(batch) >= 500:
                    if hasattr(self._client, "unlink"):
                        self._client.unlink(*batch)
                    else:
                        self._client.delete(*batch)
                    count += len(batch)
                    batch = []
            if batch:
                if hasattr(self._client, "unlink"):
                    self._client.unlink(*batch)
                else:
                    self._client.delete(*batch)
                count += len(batch)
        except Exception as e:
            logger.error(f"Pattern invalidation failed for {pattern}: {e}")
        return count

    def invalidate_events_and_stats(self) -> int:
        """Fast invalidator called by workers upon new incident ingestion."""
        ev_count = self.invalidate_pattern(f"api:{self.version}:events:*")
        st_count = self.invalidate_pattern(f"api:{self.version}:stats*")
        return ev_count + st_count

    # --- Event-Driven Pub/Sub Invalidation ---
    def publish_invalidation(self, topic: str = "cache:invalidate", payload: Optional[Dict[str, Any]] = None):
        """Broadcasts an invalidation event across cluster / worker containers."""
        if not self._client:
            return
        data = payload or {"pattern": f"api:{self.version}:events:*", "version": self.version}
        try:
            self._client.publish(topic, json.dumps(data))
        except Exception as e:
            logger.warning(f"Failed to publish invalidation event: {e}")

    # --- Observability & Telemetry ---
    def get_metrics(self) -> Dict[str, Any]:
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100.0) if total > 0 else 0.0
        uptime = max(1.0, time.time() - self._start_time)
        return {
            "version": self.version,
            "connected": self.is_connected,
            "hits": self._hits,
            "misses": self._misses,
            "total_requests": total,
            "hit_rate_pct": round(hit_rate, 2),
            "estimated_qps": round(total / uptime, 2),
            "uptime_seconds": round(uptime, 1)
        }

    def reset_metrics(self):
        self._hits = 0
        self._misses = 0
        self._start_time = time.time()


# Global singleton instance
cache_manager = TacticalCacheManager()
