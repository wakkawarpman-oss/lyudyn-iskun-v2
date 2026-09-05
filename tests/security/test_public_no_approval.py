from unittest.mock import patch, MagicMock
from api.main import get_radar_drones, get_map_shelters

def test_public_radar_endpoint_no_approval_needed():
    mock_threats = {
        "count": 1,
        "drones": [
            {
                "id": "trk_pub",
                "lat": 50.4501,
                "lng": 30.5234,
                "heading": 180.0,
                "speed_kmh": 185.0,
                "category": "drone",
                "trail": [[50.4501, 30.5234]],
                "waypoints": [{"lat": 50.4501, "lng": 30.5234}]
            }
        ]
    }
    with patch("worker.osint.neptun_radar.get_live_radar_threats", return_value=mock_threats), \
         patch("api.main.is_tactical_authorized", return_value=False):
        res = get_radar_drones()
        assert res["contour"] == "civilian"
        assert res["coordinates_fidelity"] == "1:1_exact_wgs84"
        assert res["drones"][0]["lat"] == 50.4501
        assert res["drones"][0]["projected_targets"] == []

def test_shelters_endpoint_accessible_publicly():
    mock_db = MagicMock()
    mock_db.query.return_value.all.return_value = []
    res = get_map_shelters(db=mock_db)
    assert "shelters" in res
