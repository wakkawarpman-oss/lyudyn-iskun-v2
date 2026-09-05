import json
import pytest
from unittest.mock import patch, MagicMock
from api.main import is_tactical_authorized, get_radar_drones, get_active_substation_threats


def test_civilian_contour_drone_exact_kinematics_no_extensions():
    """
    Civilian contour delivers 100% exact WGS-84 coordinates, speed, heading, trail,
    waypoints, and Kalman kinematics, but strictly strips sensitive military targeting
    cones, launch triangulation, EW profiles, and sensor node IDs.
    """
    mock_threats = {
        "count": 1,
        "drones": [
            {
                "id": "trk_shahed_01",
                "lat": 50.4501,
                "lng": 30.5234,
                "heading": 245.0,
                "speed_kmh": 185.0,
                "category": "drone",
                "label": "БПЛА Shahed",
                "trail": [[50.4800, 30.6000], [50.4501, 30.5234]],
                "waypoints": [
                    {"lat": 50.4800, "lng": 30.6000, "speed_kmh": 185.0, "source": "РЛС Нептун", "time": "2026-09-05T12:00:00Z", "index": 0},
                    {"lat": 50.4501, "lng": 30.5234, "speed_kmh": 185.0, "source": "РЛС Нептун", "time": "2026-09-05T12:05:00Z", "index": 1}
                ],
                "eta_cone": {
                    "eta_time_str": "12:14:30",
                    "speed_kmh": 185.0,
                    "bearing_deg": 245.0
                },
                "ew_profile": {"vtx_5_8_jamming": True, "crpa_antenna": "Комета-М"},
                "sigint_corroboration": {"sigint_active": True},
                "corroborating_sensors": ["acoustic_node_04"]
            }
        ]
    }

    with patch("worker.osint.neptun_radar.get_live_radar_threats", return_value=mock_threats), \
         patch("api.main.is_tactical_authorized", return_value=False):
        
        res = get_radar_drones(oblast="kyiv")
        assert res["contour"] == "civilian"
        assert res["coordinates_fidelity"] == "1:1_exact_wgs84"
        
        target = res["drones"][0]
        # 1:1 exact coordinates and kinematics preserved
        assert target["lat"] == 50.4501
        assert target["lng"] == 30.5234
        assert target["heading"] == 245.0
        assert target["speed_kmh"] == 185.0
        assert len(target["trail"]) == 2
        assert target["trail"][1] == [50.4501, 30.5234]
        assert len(target["waypoints"]) == 2
        assert target["waypoints"][1]["lat"] == 50.4501
        assert target["eta_cone"]["eta_time_str"] == "12:14:30"

        # Military extensions strictly stripped
        assert target["projected_targets"] == []
        assert target["estimated_launch"] is None
        assert target["ew_profile"] is None
        assert target["sigint_corroboration"] is None
        assert target["corroborating_sensors"] == []


def test_operational_contour_drone_with_authorized_extensions():
    """
    When an authorized tactical token or Security Officer approval is provided,
    the restricted operational contour receives the targeting cone and launch triangulation.
    """
    mock_threats = {
        "count": 1,
        "drones": [
            {
                "id": "trk_shahed_01",
                "lat": 50.4501,
                "lng": 30.5234,
                "heading": 245.0,
                "speed_kmh": 185.0,
                "category": "drone",
                "label": "БПЛА Shahed",
                "trail": [[50.4800, 30.6000], [50.4501, 30.5234]],
                "waypoints": [{"lat": 50.4501, "lng": 30.5234, "speed_kmh": 185.0}],
                "ew_profile": {"vtx_5_8_jamming": True},
                "sigint_corroboration": {"sigint_active": True},
                "corroborating_sensors": ["node_1"]
            }
        ]
    }

    with patch("worker.osint.neptun_radar.get_live_radar_threats", return_value=mock_threats), \
         patch("api.main.is_tactical_authorized", return_value=True):
        
        res = get_radar_drones(oblast="kyiv")
        assert res["contour"] == "restricted_operational"
        assert res["coordinates_fidelity"] == "1:1_exact_wgs84"
        
        target = res["drones"][0]
        assert target["lat"] == 50.4501
        assert target["lng"] == 30.5234
        assert target["ew_profile"] is not None
        assert target["sigint_corroboration"] is not None
        assert len(target["corroborating_sensors"]) == 1
        assert "projected_targets" in target


def test_active_alerts_restricted_for_civilian_contour():
    """
    Verifies that get_active_substation_threats denies access to unauthenticated callers
    and requires authorization by Security Officer.
    """
    with patch("api.main.is_tactical_authorized", return_value=False):
        data = get_active_substation_threats()
        assert data["status"] == "restricted"
        assert data["contour"] == "civilian"
        assert data["alerts"] == []
        assert "Security Officer" in data["message"]


def test_active_alerts_accessible_when_authorized():
    """
    Verifies that get_active_substation_threats serves dispatch alerts when authorized.
    """
    mock_summary = {
        "active_substation_alerts": 2,
        "alerts": [{"substation": "ПС 750 кВ Київська", "eta_min": 12}],
        "timestamp": "2026-09-05T12:00:00Z"
    }
    with patch("api.main.is_tactical_authorized", return_value=True), \
         patch("worker.osint.threat_dispatcher.get_active_dispatch_summary", return_value=mock_summary):
        data = get_active_substation_threats()
        assert data["contour"] == "restricted_operational"
        assert data["active_substation_alerts"] == 2
