import pytest
from unittest.mock import MagicMock, patch
from api.cache_layer import TacticalCacheManager, TTL_RADAR_LIVE, TTL_EVENTS_FEED, TTL_STATS_AGGREGATES


def test_cache_keys_and_versioning():
    cm = TacticalCacheManager(redis_url="redis://localhost:6379/0", version="v3")
    
    assert cm.event_key(72, "kyiv_city") == "api:v3:events:72:kyiv_city"
    assert cm.event_key(24, None) == "api:v3:events:24:all"
    assert cm.stats_key() == "api:v3:stats"
    assert cm.layer_key("shelters") == "api:v3:layers:shelters"
    assert cm.radar_key() == "radar:v3:neptun:live_drones"


def test_metrics_tracking_hits_and_misses():
    cm = TacticalCacheManager(redis_url="redis://localhost:6379/0", version="v3")
    cm._client = MagicMock()

    # Simulate 3 hits, 1 miss
    cm._client.get.side_effect = [
        "{\"data\": 1}",
        "{\"data\": 2}",
        None,
        "{\"data\": 3}"
    ]

    r1 = cm.get("key1")
    r2 = cm.get("key2")
    r3 = cm.get("key3")
    r4 = cm.get("key4")

    assert r1 == {"data": 1}
    assert r3 is None

    metrics = cm.get_metrics()
    assert metrics["hits"] == 3
    assert metrics["misses"] == 1
    assert metrics["total_requests"] == 4
    assert metrics["hit_rate_pct"] == 75.0


def test_scan_and_unlink_invalidation():
    cm = TacticalCacheManager(redis_url="redis://localhost:6379/0", version="v3")
    cm._client = MagicMock()

    # Mock scan_iter to return 3 matching keys
    cm._client.scan_iter.return_value = ["api:v3:events:72:kyiv", "api:v3:events:24:all", "api:v3:events:12:dnipro"]
    cm._client.unlink.return_value = 3

    count = cm.invalidate_pattern("api:v3:events:*")
    assert count == 3
    cm._client.unlink.assert_called_once_with("api:v3:events:72:kyiv", "api:v3:events:24:all", "api:v3:events:12:dnipro")


def test_get_with_ttl_for_stale_while_revalidate():
    cm = TacticalCacheManager(redis_url="redis://localhost:6379/0", version="v3")
    cm._client = MagicMock()
    pipe_mock = MagicMock()
    cm._client.pipeline.return_value = pipe_mock

    # Mock pipeline return: [json_val, ttl_sec]
    pipe_mock.execute.return_value = ["{\"status\": \"ok\"}", 15]

    data, ttl = cm.get_with_ttl("api:v3:stats")
    assert data == {"status": "ok"}
    assert ttl == 15
