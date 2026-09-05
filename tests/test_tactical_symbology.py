import math
import json
from unittest.mock import patch, MagicMock
from worker.osint.neptun_radar import (
    classify_threat,
    get_live_radar_threats,
    calculate_distance_km
)


def test_threat_categories_and_colors():
    """Verifies that all threat types are mapped to distinct categories and colors."""
    cases = [
        ("shahed", "БпЛА Shahed-136", "drone", "#ff3366"),
        ("cruise", "Крилата ракета Калібр", "missile", "#ff0044"),
        ("ballistic", "Балістична ракета Іскандер-М", "ballistic", "#ff00cc"),
        ("kab", "Скидання КАБ по Куп'янську", "kab", "#ffaa00"),
        ("recon", "БпЛА Supercam корегувальник", "recon", "#00bfff"),
        (None, "Невідома повітряна ціль", "generic", "#ff9900"),
    ]
    for threat_type, text, expected_cat, expected_color in cases:
        label, color, cat = classify_threat(threat_type, text)
        assert cat == expected_cat, f"Expected {expected_cat} for {text}, got {cat}"
        assert color == expected_color


def test_waypoints_enrichment_in_radar_threats():
    """Verifies that radar threat processing generates structured waypoints with metadata."""
    mock_payload = {
        "ballistic_threat": False,
        "markers": [
            {
                "id": "target_trk_999",
                "lat": 50.45,
                "lng": 30.52,
                "threat_type": "shahed",
                "place": "Київ",
                "region": "Київська область",
                "text": "Шахед над правим берегом",
                "confidence_0_100": 90,
                "speed_kmh": 185,
                "course_bearing": 270,
                "positions": [
                    {"lat": 50.40, "lng": 30.70, "time": "2026-09-05T10:00:00Z", "speed_kmh": 180, "source": "РЛС Нептун"},
                    {"lat": 50.42, "lng": 30.60, "time": "2026-09-05T10:05:00Z", "speed_kmh": 185, "source": "РЛС Нептун"},
                    {"lat": 50.45, "lng": 30.52, "time": "2026-09-05T10:10:00Z", "speed_kmh": 185, "source": "РЛС Нептун"}
                ]
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp), \
         patch("redis.Redis.from_url") as mock_redis_cls:

        mock_r = MagicMock()
        mock_r.get.return_value = None
        mock_redis_cls.return_value = mock_r

        data = get_live_radar_threats(force_refresh=True)
        assert data["count"] == 1
        threat = data["drones"][0]

        assert "waypoints" in threat
        assert len(threat["waypoints"]) == 3
        wp0 = threat["waypoints"][0]
        assert wp0["lat"] == 50.40
        assert wp0["lng"] == 30.70
        assert wp0["speed_kmh"] == 180
        assert wp0["source"] == "РЛС Нептун"
        assert wp0["index"] == 0

        # Verify trail also matches coordinates
        assert len(threat["trail"]) == 3
        assert threat["trail"][0] == [50.40, 30.70]


def test_geodesic_vector_projection_math():
    """Verifies that geodesic forward projection coordinates calculate correctly."""
    # Starting from Kyiv (50.4501, 30.5234) flying due North (heading 0 deg) at 180 km/h for 15 min
    lat0, lon0 = 50.4501, 30.5234
    speed_kmh = 180.0
    minutes = 15.0
    heading_deg = 0.0

    R = 6371.0
    dist_km = (speed_kmh * minutes) / 60.0  # 45 km
    delta = dist_km / R
    rad_lat = math.radians(lat0)
    rad_lon = math.radians(lon0)
    rad_heading = math.radians(heading_deg)

    lat_proj = math.asin(
        math.sin(rad_lat) * math.cos(delta) +
        math.cos(rad_lat) * math.sin(delta) * math.cos(rad_heading)
    )
    lon_proj = rad_lon + math.atan2(
        math.sin(rad_heading) * math.sin(delta) * math.cos(rad_lat),
        math.cos(delta) - math.sin(rad_lat) * math.sin(lat_proj)
    )

    lat_deg = math.degrees(lat_proj)
    lon_deg = math.degrees(lon_proj)

    # In 15 min at 180 km/h, target moves 45 km North.
    # 45 km / 111.32 km per deg latitude ~ +0.404 deg latitude.
    assert 50.84 <= lat_deg <= 50.87
    # Longitude heading due North should remain practically unchanged
    assert abs(lon_deg - lon0) < 0.01

    # Verify calculated distance between origin and projected point is ~45 km
    actual_dist = calculate_distance_km(lat0, lon0, lat_deg, lon_deg)
    assert abs(actual_dist - 45.0) <= 0.2


def test_api_radar_drones_endpoint():
    """Verifies that API endpoint /api/v1/radar/drones returns enriched targets with waypoints."""
    from api.main import get_radar_drones

    mock_threats = {
        "count": 1,
        "drones": [
            {
                "id": "trk_test",
                "lat": 50.45,
                "lng": 30.52,
                "heading": 90.0,
                "speed_kmh": 200.0,
                "category": "drone",
                "label": "БПЛА Shahed",
                "trail": [[50.40, 30.40], [50.45, 30.52]],
                "waypoints": [
                    {"lat": 50.40, "lng": 30.40, "speed_kmh": 200.0, "source": "РЛС", "time": "2026-09-05T10:00:00Z", "index": 0}
                ]
            }
        ]
    }

    with patch("worker.osint.neptun_radar.get_live_radar_threats", return_value=mock_threats):
        res = get_radar_drones(oblast="kyiv")
        assert res["count"] == 1
        d = res["drones"][0]
        assert d["category"] == "drone"
        assert len(d["waypoints"]) == 1
        assert "estimated_launch" in d
        assert "projected_targets" in d
