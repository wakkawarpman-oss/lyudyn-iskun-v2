from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from worker.osint.firms_viirs import (
    haversine_distance_km,
    parse_firms_time,
    fetch_ukraine_thermal_anomalies,
    find_nearby_thermal_anomaly
)

def test_haversine_distance_km():
    # Kyiv to Bila Tserkva (~80 km)
    kyiv_lat, kyiv_lon = 50.4501, 30.5234
    bt_lat, bt_lon = 49.7956, 30.1311
    dist = haversine_distance_km(kyiv_lat, kyiv_lon, bt_lat, bt_lon)
    assert 75.0 <= dist <= 85.0
    assert haversine_distance_km(kyiv_lat, kyiv_lon, kyiv_lat, kyiv_lon) == 0.0


def test_parse_firms_time():
    dt = parse_firms_time("2026-09-03", "0430")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 9
    assert dt.day == 3
    assert dt.hour == 4
    assert dt.minute == 30
    assert dt.tzinfo == timezone.utc

    # Invalid input handling
    assert parse_firms_time("invalid-date", "9999") is None


def test_fetch_ukraine_thermal_anomalies_mock():
    # Mock CSV containing one point inside Ukraine and one in Africa
    mock_csv = (
        "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,confidence,version,bright_ti5,frp,daynight\n"
        "50.4501,30.5234,342.5,0.4,0.4,2026-09-03,0215,N,nominal,2.0NRT,295.2,18.4,N\n"
        "-30.619,28.653,297.8,0.3,0.5,2026-09-03,0001,N,nominal,2.0NRT,280.7,0.28,N\n"
    )

    mock_resp = MagicMock()
    mock_resp.read.return_value = mock_csv.encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp), \
         patch("redis.Redis.from_url") as mock_redis_cls:

        mock_r = MagicMock()
        mock_r.get.return_value = None
        mock_redis_cls.return_value = mock_r

        result = fetch_ukraine_thermal_anomalies(force_refresh=True)

        assert result["status"] == "live"
        assert result["count"] == 1  # Only the point inside Ukraine bbox
        
        anom = result["anomalies"][0]
        assert anom["lat"] == 50.4501
        assert anom["lon"] == 30.5234
        assert anom["frp_mw"] == 18.4
        assert anom["brightness_k"] == 342.5
        assert anom["daynight"] == "N"

        # Verify Redis caching
        assert mock_r.setex.called


def test_find_nearby_thermal_anomaly_correlation():
    mock_anomalies = [
        {
            "lat": 50.4510,
            "lon": 30.5240,
            "brightness_k": 350.0,
            "frp_mw": 25.0,
            "confidence": "high",
            "daynight": "N",
            "acq_time": "2026-09-03T02:00:00+00:00",
            "satellite": "Suomi-NPP VIIRS (375m)"
        },
        {
            "lat": 48.5000,
            "lon": 35.0000,
            "brightness_k": 310.0,
            "frp_mw": 5.0,
            "confidence": "nominal",
            "daynight": "D",
            "acq_time": "2026-09-03T10:00:00+00:00",
            "satellite": "Suomi-NPP VIIRS (375m)"
        }
    ]

    with patch("worker.osint.firms_viirs.fetch_ukraine_thermal_anomalies", return_value={"anomalies": mock_anomalies}):
        # Event in Kyiv near the first anomaly at 02:30 UTC (30 min diff)
        event_dt = datetime(2026, 9, 3, 2, 30, tzinfo=timezone.utc)
        match = find_nearby_thermal_anomaly(50.4501, 30.5234, event_dt=event_dt, max_distance_km=5.0)

        assert match is not None
        assert match["frp_mw"] == 25.0
        assert match["distance_km"] < 1.0

        # Far away event (e.g. Lviv) should return None
        no_match = find_nearby_thermal_anomaly(49.8397, 24.0297, event_dt=event_dt, max_distance_km=5.0)
        assert no_match is None


def test_firms_offline_graceful_fallback():
    with patch("urllib.request.urlopen", side_effect=Exception("NASA FIRMS network timeout")), \
         patch("redis.Redis.from_url") as mock_redis_cls:

        mock_r = MagicMock()
        mock_r.get.return_value = None
        mock_redis_cls.return_value = mock_r

        result = fetch_ukraine_thermal_anomalies(force_refresh=True)

        assert result["status"] == "offline_fallback"
        assert result["count"] == 0
        assert result["anomalies"] == []
