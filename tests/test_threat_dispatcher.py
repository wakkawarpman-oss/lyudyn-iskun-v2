from worker.osint.threat_dispatcher import (
    generate_substation_alerts,
    get_active_dispatch_summary
)


def test_generate_substation_alerts_empty():
    assert generate_substation_alerts([]) == []
    assert generate_substation_alerts([{"lat": None, "lng": 30.5}]) == []


def test_generate_substation_alerts_threat_detection():
    # Drone at (50.5, 30.5) heading South (180 deg) towards Kyiv substations
    mock_drone = {
        "id": "test_shahed_01",
        "label": "БпЛА Shahed-136",
        "lat": 50.6,
        "lng": 30.5,
        "heading": 180.0,
        "speed_kmh": 180.0,
        "estimated_launch": {
            "site_name": "Навля (Брянська обл., РФ)"
        }
    }
    alerts = generate_substation_alerts([mock_drone], max_cone_deg=45.0, max_distance_km=80.0)
    assert len(alerts) >= 1

    first = alerts[0]
    assert "target_name" in first
    assert "voltage" in first
    assert "eta_minutes" in first
    assert first["eta_minutes"] > 0
    assert first["urgency"] in ("CRITICAL", "HIGH", "ELEVATED")
    assert "Навля" in (first["estimated_launch_site"] or "")
    assert "НЕГАЙНО" in first["recommended_action"] or "УВАГА" in first["recommended_action"] or "МОНІТОРИНГ" in first["recommended_action"]


def test_get_active_dispatch_summary():
    mock_drones = [
        {
            "id": "drone_test_02",
            "label": "БпЛА Shahed-136",
            "lat": 50.55,
            "lng": 30.5,
            "heading": 180.0,
            "speed_kmh": 185.0
        }
    ]
    summary = get_active_dispatch_summary(drones=mock_drones)
    assert summary["status"] == "active"
    assert "total_threats_detected" in summary
    assert "critical_immediate_count" in summary
    assert "alerts" in summary
    assert len(summary["alerts"]) >= 1
