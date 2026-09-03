from unittest.mock import MagicMock, patch
from worker.tasks import cached_geocode, _geocode_cache_key


def test_geocode_cache_key_deterministic():
    k1 = _geocode_cache_key("Ірпінь, Київська область, Україна")
    k2 = _geocode_cache_key("  ірпінь, київська область, україна  ")
    assert k1 == k2
    assert k1.startswith("geo:")


def test_cached_geocode_hits_redis():
    mock_redis = MagicMock()
    mock_redis.get.return_value = b"POINT(30.45 50.45)"

    with patch("worker.tasks.redis_client", mock_redis):
        with patch("worker.tasks.geolocator.geocode") as mock_geo:
            res = cached_geocode("Тестова локація")
            assert res == "POINT(30.45 50.45)"
            # Nominatim should NOT be called on cache hit
            mock_geo.assert_not_called()


def test_cached_geocode_miss_stores_in_redis():
    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    fake_loc = MagicMock()
    fake_loc.longitude = 30.5234
    fake_loc.latitude = 50.4501

    with patch("worker.tasks.redis_client", mock_redis):
        with patch("worker.tasks.geolocator.geocode", return_value=fake_loc) as mock_geo:
            res = cached_geocode("Київ, Хрещатик")
            assert res == "POINT(30.5234 50.4501)"
            mock_geo.assert_called_once()
            # Must write to Redis with TTL 86400s
            mock_redis.setex.assert_called_once()
            args = mock_redis.setex.call_args[0]
            assert args[0].startswith("geo:")
            assert args[1] == 86400
            assert args[2] == "POINT(30.5234 50.4501)"
