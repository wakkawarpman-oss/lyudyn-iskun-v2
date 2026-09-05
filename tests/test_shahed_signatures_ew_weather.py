"""
Unit & Integration Tests for Shahed Signatures, EW Profiles, Wind Drift, and Acoustic Verification.
"""
import pytest
from worker.osint.weather_vector import compute_wind_drift, get_closest_sector_wind
from worker.osint.adsb_intel import get_aviation_intel_summary
from worker.osint.acoustic_gateway import record_acoustic_hit, get_active_acoustic_hits, corroborate_drone_with_acoustics
from worker.osint.neptun_radar import get_live_radar_threats


def test_wind_drift_headwind():
    # North heading (0 deg), Wind from North (0 deg) -> headwind
    res = compute_wind_drift(heading_deg=0.0, air_speed_kmh=180.0, wind_deg=0.0, wind_speed_kmh=30.0)
    assert res["ground_speed_kmh"] == 150.0
    assert res["speed_delta_kmh"] == -30.0
    assert res["drift_angle_deg"] == 0.0


def test_wind_drift_tailwind():
    # North heading (0 deg), Wind from South (180 deg) -> tailwind pushing North
    res = compute_wind_drift(heading_deg=0.0, air_speed_kmh=180.0, wind_deg=180.0, wind_speed_kmh=40.0)
    assert res["ground_speed_kmh"] == 220.0
    assert res["speed_delta_kmh"] == 40.0
    assert res["drift_angle_deg"] == 0.0


def test_wind_drift_crosswind():
    # North heading (0 deg), Wind from West (270 deg) -> pushes East
    res = compute_wind_drift(heading_deg=0.0, air_speed_kmh=180.0, wind_deg=270.0, wind_speed_kmh=30.0)
    assert res["ground_speed_kmh"] > 180.0
    assert res["drift_angle_deg"] > 0.0  # drifts towards East (> 0)


def test_closest_sector_wind():
    # Coordinates in Kyiv
    wind = get_closest_sector_wind(50.45, 30.52)
    assert wind is not None
    assert "wind_speed_kmh" in wind
    assert "wind_direction_deg" in wind
    assert "Київ" in wind["name"]


def test_aviation_intel():
    intel = get_aviation_intel_summary()
    assert intel is not None
    assert "status" in intel
    assert intel["status"] in ("NORMAL", "ELEVATED", "CRITICAL")
    assert "threat_count" in intel


def test_acoustic_gateway_and_corroboration():
    # Record hit near Dnipro
    hit = record_acoustic_hit(
        lat=48.46,
        lng=35.04,
        sensor_id="MIC-DNIPRO-01",
        azimuth=180.0,
        snr_db=22.0,
        drone_frequency_hz=144.0
    )
    assert hit["sensor_id"] == "MIC-DNIPRO-01"

    # Corroborate target at (48.45, 35.05) - within 3 km
    corrob = corroborate_drone_with_acoustics(48.45, 35.05, max_radius_km=15.0)
    assert corrob["corroborated"] is True
    assert corrob["sensor_count"] >= 1


def test_neptun_radar_ew_weather_schema():
    threats = get_live_radar_threats()
    assert "drones" in threats
    for d in threats["drones"][:3]:
        assert "ew_profile" in d
        assert d["ew_profile"]["vtx_5_8_jamming"] is True
        assert "weather_vector" in d
        assert "acoustic_corroborated" in d
