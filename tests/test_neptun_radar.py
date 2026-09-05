from unittest.mock import patch, MagicMock
import json
from worker.osint.neptun_radar import (
    calculate_distance_km,
    classify_threat,
    get_live_radar_threats,
    KYIV_LAT,
    KYIV_LON
)

def test_calculate_distance_km_known_points():
    # Kyiv to Boryspil (~30 km)
    boryspil_lat, boryspil_lon = 50.35, 30.95
    dist = calculate_distance_km(boryspil_lat, boryspil_lon, KYIV_LAT, KYIV_LON)
    assert 25.0 <= dist <= 40.0

    # Distance to self should be 0
    assert calculate_distance_km(KYIV_LAT, KYIV_LON, KYIV_LAT, KYIV_LON) == 0.0


def test_classify_threat_patterns():
    label, color, cat = classify_threat("shahed", "БПЛА Shahed курсом на Київ")
    assert cat == "drone"
    assert "Shahed" in label

    label, color, cat = classify_threat("raketa", "Пуск крилатої ракети Калібр")
    assert cat == "missile"
    assert "Крилата" in label

    label, color, cat = classify_threat(None, "Зафіксовано балістику Іскандер")
    assert cat == "ballistic"

    label, color, cat = classify_threat("kab", "Пуск КАБів на прикордоння")
    assert cat == "kab"

    label, color, cat = classify_threat("recon", "Розвідник ZALA над районом")
    assert cat == "recon"

    label, color, cat = classify_threat(None, "Невідомий об'єкт")
    assert cat == "generic"


def test_get_live_radar_threats_success():
    mock_response_data = {
        "ballistic_threat": True,
        "markers": [
            {
                "id": "trk_001",
                "lat": 50.30,
                "lng": 30.60,
                "threat_type": "shahed",
                "place": "Обухівський район",
                "region": "Київська область",
                "text": "Шахед у напрямку Києва",
                "confidence_0_100": 95,
                "speed_kmh": 185,
                "course_bearing": 340,
                "positions": [
                    {"lat": 50.20, "lng": 30.65},
                    {"lat": 50.30, "lng": 30.60}
                ]
            },
            {
                "id": "trk_002",
                "lat": 46.50,
                "lng": 32.50,
                "threat_type": "recon",
                "place": "Херсон",
                "region": "Херсонська область",
                "text": "Розвідник над морем",
                "confidence_0_100": 80,
                "speed_kmh": 90,
                "course_bearing": 180,
                "positions": []
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_response_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp), \
         patch("redis.Redis.from_url") as mock_redis_cls:

        mock_r = MagicMock()
        mock_r.get.return_value = None
        mock_redis_cls.return_value = mock_r

        result = get_live_radar_threats(force_refresh=True)

        assert result["count"] == 2
        assert result["ballistic_threat"] is True
        assert result["kyiv_threat_count"] == 1  # trk_001 is near Kyiv (<180km)

        closest = result["drones"][0]
        assert closest["id"] == "trk_001"
        assert closest["is_kyiv_threat"] is True
        assert len(closest["trail"]) == 2
        assert closest["trail"][0] == [50.20, 30.65]

        # Verify Redis caching was performed
        assert mock_r.setex.called


def test_get_live_radar_threats_network_failure():
    with patch("urllib.request.urlopen", side_effect=Exception("Network error")), \
         patch("redis.Redis.from_url") as mock_redis_cls:

        mock_r = MagicMock()
        mock_r.get.return_value = None
        mock_redis_cls.return_value = mock_r

        result = get_live_radar_threats(force_refresh=True)

        assert result["count"] == 0
        assert result["status"] == "offline_fallback"
        assert result["drones"] == []


def test_filter_drones_for_oblast_inbound():
    from worker.osint.neptun_radar import filter_drones_for_oblast
    # trk_direct: 30 km from Kyiv (lat 50.30, lng 30.60)
    # trk_inbound: 90 km from Kyiv, heading 320 towards Kyiv (lat 50.00, lng 31.40)
    # trk_far: 450 km away (lat 46.50, lng 32.50)
    mock_drones = [
        {"id": "trk_direct", "lat": 50.30, "lng": 30.60, "heading": 350, "speed_kmh": 185, "relevant_oblasts": ["kyiv_city"]},
        {"id": "trk_inbound", "lat": 50.00, "lng": 31.40, "heading": 310, "speed_kmh": 185, "relevant_oblasts": ["kyiv_oblast"]},
        {"id": "trk_far", "lat": 46.50, "lng": 32.50, "heading": 180, "speed_kmh": 185, "relevant_oblasts": ["kherson"]}
    ]

    direct, inbound = filter_drones_for_oblast(mock_drones, "kyiv_city")
    assert len(direct) == 1
    assert direct[0]["id"] == "trk_direct"
    assert direct[0]["is_direct_threat"] is True

    assert len(inbound) == 1
    assert inbound[0]["id"] == "trk_inbound"
    assert inbound[0]["is_inbound_threat"] is True
    assert inbound[0]["distance_to_center_km"] < 120.0
